"""
CAN Bus Viewer - Supports PEAK (PCAN) and Vector interfaces
Requires: pip install python-can cantools
"""
import contextlib
import csv
import os
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
        self.root.geometry("1400x700")
        self.root.minsize(900, 450)

        self.bus = None
        self.running = False
        self.message_queue = queue.Queue()
        self.message_count = 0
        self.error_count = 0

        self.log_writer = None
        self.log_file = None
        self.log_format = None

        self.db = None                # cantools database
        self._signal_iids: dict = {}  # (msg_id, signal_name) → treeview iid

        self._build_ui()
        self._scan_channels()
        self._poll_queue()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        # --- Connection bar ---
        conn = ttk.LabelFrame(self.root, text="Connection", padding=8)
        conn.pack(fill=tk.X, padx=10, pady=(8, 2))

        ttk.Label(conn, text="Interface:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.iface_var = tk.StringVar(value="pcan")
        iface_cb = ttk.Combobox(conn, textvariable=self.iface_var,
                                 values=["pcan", "vector"], width=8, state="readonly")
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

        # --- Toolbar ---
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

        # --- Side-by-side pane ---
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              sashrelief=tk.RAISED, sashwidth=5)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # Left: Raw CAN
        raw_frame = ttk.LabelFrame(pane, text="Raw CAN")
        pane.add(raw_frame, minsize=420)

        raw_cols = ("time", "id", "ext", "dlc", "data")
        self.tree = ttk.Treeview(raw_frame, columns=raw_cols, show="headings")
        self.tree.heading("time",  text="Timestamp")
        self.tree.heading("id",   text="Arb ID (hex)")
        self.tree.heading("ext",  text="Frame")
        self.tree.heading("dlc",  text="DLC")
        self.tree.heading("data", text="Data (hex)")
        self.tree.column("time",  width=115, anchor=tk.W)
        self.tree.column("id",   width=100, anchor=tk.CENTER)
        self.tree.column("ext",  width=55,  anchor=tk.CENTER)
        self.tree.column("dlc",  width=40,  anchor=tk.CENTER)
        self.tree.column("data", width=280, anchor=tk.W)

        raw_vsb = ttk.Scrollbar(raw_frame, orient=tk.VERTICAL,   command=self.tree.yview)
        raw_hsb = ttk.Scrollbar(raw_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=raw_vsb.set, xscrollcommand=raw_hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        raw_vsb.grid(row=0, column=1, sticky="ns")
        raw_hsb.grid(row=1, column=0, sticky="ew")
        raw_frame.rowconfigure(0, weight=1)
        raw_frame.columnconfigure(0, weight=1)

        # Right: Symbolic (DBC decoded) — live signal values, one row per signal
        sym_frame = ttk.LabelFrame(pane, text="Symbolic (DBC Decoded)")
        pane.add(sym_frame, minsize=320)

        sym_cols = ("msg", "signal", "value", "unit", "updated")
        self.sym_tree = ttk.Treeview(sym_frame, columns=sym_cols, show="headings")
        self.sym_tree.heading("msg",     text="Message")
        self.sym_tree.heading("signal",  text="Signal")
        self.sym_tree.heading("value",   text="Value")
        self.sym_tree.heading("unit",    text="Unit")
        self.sym_tree.heading("updated", text="Updated")
        self.sym_tree.column("msg",     width=120, anchor=tk.W)
        self.sym_tree.column("signal",  width=150, anchor=tk.W)
        self.sym_tree.column("value",   width=90,  anchor=tk.E)
        self.sym_tree.column("unit",    width=55,  anchor=tk.W)
        self.sym_tree.column("updated", width=110, anchor=tk.W)

        sym_vsb = ttk.Scrollbar(sym_frame, orient=tk.VERTICAL, command=self.sym_tree.yview)
        self.sym_tree.configure(yscrollcommand=sym_vsb.set)
        self.sym_tree.grid(row=0, column=0, sticky="nsew")
        sym_vsb.grid(row=0, column=1, sticky="ns")
        sym_frame.rowconfigure(0, weight=1)
        sym_frame.columnconfigure(0, weight=1)

        # --- Status bar ---
        self.bar_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.bar_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM, padx=10, pady=(0, 4))

    # --------------------------------------------------------- device scan --

    def _scan_channels(self):
        iface = self.iface_var.get()
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
        # Clear symbolic view — signals from the old DBC are stale
        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()

    def _decode_and_display(self, msg: can.Message, ts: str):
        """Decode msg signals via DBC and update the symbolic live view."""
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
        for sig_name, value in signals.items():
            sig_def = db_msg.get_signal_by_name(sig_name)
            unit = sig_def.unit or ""
            val_str = f"{value:.4g}" if isinstance(value, float) else str(value)
            key = (msg.arbitration_id, sig_name)
            if key in self._signal_iids:
                self.sym_tree.item(self._signal_iids[key],
                                   values=(db_msg.name, sig_name, val_str, unit, ts))
            else:
                iid = self.sym_tree.insert(
                    "", tk.END, values=(db_msg.name, sig_name, val_str, unit, ts))
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
            self.bus = can.interface.Bus(
                interface=iface,
                channel=channel,
                bitrate=bitrate,
            )
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))
            self.bar_var.set(f"Error: {exc}")
            return

        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()

        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)
        self.status_var.set("Connected")
        self.status_lbl.config(foreground="green")
        self.bar_var.set(
            f"Connected  |  {iface.upper()}  channel={channel}  bitrate={bitrate} bps")

    def _disconnect(self):
        self.running = False
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

        if self.log_writer is not None:
            self._stop_logging()

        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.status_var.set("Disconnected")
        self.status_lbl.config(foreground="red")
        self.bar_var.set("Disconnected")

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()
        self.message_count = 0
        self.error_count = 0
        self.count_var.set("Messages: 0")
        self.error_var.set("Errors: 0")

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    # ------------------------------------------------------- background reader

    def _reader(self):
        """Runs in a daemon thread; pushes received messages onto the queue."""
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
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if msg.is_error_frame:
            data = " ".join(f"{b:02X}" for b in msg.data) if msg.data else ""
            self.tree.insert("", tk.END,
                             values=(ts, "---", "ERR", "---", data),
                             tags=("error",))
            self.tree.tag_configure("error", foreground="red")
            self.error_count += 1
            self.error_var.set(f"Errors: {self.error_count}")
        else:
            arb   = (f"0x{msg.arbitration_id:08X}" if msg.is_extended_id
                     else f"0x{msg.arbitration_id:03X}")
            frame = "EXT" if msg.is_extended_id else "STD"
            data  = " ".join(f"{b:02X}" for b in msg.data)
            self.tree.insert("", tk.END, values=(ts, arb, frame, msg.dlc, data))
            self.message_count += 1
            self.count_var.set(f"Messages: {self.message_count}")
            self._decode_and_display(msg, ts)

        if self.log_writer is not None:
            try:
                if self.log_format == "blf":
                    self.log_writer(msg)
                else:
                    arb = ("---" if msg.is_error_frame
                           else (f"0x{msg.arbitration_id:08X}" if msg.is_extended_id
                                 else f"0x{msg.arbitration_id:03X}"))
                    frame = "ERR" if msg.is_error_frame else ("EXT" if msg.is_extended_id else "STD")
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
