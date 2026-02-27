"""
Send mixin — raw and DBC send panels, periodic scheduling, and send-mode toggle.

Responsibilities
----------------
Raw send rows
    Each row has an ID field, an EXT checkbox, eight byte entries (hex-validated),
    a periodic checkbox + interval, a Send button, and a Delete button.

DBC send cards
    Each card shows a message selector at the top, then one entry per signal below
    (enum → Combobox, numeric → Entry with min/max range hint).  Cards can be
    collapsed with the ▼/▶ toggle.  All signals are provided on encode so that
    multiplexed-signal errors cannot occur.

Periodic sending
    Shared by raw and DBC rows via ``_reschedule_periodic`` / ``_stop_periodic``.
    The periodic timer is cancelled *before* any error dialog is shown to prevent
    re-entrant popup loops.

Send-mode toggle
    ``_on_send_mode_change`` swaps the visible sub-panel between raw and DBC.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import can


class SendMixin:
    """Mixin that manages the raw and DBC send panels."""

    # ─── raw send rows ────────────────────────────────────────────────────────

    def _add_send_row(self):
        row = ttk.Frame(self._send_rows_frame)
        row.pack(fill=tk.X, pady=1)

        id_var      = tk.StringVar(value="100")
        ext_var     = tk.BooleanVar(value=False)
        byte_vars   = [tk.StringVar(value="") for _ in range(8)]
        periodic_var = tk.BooleanVar(value=False)
        period_var  = tk.StringVar(value="100")

        row_data = {
            "id_var":      id_var,
            "ext_var":     ext_var,
            "byte_vars":   byte_vars,
            "periodic_var": periodic_var,
            "period_var":  period_var,
            "frame":       row,
            "_after_id":   None,
        }

        ttk.Entry(row, textvariable=id_var, width=9).pack(side=tk.LEFT, padx=(2, 1))
        ttk.Checkbutton(row, variable=ext_var, text="").pack(side=tk.LEFT, padx=1)
        for bv in byte_vars:
            ttk.Entry(row, textvariable=bv, width=3,
                      validate="key", validatecommand=self._vcmd_hex_byte
                      ).pack(side=tk.LEFT, padx=1)

        # Periodic checkbox + interval
        ttk.Checkbutton(row, text="", variable=periodic_var,
                        command=lambda rd=row_data: self._on_periodic_toggle(rd)
                        ).pack(side=tk.LEFT, padx=(10, 1))
        ttk.Entry(row, textvariable=period_var, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Label(row, text="ms").pack(side=tk.LEFT, padx=(0, 2))

        state = tk.NORMAL if self.bus else tk.DISABLED
        btn = ttk.Button(row, text="Send", width=5, state=state,
                         command=lambda rd=row_data: self._send_row_message(rd))
        btn.pack(side=tk.LEFT, padx=(4, 2))
        row_data["btn_send"] = btn
        row_data["send_fn"]  = lambda rd=row_data: self._send_row_message(rd)

        ttk.Button(row, text="X", width=2,
                   command=lambda rf=row, rd=row_data: self._remove_send_row(rf, rd)
                   ).pack(side=tk.LEFT, padx=2)

        self._send_rows.append(row_data)
        self._send_rows_frame.update_idletasks()
        self._send_canvas.configure(scrollregion=self._send_canvas.bbox("all"))
        self._send_canvas.yview_moveto(1.0)

    def _remove_send_row(self, row_frame, row_data):
        self._stop_periodic(row_data)
        row_frame.destroy()
        if row_data in self._send_rows:
            self._send_rows.remove(row_data)
        self._send_rows_frame.update_idletasks()
        self._send_canvas.configure(scrollregion=self._send_canvas.bbox("all"))

    def _send_row_message(self, row_data):
        if self.bus is None:
            return
        try:
            arb_id = int(row_data["id_var"].get().strip(), 16)
            data = []
            for bv in row_data["byte_vars"]:
                val = bv.get().strip()
                if val:
                    data.append(int(val, 16))
            msg = can.Message(
                arbitration_id=arb_id,
                data=bytes(data),
                is_extended_id=row_data["ext_var"].get(),
            )
            self.bus.send(msg)
        except Exception as exc:
            if row_data.get("periodic_var") and row_data["periodic_var"].get():
                self._stop_periodic(row_data)
                row_data["periodic_var"].set(False)
            messagebox.showerror("Send Error", str(exc))

    # ─── DBC send rows ────────────────────────────────────────────────────────

    def _add_dbc_send_row(self):
        """Add a card-style DBC send row: header + one sub-row per signal."""
        card = ttk.Frame(self._dbc_rows_frame, relief=tk.GROOVE, borderwidth=1)
        card.pack(fill=tk.X, pady=2, padx=2)

        msg_var      = tk.StringVar()
        periodic_var = tk.BooleanVar(value=False)
        period_var   = tk.StringVar(value="100")

        row_data = {
            "msg_var":      msg_var,
            "msg_cb":       None,
            "sig_frame":    None,
            "sig_rows":     {},          # sig_name → {"val_var", "_is_enum", "_choices"}
            "periodic_var": periodic_var,
            "period_var":   period_var,
            "btn_send":     None,
            "btn_toggle":   None,
            "_collapsed":   False,
            "frame":        card,
            "_after_id":    None,
        }

        # ── Header row ────────────────────────────────────────────────────────
        hdr = ttk.Frame(card)
        hdr.pack(fill=tk.X, padx=2, pady=(2, 0))

        # Collapse/expand toggle (▼ = expanded, ▶ = collapsed)
        btn_toggle = ttk.Button(hdr, text="▼", width=2,
                                command=lambda rd=row_data: self._toggle_dbc_card(rd))
        btn_toggle.pack(side=tk.LEFT, padx=(0, 2))
        row_data["btn_toggle"] = btn_toggle

        msg_cb = ttk.Combobox(hdr, textvariable=msg_var, width=22, state="readonly")
        if self.db:
            msg_cb["values"] = sorted(m.name for m in self.db.messages)
        msg_cb.pack(side=tk.LEFT, padx=(0, 4))
        msg_cb.bind("<<ComboboxSelected>>",
                    lambda _, rd=row_data: self._on_dbc_msg_change(rd))
        row_data["msg_cb"] = msg_cb

        ttk.Checkbutton(hdr, text="Periodic", variable=periodic_var,
                        command=lambda rd=row_data: self._on_periodic_toggle(rd)
                        ).pack(side=tk.LEFT, padx=(0, 1))
        ttk.Entry(hdr, textvariable=period_var, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Label(hdr, text="ms").pack(side=tk.LEFT, padx=(0, 6))

        state = tk.NORMAL if self.bus else tk.DISABLED
        btn = ttk.Button(hdr, text="Send", width=5, state=state,
                         command=lambda rd=row_data: self._send_dbc_row(rd))
        btn.pack(side=tk.LEFT, padx=(0, 2))
        row_data["btn_send"] = btn
        row_data["send_fn"]  = lambda rd=row_data: self._send_dbc_row(rd)

        ttk.Button(hdr, text="X", width=2,
                   command=lambda cf=card, rd=row_data: self._remove_dbc_send_row(cf, rd)
                   ).pack(side=tk.LEFT, padx=2)

        # ── Signal sub-frame (populated by _on_dbc_msg_change) ────────────────
        sig_frame = ttk.Frame(card)
        sig_frame.pack(fill=tk.X, padx=(20, 2), pady=(2, 4))
        row_data["sig_frame"] = sig_frame

        self._dbc_send_rows.append(row_data)

        # If DBC is already loaded, populate this card immediately
        if self.db:
            msg_names = sorted(m.name for m in self.db.messages)
            if msg_names:
                msg_var.set(msg_names[0])
                self._on_dbc_msg_change(row_data)

        self._dbc_rows_frame.update_idletasks()
        self._dbc_canvas.configure(scrollregion=self._dbc_canvas.bbox("all"))
        self._dbc_canvas.yview_moveto(1.0)

    def _remove_dbc_send_row(self, row_frame, row_data):
        self._stop_periodic(row_data)
        row_frame.destroy()
        if row_data in self._dbc_send_rows:
            self._dbc_send_rows.remove(row_data)
        self._dbc_rows_frame.update_idletasks()
        self._dbc_canvas.configure(scrollregion=self._dbc_canvas.bbox("all"))

    def _toggle_dbc_card(self, row_data):
        """Show or hide the signal sub-frame for a DBC send card."""
        row_data["_collapsed"] = not row_data["_collapsed"]
        if row_data["_collapsed"]:
            row_data["sig_frame"].pack_forget()
            row_data["btn_toggle"].config(text="▶")
        else:
            row_data["sig_frame"].pack(fill=tk.X, padx=(20, 2), pady=(2, 4))
            row_data["btn_toggle"].config(text="▼")
        self._dbc_rows_frame.update_idletasks()
        self._dbc_canvas.configure(scrollregion=self._dbc_canvas.bbox("all"))

    def _on_dbc_msg_change(self, row_data):
        """Rebuild the signal sub-frame to show one row per signal in the chosen message."""
        if self.db is None:
            return
        try:
            db_msg = self.db.get_message_by_name(row_data["msg_var"].get())
        except Exception:
            return

        sig_frame = row_data["sig_frame"]
        # Destroy existing signal widgets
        for w in sig_frame.winfo_children():
            w.destroy()
        row_data["sig_rows"].clear()

        for sig in sorted(db_msg.signals, key=lambda s: s.name):
            sig_row = ttk.Frame(sig_frame)
            sig_row.pack(fill=tk.X, pady=1)

            ttk.Label(sig_row, text=sig.name, width=20, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 4))

            val_var = tk.StringVar()

            if sig.choices:
                labels = [str(v) for v in sig.choices.values()]
                val_var.set(labels[0] if labels else "")
                cb = ttk.Combobox(sig_row, textvariable=val_var,
                                  values=labels, width=14, state="readonly")
                cb.pack(side=tk.LEFT, padx=1)
                row_data["sig_rows"][sig.name] = {
                    "val_var":   val_var,
                    "_is_enum":  True,
                    "_choices":  sig.choices,
                }
            else:
                sig_min = sig.minimum
                sig_max = sig.maximum
                # Default entry value to minimum (or 0)
                default = sig_min if sig_min is not None else 0.0
                val_var.set(str(default))
                entry = ttk.Entry(sig_row, textvariable=val_var, width=12)
                entry.pack(side=tk.LEFT, padx=1)
                unit_text = sig.unit if sig.unit else ""
                # Show range hint when min/max are defined
                if sig_min is not None or sig_max is not None:
                    lo = f"{sig_min}" if sig_min is not None else "-∞"
                    hi = f"{sig_max}" if sig_max is not None else "∞"
                    ttk.Label(sig_row, text=f"{unit_text}  [{lo}, {hi}]",
                              anchor=tk.W, foreground="gray").pack(side=tk.LEFT, padx=(2, 0))
                else:
                    ttk.Label(sig_row, text=unit_text, width=6, anchor=tk.W).pack(side=tk.LEFT)
                row_data["sig_rows"][sig.name] = {
                    "val_var":  val_var,
                    "_is_enum": False,
                    "_min":     sig_min,
                    "_max":     sig_max,
                }
                # Clamp on FocusOut and Return
                clamp_fn = lambda _, rd=row_data, sn=sig.name: self._clamp_signal_entry(rd, sn)
                entry.bind("<FocusOut>", clamp_fn)
                entry.bind("<Return>",   clamp_fn)

        self._dbc_rows_frame.update_idletasks()
        self._dbc_canvas.configure(scrollregion=self._dbc_canvas.bbox("all"))

    def _send_dbc_row(self, row_data):
        if self.bus is None or self.db is None:
            return
        try:
            db_msg = self.db.get_message_by_name(row_data["msg_var"].get())
        except Exception as exc:
            messagebox.showerror("Send Error", str(exc))
            return

        sig_data: dict = {}
        for sig in db_msg.signals:
            entry = row_data["sig_rows"].get(sig.name)
            if entry is None:
                # Signal not in UI (shouldn't happen) — use safe default
                if sig.choices:
                    sig_data[sig.name] = next(iter(sig.choices.keys()), 0)
                elif sig.minimum is not None:
                    sig_data[sig.name] = sig.minimum
                else:
                    sig_data[sig.name] = 0
            elif entry["_is_enum"]:
                label = entry["val_var"].get()
                sig_data[sig.name] = next(
                    (k for k, v in entry["_choices"].items() if str(v) == label), 0)
            else:
                try:
                    val = float(entry["val_var"].get())
                except ValueError:
                    val = 0.0
                # Clamp to DBC-defined range so out-of-range values never
                # cause an encode error (periodic send continues uninterrupted)
                sig_min = entry.get("_min")
                sig_max = entry.get("_max")
                if sig_min is not None and val < sig_min:
                    val = sig_min
                if sig_max is not None and val > sig_max:
                    val = sig_max
                sig_data[sig.name] = val

        try:
            # strict=False: encode available signals without requiring every
            # codec-internal signal (e.g. multiplexed groups not in .signals).
            data = db_msg.encode(sig_data, padding=True, strict=False)
            msg  = can.Message(
                arbitration_id=db_msg.frame_id,
                data=data,
                is_extended_id=db_msg.is_extended_frame,
            )
            self.bus.send(msg)
        except Exception as exc:
            # Stop periodic BEFORE showing the popup so the modal dialog
            # doesn't trigger another send (and another popup) while open.
            if row_data.get("periodic_var") and row_data["periodic_var"].get():
                self._stop_periodic(row_data)
                row_data["periodic_var"].set(False)
            messagebox.showerror("Send Error", str(exc))

    def _clamp_signal_entry(self, row_data, sig_name):
        """Clamp a numeric signal entry to the DBC-defined min/max on FocusOut/Return."""
        entry = row_data["sig_rows"].get(sig_name)
        if entry is None or entry["_is_enum"]:
            return
        try:
            val = float(entry["val_var"].get())
        except ValueError:
            val = 0.0
        sig_min = entry["_min"]
        sig_max = entry["_max"]
        if sig_min is not None and val < sig_min:
            val = sig_min
        if sig_max is not None and val > sig_max:
            val = sig_max
        # Format as int if the value is a whole number, else float
        entry["val_var"].set(int(val) if val == int(val) else val)

    # ─── periodic send (shared by raw and DBC rows) ───────────────────────────

    def _on_periodic_toggle(self, row_data):
        if row_data["periodic_var"].get():
            aid = row_data.get("_after_id")
            if aid:
                self.root.after_cancel(aid)
            self._reschedule_periodic(row_data)
        else:
            self._stop_periodic(row_data)

    def _reschedule_periodic(self, row_data):
        """Send the message then schedule the next call."""
        if not row_data["periodic_var"].get() or self.bus is None:
            row_data["_after_id"] = None
            return
        row_data["send_fn"]()
        try:
            interval = max(10, int(row_data["period_var"].get()))
        except ValueError:
            interval = 100
        row_data["_after_id"] = self.root.after(
            interval, self._reschedule_periodic, row_data)

    def _stop_periodic(self, row_data):
        aid = row_data.get("_after_id")
        if aid:
            self.root.after_cancel(aid)
            row_data["_after_id"] = None

    def _cancel_all_periodic(self):
        """Cancel every running periodic timer and uncheck all periodic boxes."""
        for rd in self._send_rows + self._dbc_send_rows:
            self._stop_periodic(rd)
            if "periodic_var" in rd:
                rd["periodic_var"].set(False)

    # ─── send mode toggle ─────────────────────────────────────────────────────

    def _on_send_mode_change(self):
        if self.send_mode_var.get() == "raw":
            self._dbc_send_frame.pack_forget()
            self._raw_send_frame.pack(fill=tk.X)
        else:
            self._raw_send_frame.pack_forget()
            self._dbc_send_frame.pack(fill=tk.X)

    def _set_send_buttons_state(self, state):
        for rd in self._send_rows + self._dbc_send_rows:
            rd["btn_send"].config(state=state)
