"""
Replay mixin — trace import and playback.

Supported input formats
-----------------------
* **CSV** — the application's own log format (Timestamp, Arb ID, Frame, DLC, Data).
* **ASC** — Vector ASCII log format (parsed by ``can.LogReader``).
* **BLF** — Vector Binary Logging Format (parsed by ``can.LogReader``).

The replay window shows a preview tree with up to 2 000 rows, a speed multiplier
entry, and a Replay button.  Playback runs on a daemon thread so the GUI stays
responsive.  Timing is re-synchronised from the original message timestamps scaled
by the speed multiplier.
"""
import csv
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import can


class ReplayMixin:
    """Mixin that provides the trace import and replay window."""

    def _open_replay_window(self):
        """Open (or raise) the trace import/replay Toplevel window."""
        if hasattr(self, "_replay_win") and self._replay_win \
                and self._replay_win.winfo_exists():
            self._replay_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("Trace Import / Replay")
        win.geometry("800x520")
        win.protocol("WM_DELETE_WINDOW",
                     lambda: (win.destroy(),
                              setattr(self, "_replay_win", None)))
        self._replay_win = win

        # ── Controls row ──────────────────────────────────────────────────────
        ctrl = ttk.Frame(win, padding=4)
        ctrl.pack(fill=tk.X)
        ttk.Button(ctrl, text="Open File…",
                   command=self._replay_open_file).pack(side=tk.LEFT, padx=4)
        ttk.Label(ctrl, text="Speed:").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Entry(ctrl, textvariable=self._replay_speed_var,
                  width=6).pack(side=tk.LEFT)
        ttk.Label(ctrl, text="x").pack(side=tk.LEFT, padx=(0, 12))
        self._btn_replay = ttk.Button(ctrl, text="Replay",
                                      command=self._replay_start,
                                      state=tk.DISABLED)
        self._btn_replay.pack(side=tk.LEFT, padx=4)
        self._replay_info_var = tk.StringVar(value="No file loaded")
        ttk.Label(ctrl, textvariable=self._replay_info_var,
                  foreground="gray").pack(side=tk.LEFT, padx=8)

        # ── Preview tree ──────────────────────────────────────────────────────
        preview = ttk.Frame(win)
        preview.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        cols = ("ts", "id", "frame", "dlc", "data")
        self._replay_tree = ttk.Treeview(preview, columns=cols, show="headings")
        self._replay_tree.heading("ts",    text="Timestamp (s)")
        self._replay_tree.heading("id",    text="Arb ID")
        self._replay_tree.heading("frame", text="Frame")
        self._replay_tree.heading("dlc",   text="DLC")
        self._replay_tree.heading("data",  text="Data (hex)")
        self._replay_tree.column("ts",    width=110, anchor=tk.E)
        self._replay_tree.column("id",    width=100, anchor=tk.CENTER)
        self._replay_tree.column("frame", width=50,  anchor=tk.CENTER)
        self._replay_tree.column("dlc",   width=40,  anchor=tk.CENTER)
        self._replay_tree.column("data",  width=400, anchor=tk.W)
        vsb = ttk.Scrollbar(preview, orient=tk.VERTICAL,
                             command=self._replay_tree.yview)
        self._replay_tree.configure(yscrollcommand=vsb.set)
        self._replay_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _replay_open_file(self):
        """Prompt for a trace file, parse it, and populate the preview tree."""
        filename = filedialog.askopenfilename(
            title="Open CAN Trace",
            filetypes=[
                ("All supported", "*.asc *.blf *.csv *.log"),
                ("ASC files",  "*.asc"),
                ("BLF files",  "*.blf"),
                ("CSV files",  "*.csv"),
                ("All files",  "*.*"),
            ],
        )
        if not filename:
            return
        messages = []
        try:
            if filename.lower().endswith(".csv"):
                # Read the app's own CSV format:
                # Timestamp, Arb ID, Frame, DLC, Data
                t0 = None
                with open(filename, newline="") as f:
                    for row in csv.reader(f):
                        if not row or row[0].startswith("Timestamp"):
                            continue
                        try:
                            _, arb_str, frame, _, data_str = \
                                row[0], row[1], row[2], row[3], row[4]
                            if arb_str in ("---", ""):
                                continue
                            arb_id  = int(arb_str, 16)
                            is_ext  = frame.upper() == "EXT"
                            data    = bytes(
                                int(x, 16) for x in data_str.split() if x)
                            # Reconstruct a monotonic timestamp from row index
                            ts_f = float(len(messages)) * 0.01
                            if t0 is None:
                                t0 = ts_f
                            msg = can.Message(
                                timestamp=ts_f,
                                arbitration_id=arb_id,
                                is_extended_id=is_ext,
                                data=data,
                            )
                            messages.append(msg)
                        except Exception:
                            continue
            else:
                with can.LogReader(filename) as reader:
                    for msg in reader:
                        if not msg.is_error_frame:
                            messages.append(msg)
        except Exception as exc:
            messagebox.showerror("Import Error", str(exc),
                                 parent=self._replay_win)
            return

        self._replay_messages = messages
        self._replay_info_var.set(f"{len(messages)} messages loaded")

        # Populate preview
        self._replay_tree.delete(*self._replay_tree.get_children())
        t0 = messages[0].timestamp if messages else 0.0
        for m in messages[:2000]:   # cap preview at 2000 rows
            arb = (f"0x{m.arbitration_id:08X}" if m.is_extended_id
                   else f"0x{m.arbitration_id:03X}")
            data = " ".join(f"{b:02X}" for b in m.data)
            frame = "EXT" if m.is_extended_id else "STD"
            self._replay_tree.insert(
                "", tk.END,
                values=(f"{m.timestamp - t0:.4f}", arb, frame, m.dlc, data))

        self._btn_replay.config(
            state=tk.NORMAL if self.bus else tk.DISABLED)

    def _replay_start(self):
        """Start a daemon thread that sends buffered messages at the requested speed."""
        if not self._replay_messages or self.bus is None:
            return
        try:
            speed = max(0.01, float(self._replay_speed_var.get()))
        except ValueError:
            speed = 1.0
        self._btn_replay.config(state=tk.DISABLED, text="Replaying…")

        def _run():
            msgs = self._replay_messages
            if not msgs:
                return
            t0    = msgs[0].timestamp
            start = time.time()
            for m in msgs:
                if self.bus is None:
                    break
                delay      = (m.timestamp - t0) / speed
                elapsed    = time.time() - start
                sleep_time = delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                try:
                    self.bus.send(m)
                except Exception:
                    break
            self.root.after(
                0, lambda: self._btn_replay.config(
                    state=tk.NORMAL, text="Replay"))

        threading.Thread(target=_run, daemon=True).start()
