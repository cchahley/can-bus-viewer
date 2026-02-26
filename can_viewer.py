"""
CAN Bus Viewer - Supports PEAK (PCAN), Vector, and Virtual interfaces
Requires: pip install python-can cantools
"""
import contextlib
import csv
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import queue
from datetime import datetime

import can

try:
    import cantools
    _CANTOOLS_AVAILABLE = True
except ImportError:
    _CANTOOLS_AVAILABLE = False


@contextlib.contextmanager
def _silence_stderr():
    """Suppress C-level stderr (e.g. noisy PCAN API probe messages)."""
    devnull = open(os.devnull, "w")
    old_fd = os.dup(2)
    try:
        os.dup2(devnull.fileno(), 2)
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)
        devnull.close()


class CANViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("CAN Bus Viewer")
        self.root.geometry("1400x920")
        self.root.minsize(900, 620)

        self.bus = None
        self.running = False
        self.message_queue = queue.Queue()
        self.message_count = 0
        self.error_count = 0

        self.log_writer = None
        self.log_file = None
        self.log_format = None

        self.db = None
        self._signal_iids: dict = {}    # (arb_id, sig_name) → treeview iid
        self._msg_iids: dict = {}       # arb_id → message parent row iid
        self._trace_start: float | None = None
        self._send_rows: list = []       # raw send rows
        self._dbc_send_rows: list = []   # DBC send rows

        self._build_ui()
        self._scan_channels()
        self._poll_queue()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        self.bar_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.bar_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM, padx=10, pady=(0, 4))

        conn = ttk.LabelFrame(self.root, text="Connection", padding=8)
        conn.pack(fill=tk.X, padx=10, pady=(8, 2))

        ttk.Label(conn, text="Interface:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.iface_var = tk.StringVar(value="pcan")
        iface_cb = ttk.Combobox(conn, textvariable=self.iface_var,
                                 values=["pcan", "vector", "slcan", "virtual"],
                                 width=8, state="readonly")
        iface_cb.grid(row=0, column=1, padx=4)
        iface_cb.bind("<<ComboboxSelected>>", self._on_iface_change)

        ttk.Label(conn, text="Device:").grid(row=0, column=2, sticky=tk.W, padx=4)
        self.channel_var = tk.StringVar()
        self.channel_cb = ttk.Combobox(conn, textvariable=self.channel_var, width=18)
        self.channel_cb.grid(row=0, column=3, padx=4)

        ttk.Button(conn, text="Rescan", command=self._scan_channels).grid(
            row=0, column=4, padx=(0, 10))

        ttk.Label(conn, text="Bitrate:").grid(row=0, column=5, sticky=tk.W, padx=4)
        self.bitrate_var = tk.StringVar(value="500000")
        ttk.Combobox(conn, textvariable=self.bitrate_var, width=10,
                     values=["125000", "250000", "500000", "1000000"]).grid(
            row=0, column=6, padx=4)

        self.btn_connect = ttk.Button(conn, text="Connect",
                                       command=self._connect, state=tk.DISABLED)
        self.btn_connect.grid(row=0, column=7, padx=(12, 4))

        self.btn_disconnect = ttk.Button(conn, text="Disconnect",
                                          command=self._disconnect, state=tk.DISABLED)
        self.btn_disconnect.grid(row=0, column=8, padx=4)

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_lbl = ttk.Label(conn, textvariable=self.status_var,
                                     foreground="red", width=14)
        self.status_lbl.grid(row=0, column=9, padx=10)

        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=10, pady=2)

        ttk.Button(toolbar, text="Clear", command=self._clear).pack(side=tk.LEFT, padx=4)

        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll",
                         variable=self.autoscroll_var).pack(side=tk.LEFT, padx=4)

        self.btn_log = ttk.Button(toolbar, text="Start Log", command=self._toggle_logging)
        self.btn_log.pack(side=tk.LEFT, padx=(12, 4))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=2)

        ttk.Button(toolbar, text="Load DBC", command=self._load_dbc).pack(
            side=tk.LEFT, padx=4)
        self.dbc_var = tk.StringVar(value="No DBC loaded")
        ttk.Label(toolbar, textvariable=self.dbc_var,
                  foreground="gray").pack(side=tk.LEFT, padx=4)

        self.error_var = tk.StringVar(value="Errors: 0")
        ttk.Label(toolbar, textvariable=self.error_var,
                  foreground="red").pack(side=tk.RIGHT, padx=10)

        self.count_var = tk.StringVar(value="Messages: 0")
        ttk.Label(toolbar, textvariable=self.count_var).pack(side=tk.RIGHT, padx=10)

        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              sashrelief=tk.RAISED, sashwidth=5)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # Left: Raw CAN  (time, rel, id, ext, dlc, data)
        raw_frame = ttk.LabelFrame(pane, text="Raw CAN")
        pane.add(raw_frame, minsize=420)

        raw_cols = ("time", "rel", "id", "ext", "dlc", "data")
        self.tree = ttk.Treeview(raw_frame, columns=raw_cols, show="headings")
        self.tree.heading("time", text="Timestamp")
        self.tree.heading("rel",  text="Rel (s)")
        self.tree.heading("id",   text="Arb ID (hex)")
        self.tree.heading("ext",  text="Frame")
        self.tree.heading("dlc",  text="DLC")
        self.tree.heading("data", text="Data (hex)")
        self.tree.column("time", width=110, anchor=tk.W)
        self.tree.column("rel",  width=72,  anchor=tk.E)
        self.tree.column("id",   width=100, anchor=tk.CENTER)
        self.tree.column("ext",  width=50,  anchor=tk.CENTER)
        self.tree.column("dlc",  width=38,  anchor=tk.CENTER)
        self.tree.column("data", width=260, anchor=tk.W)

        raw_vsb = ttk.Scrollbar(raw_frame, orient=tk.VERTICAL,   command=self.tree.yview)
        raw_hsb = ttk.Scrollbar(raw_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=raw_vsb.set, xscrollcommand=raw_hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        raw_vsb.grid(row=0, column=1, sticky="ns")
        raw_hsb.grid(row=1, column=0, sticky="ew")
        raw_frame.rowconfigure(0, weight=1)
        raw_frame.columnconfigure(0, weight=1)

        # Right: Symbolic — tree view, Message parent → Signal children
        sym_frame = ttk.LabelFrame(pane, text="Symbolic (DBC Decoded)")
        pane.add(sym_frame, minsize=320)

        sym_cols = ("value", "unit", "timestamp", "rel")
        self.sym_tree = ttk.Treeview(sym_frame, columns=sym_cols, show="tree headings")
        self.sym_tree.heading("#0",        text="Message / Signal", anchor=tk.W)
        self.sym_tree.heading("value",     text="Value")
        self.sym_tree.heading("unit",      text="Unit")
        self.sym_tree.heading("timestamp", text="Timestamp")
        self.sym_tree.heading("rel",       text="Rel (s)")
        self.sym_tree.column("#0",        width=170, anchor=tk.W)
        self.sym_tree.column("value",     width=80,  anchor=tk.E)
        self.sym_tree.column("unit",      width=45,  anchor=tk.W)
        self.sym_tree.column("timestamp", width=100, anchor=tk.W)
        self.sym_tree.column("rel",       width=65,  anchor=tk.E)

        sym_vsb = ttk.Scrollbar(sym_frame, orient=tk.VERTICAL, command=self.sym_tree.yview)
        self.sym_tree.configure(yscrollcommand=sym_vsb.set)
        self.sym_tree.grid(row=0, column=0, sticky="nsew")
        sym_vsb.grid(row=0, column=1, sticky="ns")
        sym_frame.rowconfigure(0, weight=1)
        sym_frame.columnconfigure(0, weight=1)

        self._build_send_panel()

    # ─────────────────────────────────────────────────── Send panel ──────────

    def _build_send_panel(self):
        sf = ttk.LabelFrame(self.root, text="Send CAN Message", padding=4)
        sf.pack(fill=tk.X, padx=10, pady=(0, 4))

        # Register hex-byte validator once on the root widget
        self._vcmd_hex_byte = (self.root.register(self._validate_hex_byte), "%P")

        # Mode selector
        mode_row = ttk.Frame(sf)
        mode_row.pack(fill=tk.X, pady=(0, 4))
        self.send_mode_var = tk.StringVar(value="raw")
        ttk.Radiobutton(mode_row, text="Raw", variable=self.send_mode_var,
                        value="raw", command=self._on_send_mode_change).pack(
            side=tk.LEFT, padx=(0, 2))
        ttk.Radiobutton(mode_row, text="DBC Signal", variable=self.send_mode_var,
                        value="dbc", command=self._on_send_mode_change).pack(
            side=tk.LEFT)

        # ── Raw mode ──────────────────────────────────────────────────────────
        self._raw_send_frame = ttk.Frame(sf)
        self._raw_send_frame.pack(fill=tk.X)

        # Header row
        raw_hdr = ttk.Frame(self._raw_send_frame)
        raw_hdr.pack(fill=tk.X, padx=2)
        ttk.Label(raw_hdr, text="ID (hex)", width=9, anchor=tk.W).pack(side=tk.LEFT, padx=(2, 1))
        ttk.Label(raw_hdr, text="Ext",      width=4, anchor=tk.CENTER).pack(side=tk.LEFT, padx=1)
        for i in range(8):
            ttk.Label(raw_hdr, text=f"B{i}", width=3, anchor=tk.CENTER).pack(side=tk.LEFT, padx=1)
        ttk.Label(raw_hdr, text="Periodic", anchor=tk.W).pack(side=tk.LEFT, padx=(10, 1))
        ttk.Label(raw_hdr, text="ms",       anchor=tk.W).pack(side=tk.LEFT, padx=1)

        # Scrollable canvas
        raw_outer = ttk.Frame(self._raw_send_frame)
        raw_outer.pack(fill=tk.X, padx=2)
        self._send_canvas = tk.Canvas(raw_outer, height=120, highlightthickness=0)
        raw_vsb = ttk.Scrollbar(raw_outer, orient=tk.VERTICAL,
                                 command=self._send_canvas.yview)
        self._send_canvas.configure(yscrollcommand=raw_vsb.set)
        self._send_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        raw_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._send_rows_frame = ttk.Frame(self._send_canvas)
        self._send_canvas_window = self._send_canvas.create_window(
            (0, 0), window=self._send_rows_frame, anchor=tk.NW)
        self._send_rows_frame.bind("<Configure>", self._on_send_frame_configure)
        self._send_canvas.bind("<Configure>", self._on_send_canvas_configure)
        self._send_canvas.bind("<MouseWheel>",
            lambda e: self._send_canvas.yview_scroll(int(-e.delta / 120), "units"))

        ttk.Button(self._raw_send_frame, text="+ Add Row",
                   command=self._add_send_row).pack(anchor=tk.W, padx=2, pady=2)

        # ── DBC Signal mode (initially hidden) ───────────────────────────────
        self._dbc_send_frame = ttk.Frame(sf)

        # Scrollable canvas (cards are self-labeling — no header row needed)
        dbc_outer = ttk.Frame(self._dbc_send_frame)
        dbc_outer.pack(fill=tk.X, padx=2)
        self._dbc_canvas = tk.Canvas(dbc_outer, height=180, highlightthickness=0)
        dbc_vsb = ttk.Scrollbar(dbc_outer, orient=tk.VERTICAL,
                                  command=self._dbc_canvas.yview)
        self._dbc_canvas.configure(yscrollcommand=dbc_vsb.set)
        self._dbc_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dbc_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._dbc_rows_frame = ttk.Frame(self._dbc_canvas)
        self._dbc_canvas_window = self._dbc_canvas.create_window(
            (0, 0), window=self._dbc_rows_frame, anchor=tk.NW)
        self._dbc_rows_frame.bind("<Configure>", self._on_dbc_frame_configure)
        self._dbc_canvas.bind("<Configure>", self._on_dbc_canvas_configure)
        self._dbc_canvas.bind("<MouseWheel>",
            lambda e: self._dbc_canvas.yview_scroll(int(-e.delta / 120), "units"))

        ttk.Button(self._dbc_send_frame, text="+ Add Row",
                   command=self._add_dbc_send_row).pack(anchor=tk.W, padx=2, pady=2)

        # Seed with initial rows
        for _ in range(3):
            self._add_send_row()
        for _ in range(2):
            self._add_dbc_send_row()

    # ─── canvas resize helpers ────────────────────────────────────────────────

    def _on_send_frame_configure(self, _=None):
        self._send_canvas.configure(scrollregion=self._send_canvas.bbox("all"))

    def _on_send_canvas_configure(self, event):
        self._send_canvas.itemconfig(self._send_canvas_window, width=event.width)

    def _on_dbc_frame_configure(self, _=None):
        self._dbc_canvas.configure(scrollregion=self._dbc_canvas.bbox("all"))

    def _on_dbc_canvas_configure(self, event):
        self._dbc_canvas.itemconfig(self._dbc_canvas_window, width=event.width)

    # ─── hex-byte validation ──────────────────────────────────────────────────

    def _validate_hex_byte(self, value: str) -> bool:
        """Allow at most 2 hex characters (one byte 00–FF)."""
        if len(value) > 2:
            return False
        return all(c in "0123456789abcdefABCDEF" for c in value)

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
                    sig_data[sig.name] = float(entry["val_var"].get())
                except ValueError:
                    sig_data[sig.name] = 0.0

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

    # --------------------------------------------------------- device scan --

    def _scan_channels(self):
        iface = self.iface_var.get()

        if iface == "virtual":
            self.channel_cb["values"] = ["0"]
            self.channel_var.set("0")
            self.btn_connect.config(state=tk.NORMAL)
            self.bar_var.set("Virtual CAN — no hardware required, loopback enabled")
            return

        if iface == "slcan":
            try:
                import serial.tools.list_ports as slp
                ports = sorted(p.device for p in slp.comports())
            except ImportError:
                ports = []
            self.channel_cb["values"] = ports
            self.channel_var.set(ports[0] if ports else "COM3")
            self.btn_connect.config(state=tk.NORMAL)
            self.bar_var.set(
                "CANable/SLCAN — select or type serial port (e.g. COM3)")
            return

        try:
            with _silence_stderr():
                configs = can.detect_available_configs(interfaces=[iface])
            channels = [str(c["channel"]) for c in configs]
        except Exception:
            channels = []

        if channels:
            self.channel_cb["values"] = channels
            self.channel_var.set(channels[0])
            self.btn_connect.config(state=tk.NORMAL)
            self.bar_var.set(
                f"Found {len(channels)} {iface.upper()} device(s) — ready to connect")
        else:
            self.channel_cb["values"] = []
            self.channel_var.set("")
            self.btn_connect.config(state=tk.DISABLED)
            self.bar_var.set(
                f"No {iface.upper()} devices found — plug in dongle and click Rescan")

    def _on_iface_change(self, _=None):
        self._scan_channels()

    # ----------------------------------------------------------------- DBC --

    def _load_dbc(self):
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
        self.dbc_var.set(
            f"DBC: {os.path.basename(filename)}  ({len(self.db.messages)} msgs)")

        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()
        self._msg_iids.clear()

        # Refresh all DBC send rows with the new message list
        msg_names = sorted(m.name for m in self.db.messages)
        for rd in self._dbc_send_rows:
            rd["msg_cb"]["values"] = msg_names
            if msg_names:
                if not rd["msg_var"].get() or rd["msg_var"].get() not in msg_names:
                    rd["msg_var"].set(msg_names[0])
                self._on_dbc_msg_change(rd)

    def _decode_and_display(self, msg: can.Message, ts: str, rel: str = "0.000"):
        """Decode msg signals via DBC and update the symbolic live tree."""
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

        # Ensure message parent row exists
        if arb_id not in self._msg_iids:
            msg_iid = self.sym_tree.insert(
                "", tk.END, text=db_msg.name, open=True,
                values=("", "", ts, rel))
            self._msg_iids[arb_id] = msg_iid
        else:
            # Update last-seen timestamps on the message row
            self.sym_tree.item(self._msg_iids[arb_id], values=("", "", ts, rel))

        parent_iid = self._msg_iids[arb_id]

        for sig_name, value in signals.items():
            sig_def = db_msg.get_signal_by_name(sig_name)
            unit    = sig_def.unit or ""
            val_str = f"{value:.4g}" if isinstance(value, float) else str(value)
            key = (arb_id, sig_name)
            if key in self._signal_iids:
                self.sym_tree.item(self._signal_iids[key],
                                   values=(val_str, unit, ts, rel))
            else:
                iid = self.sym_tree.insert(
                    parent_iid, tk.END,
                    text=sig_name, values=(val_str, unit, ts, rel))
                self._signal_iids[key] = iid

    # --------------------------------------------------------------- logging --

    def _toggle_logging(self):
        if self.log_writer is None:
            self._start_logging()
        else:
            self._stop_logging()

    def _start_logging(self):
        filename = filedialog.asksaveasfilename(
            title="Save CAN Trace",
            filetypes=[("CSV files", "*.csv"), ("BLF files", "*.blf")],
            defaultextension=".csv",
        )
        if not filename:
            return
        try:
            if filename.lower().endswith(".blf"):
                self.log_writer = can.BLFWriter(filename)
                self.log_format = "blf"
            else:
                self.log_file = open(filename, "w", newline="")
                self.log_writer = csv.writer(self.log_file)
                self.log_writer.writerow(["Timestamp", "Arb ID", "Frame", "DLC", "Data"])
                self.log_format = "csv"
        except Exception as exc:
            messagebox.showerror("Log Error", str(exc))
            return
        self.btn_log.config(text="Stop Log")
        self.bar_var.set(f"Logging to: {filename}")

    def _stop_logging(self):
        try:
            if self.log_format == "blf" and self.log_writer:
                self.log_writer.stop()
            elif self.log_file:
                self.log_file.close()
        except Exception:
            pass
        self.log_writer = None
        self.log_file = None
        self.log_format = None
        self.btn_log.config(text="Start Log")
        self.bar_var.set("Log saved")

    # -------------------------------------------------------------- connect --

    def _connect(self):
        iface   = self.iface_var.get()
        channel = self.channel_var.get()
        bitrate = int(self.bitrate_var.get())

        if iface == "vector":
            try:
                channel = int(channel)
            except ValueError:
                messagebox.showerror("Config Error",
                                     "Vector channel must be an integer (e.g. 0 or 1).")
                return

        try:
            if iface == "virtual":
                self.bus = can.interface.Bus(
                    interface="virtual",
                    channel=channel,
                    receive_own_messages=True,
                )
            else:
                self.bus = can.interface.Bus(
                    interface=iface,
                    channel=channel,
                    bitrate=bitrate,
                )
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))
            self.bar_var.set(f"Error: {exc}")
            return

        self._trace_start = None
        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()

        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)
        self._set_send_buttons_state(tk.NORMAL)
        self.status_var.set("Connected")
        self.status_lbl.config(foreground="green")
        label = ("Virtual (loopback)" if iface == "virtual"
                 else f"{iface.upper()}  channel={channel}  bitrate={bitrate} bps")
        self.bar_var.set(f"Connected  |  {label}")

    def _disconnect(self):
        self._cancel_all_periodic()
        self.running = False
        if self.bus:
            try:
                with _silence_stderr():
                    self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

        # Drain stale reader-thread errors
        while not self.message_queue.empty():
            try:
                self.message_queue.get_nowait()
            except queue.Empty:
                break

        if self.log_writer is not None:
            self._stop_logging()

        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self._set_send_buttons_state(tk.DISABLED)
        self.status_var.set("Disconnected")
        self.status_lbl.config(foreground="red")
        self.bar_var.set("Disconnected")

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()
        self._msg_iids.clear()
        self.message_count = 0
        self.error_count = 0
        self.count_var.set("Messages: 0")
        self.error_var.set("Errors: 0")
        self._trace_start = None

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    # ------------------------------------------------------- background reader

    def _reader(self):
        while self.running and self.bus:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is not None:
                    self.message_queue.put(msg)
            except can.CanError as exc:
                self.message_queue.put(("error", str(exc)))
                break
            except Exception as exc:
                self.message_queue.put(("error", str(exc)))
                break

    # -------------------------------------------------- queue → GUI (tkinter)

    def _poll_queue(self):
        try:
            while True:
                item = self.message_queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "error":
                    messagebox.showerror("CAN Error", item[1])
                    self._disconnect()
                else:
                    self._show_message(item)
        except queue.Empty:
            pass
        self.root.after(10, self._poll_queue)

    def _show_message(self, msg: can.Message):
        now = time.time()
        if self._trace_start is None:
            self._trace_start = now
        rel = f"{now - self._trace_start:.3f}"
        ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if msg.is_error_frame:
            data = " ".join(f"{b:02X}" for b in msg.data) if msg.data else ""
            self.tree.insert("", tk.END,
                             values=(ts, rel, "---", "ERR", "---", data),
                             tags=("error",))
            self.tree.tag_configure("error", foreground="red")
            self.error_count += 1
            self.error_var.set(f"Errors: {self.error_count}")
        else:
            arb   = (f"0x{msg.arbitration_id:08X}" if msg.is_extended_id
                     else f"0x{msg.arbitration_id:03X}")
            frame = "EXT" if msg.is_extended_id else "STD"
            data  = " ".join(f"{b:02X}" for b in msg.data)
            self.tree.insert("", tk.END, values=(ts, rel, arb, frame, msg.dlc, data))
            self.message_count += 1
            self.count_var.set(f"Messages: {self.message_count}")
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

        if self.autoscroll_var.get():
            self.tree.yview_moveto(1.0)


# --------------------------------------------------------------------------- #

def main():
    root = tk.Tk()
    app = CANViewer(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
