"""
UI Builder mixin — constructs all static tkinter widgets.

Responsibilities
----------------
* ``_build_ui``         — top-level layout: connection panel, toolbar, filter bar,
                          raw-CAN tree, symbolic tree, send panel.
* ``_build_send_panel`` — raw-mode and DBC-mode scrollable send panels with canvas
                          windows; seeds both panels with initial rows.
* Canvas resize helpers — keep scrollregion and inner-frame width in sync.
* ``_validate_hex_byte``— tkinter validation callback for single-byte hex entry fields.
"""
import tkinter as tk
from tkinter import ttk


class UIBuilderMixin:
    """Mixin that builds the entire main-window widget tree."""

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        """Build every widget in the main window.

        Called once from ``CANViewer.__init__``.  All significant widget
        references are stored on ``self`` so that other methods can access
        them later (e.g. ``self.tree``, ``self.sym_tree``, ``self.btn_connect``).
        """
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

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        self._highlight_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Highlight changes",
                        variable=self._highlight_var).pack(side=tk.LEFT, padx=4)

        self.btn_dark = ttk.Button(toolbar, text="Dark Mode",
                                   command=self._toggle_dark_mode)
        self.btn_dark.pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Signal Plot",
                   command=self._open_plot_window).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Import Trace",
                   command=self._open_replay_window).pack(side=tk.LEFT, padx=4)

        self.error_var = tk.StringVar(value="Errors: 0")
        ttk.Label(toolbar, textvariable=self.error_var,
                  foreground="red").pack(side=tk.RIGHT, padx=10)

        self.count_var = tk.StringVar(value="Messages: 0")
        ttk.Label(toolbar, textvariable=self.count_var).pack(side=tk.RIGHT, padx=10)

        # ── Filter bar ────────────────────────────────────────────────────────
        filter_bar = ttk.Frame(self.root)
        filter_bar.pack(fill=tk.X, padx=10, pady=(0, 2))
        ttk.Label(filter_bar, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        # Entry uses self._filter_var, created after _build_send_panel to avoid
        # premature trace firing; packed here but variable assigned later.
        self._filter_entry = ttk.Entry(filter_bar, width=50)
        self._filter_entry.pack(side=tk.LEFT)
        ttk.Label(filter_bar,
                  text="  space/comma separated  •  matches ID, message name, or data",
                  foreground="gray").pack(side=tk.LEFT, padx=6)
        ttk.Button(filter_bar, text="✕", width=2,
                   command=self._clear_filter).pack(side=tk.LEFT, padx=2)

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
        self.tree.tag_configure("error", foreground="red")  # configured once here

        # Right: Symbolic — tree view, Message parent → Signal children
        sym_frame = ttk.LabelFrame(pane, text="Symbolic (DBC Decoded)")
        pane.add(sym_frame, minsize=320)

        sym_cols = ("value", "unit", "timestamp", "rel", "min_val", "max_val", "count")
        self.sym_tree = ttk.Treeview(sym_frame, columns=sym_cols, show="tree headings")
        self.sym_tree.heading("#0",        text="Message / Signal", anchor=tk.W)
        self.sym_tree.heading("value",     text="Value")
        self.sym_tree.heading("unit",      text="Unit")
        self.sym_tree.heading("timestamp", text="Timestamp")
        self.sym_tree.heading("rel",       text="Rel (s)")
        self.sym_tree.heading("min_val",   text="Min")
        self.sym_tree.heading("max_val",   text="Max")
        self.sym_tree.heading("count",     text="Count")
        self.sym_tree.column("#0",        width=170, anchor=tk.W)
        self.sym_tree.column("value",     width=80,  anchor=tk.E)
        self.sym_tree.column("unit",      width=45,  anchor=tk.W)
        self.sym_tree.column("timestamp", width=100, anchor=tk.W)
        self.sym_tree.column("rel",       width=65,  anchor=tk.E)
        self.sym_tree.column("min_val",   width=65,  anchor=tk.E)
        self.sym_tree.column("max_val",   width=65,  anchor=tk.E)
        self.sym_tree.column("count",     width=50,  anchor=tk.E)

        sym_vsb = ttk.Scrollbar(sym_frame, orient=tk.VERTICAL, command=self.sym_tree.yview)
        self.sym_tree.configure(yscrollcommand=sym_vsb.set)
        self.sym_tree.grid(row=0, column=0, sticky="nsew")
        sym_vsb.grid(row=0, column=1, sticky="ns")
        sym_frame.rowconfigure(0, weight=1)
        sym_frame.columnconfigure(0, weight=1)
        self.sym_tree.tag_configure("changed", background="#ffff99")

        self._build_send_panel()

        # Connect the filter entry to the filter var AFTER all widgets exist
        self._filter_entry.configure(textvariable=self._filter_var)
        self._filter_var.trace_add("write", lambda *_: self._on_filter_change())

    # ─────────────────────────────────────────────────── Send panel ──────────

    def _build_send_panel(self):
        """Build the Send CAN Message panel with raw-mode and DBC-mode sub-panels.

        Both sub-panels use a ``tk.Canvas`` + inner ``ttk.Frame`` pattern to make
        the row list scrollable.  The raw panel is shown by default; the DBC panel
        is hidden until the user switches the mode radio-button.
        """
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
