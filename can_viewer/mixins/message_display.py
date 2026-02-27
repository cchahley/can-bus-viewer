"""
Message display mixin — raw formatting, DBC decoding, and signal statistics.

Responsibilities
----------------
* ``_show_message``        — format a raw ``can.Message``, apply the active filter,
                             append it to the ring buffer, insert it into the raw tree,
                             forward to logging, and trigger DBC decoding.
* ``_load_dbc``            — open a DBC file via dialog, parse it with cantools, build
                             the frame-id→name cache, and seed the DBC send panel.
* ``_decode_and_display``  — decode signals from a received frame, create or update the
                             hierarchical symbolic tree, track min/max/count statistics,
                             fill plot buffers, and flash the "changed" highlight.
* ``_remove_highlight``    — ``root.after`` callback that clears the "changed" tag after
                             2 seconds.
"""
import collections
import os
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox

import can

try:
    import cantools
    _CANTOOLS_AVAILABLE = True
except ImportError:
    _CANTOOLS_AVAILABLE = False


class MessageDisplayMixin:
    """Mixin that handles incoming message formatting, DBC decoding, and statistics."""

    # ----------------------------------------------------------------- DBC --

    def _load_dbc(self):
        """Prompt the user to select a DBC file and load it with cantools.

        On success, builds the frame-id → message-name lookup cache, clears the
        symbolic tree, and refreshes all open DBC send cards with the new message list.
        """
        if not _CANTOOLS_AVAILABLE:
            messagebox.showerror(
                "Missing Library",
                "cantools is not installed.\n\nRun:  pip install cantools",
            )
            return
        filename = filedialog.askopenfilename(
            title="Load DBC File",
            filetypes=[("DBC files", "*.dbc"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            self.db = cantools.database.load_file(filename)
        except Exception as exc:
            messagebox.showerror("DBC Error", str(exc))
            return
        self._msg_name_cache = {m.frame_id: m.name for m in self.db.messages}
        self.dbc_var.set(
            f"DBC: {os.path.basename(filename)}  ({len(self.db.messages)} msgs)")

        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()
        self._msg_iids.clear()

        # Refresh plot listbox if the plot window is open
        if self._plot_win and self._plot_win.winfo_exists():
            self._populate_plot_listbox()

        # Refresh all DBC send rows with the new message list
        msg_names = sorted(m.name for m in self.db.messages)
        for rd in self._dbc_send_rows:
            rd["msg_cb"]["values"] = msg_names
            if msg_names:
                if not rd["msg_var"].get() or rd["msg_var"].get() not in msg_names:
                    rd["msg_var"].set(msg_names[0])
                self._on_dbc_msg_change(rd)

    def _decode_and_display(self, msg: can.Message, ts: str, rel: str = "0.000"):
        """Decode ``msg`` signals via DBC and update the symbolic live tree.

        Creates a message-level parent row the first time a frame ID is seen, then
        inserts or updates one child row per signal.  Also updates signal statistics
        (min, max, count), fills plot buffers, and applies the change-highlight.
        """
        if self.db is None or msg.is_error_frame:
            return
        try:
            db_msg = self.db.get_message_by_frame_id(msg.arbitration_id)
        except KeyError:
            return
        try:
            signals = db_msg.decode(msg.data, decode_choices=True)
        except Exception:
            return

        arb_id = msg.arbitration_id

        # Ensure message parent row exists; apply current filter to new rows
        if arb_id not in self._msg_iids:
            msg_iid = self.sym_tree.insert(
                "", tk.END, text=db_msg.name, open=True,
                values=("", "", ts, rel, "", "", ""))
            self._msg_iids[arb_id] = msg_iid
            # Hide immediately if a filter is active and this message doesn't match
            tokens = self._get_filter_tokens()
            if tokens and not self._passes_filter(
                    f"0x{arb_id:x}", "", db_msg.name, tokens):
                self.sym_tree.detach(msg_iid)
        else:
            self.sym_tree.item(self._msg_iids[arb_id],
                               values=("", "", ts, rel, "", "", ""))

        parent_iid = self._msg_iids[arb_id]

        for sig_name, value in signals.items():
            sig_def = db_msg.get_signal_by_name(sig_name)
            unit    = sig_def.unit or ""
            val_str = f"{value:.4g}" if isinstance(value, float) else str(value)
            key     = (arb_id, sig_name)

            # ── Signal statistics ─────────────────────────────────────────────
            stats = self._signal_stats.setdefault(
                key, {"min": None, "max": None, "count": 0})
            stats["count"] += 1
            if isinstance(value, (int, float)):
                fval = float(value)
                if stats["min"] is None or fval < stats["min"]:
                    stats["min"] = fval
                if stats["max"] is None or fval > stats["max"]:
                    stats["max"] = fval
                # ── Plot buffer ───────────────────────────────────────────────
                buf_key = f"{db_msg.name}.{sig_name}"
                if buf_key not in self._plot_buffers:
                    self._plot_buffers[buf_key] = collections.deque(maxlen=500)
                self._plot_buffers[buf_key].append(fval)

            min_str   = f"{stats['min']:.4g}"   if stats["min"] is not None else ""
            max_str   = f"{stats['max']:.4g}"   if stats["max"] is not None else ""
            count_str = str(stats["count"])
            row_vals  = (val_str, unit, ts, rel, min_str, max_str, count_str)

            # ── Update or insert treeview row ─────────────────────────────────
            if key in self._signal_iids:
                iid = self._signal_iids[key]
                self.sym_tree.item(iid, values=row_vals)
                # ── Row highlight on change ───────────────────────────────────
                if (self._highlight_var.get()
                        and self._prev_sig_values.get(key) != val_str):
                    existing = self._highlight_after_ids.get(iid)
                    if existing:
                        self.root.after_cancel(existing)
                    self.sym_tree.item(iid, tags=("changed",))
                    self._highlight_after_ids[iid] = self.root.after(
                        2000, self._remove_highlight, iid)
            else:
                iid = self.sym_tree.insert(
                    parent_iid, tk.END,
                    text=sig_name, values=row_vals)
                self._signal_iids[key] = iid

            self._prev_sig_values[key] = val_str

    # ─── highlight helpers ────────────────────────────────────────────────────

    def _remove_highlight(self, iid):
        """Remove the 'changed' tag from a symbolic tree row (called after 2 s)."""
        try:
            self.sym_tree.item(iid, tags=())
        except Exception:
            pass
        self._highlight_after_ids.pop(iid, None)

    # ------------------------------------------------- message display (raw)

    def _show_message(self, msg: can.Message):
        """Format and display a single received CAN message.

        Computes timestamps, applies the cached filter, appends to the ring buffer,
        inserts into the raw tree (via ``_insert_raw_row``), writes to the log file
        if logging is active, and triggers DBC decoding.
        """
        now = time.time()
        if self._trace_start is None:
            self._trace_start = now
        rel = f"{now - self._trace_start:.3f}"
        ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        tokens = self._filter_tokens  # use cached tokens — no re.split per message

        if msg.is_error_frame:
            data = " ".join(f"{b:02X}" for b in msg.data) if msg.data else ""
            # Error frames always buffered and shown (never filtered out)
            self._raw_buffer.append(
                (ts, rel, "---", "ERR", "---", data, True))
            self._insert_raw_row((ts, rel, "---", "ERR", "---", data), tags=("error",))
            self.error_count += 1
        else:
            arb   = (f"0x{msg.arbitration_id:08X}" if msg.is_extended_id
                     else f"0x{msg.arbitration_id:03X}")
            frame = "EXT" if msg.is_extended_id else "STD"
            data  = " ".join(f"{b:02X}" for b in msg.data)
            # Name resolved from cache — no DB lookup in the hot path
            msg_name = self._msg_name_cache.get(msg.arbitration_id, "")
            self._raw_buffer.append(
                (ts, rel, arb, frame, msg.dlc, data, False))
            if not tokens or self._passes_filter(arb, data, msg_name, tokens):
                self._insert_raw_row((ts, rel, arb, frame, msg.dlc, data))
            self.message_count += 1
            self._decode_and_display(msg, ts, rel)

        if self.log_writer is not None:
            try:
                if self.log_format == "blf":
                    self.log_writer(msg)
                else:
                    arb = ("---" if msg.is_error_frame
                           else (f"0x{msg.arbitration_id:08X}" if msg.is_extended_id
                                 else f"0x{msg.arbitration_id:03X}"))
                    frame = "ERR" if msg.is_error_frame else (
                        "EXT" if msg.is_extended_id else "STD")
                    data = " ".join(f"{b:02X}" for b in msg.data)
                    self.log_writer.writerow([ts, arb, frame,
                                             "" if msg.is_error_frame else msg.dlc,
                                             data])
            except Exception:
                pass
