"""
CAN Bus Viewer - Supports PEAK (PCAN) and Vector interfaces
Requires: pip install python-can
"""
import contextlib
import os
import tkinter as tk
from tkinter import ttk, messagebox
import can
import threading
import queue
from datetime import datetime


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
        self.root.geometry("950x620")
        self.root.minsize(700, 400)

        self.bus = None
        self.running = False
        self.message_queue = queue.Queue()
        self.message_count = 0
        self.error_count = 0

        self._build_ui()
        self._scan_channels()
        self._poll_queue()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        # --- Connection bar ---
        conn = ttk.LabelFrame(self.root, text="Connection", padding=8)
        conn.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(conn, text="Interface:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.iface_var = tk.StringVar(value="pcan")
        iface_cb = ttk.Combobox(conn, textvariable=self.iface_var,
                                 values=["pcan", "vector"], width=8, state="readonly")
        iface_cb.grid(row=0, column=1, padx=4)
        iface_cb.bind("<<ComboboxSelected>>", self._on_iface_change)

        ttk.Label(conn, text="Channel:").grid(row=0, column=2, sticky=tk.W, padx=4)
        self.channel_var = tk.StringVar(value="PCAN_USBBUS1")
        self.channel_cb = ttk.Combobox(conn, textvariable=self.channel_var, width=16)
        self.channel_cb.grid(row=0, column=3, padx=4)

        ttk.Button(conn, text="Scan", command=self._scan_channels).grid(row=0, column=4, padx=(0, 8))

        ttk.Label(conn, text="Bitrate:").grid(row=0, column=5, sticky=tk.W, padx=4)
        self.bitrate_var = tk.StringVar(value="500000")
        ttk.Combobox(conn, textvariable=self.bitrate_var, width=10,
                     values=["125000", "250000", "500000", "1000000"]).grid(row=0, column=6, padx=4)

        self.btn_connect = ttk.Button(conn, text="Connect", command=self._connect)
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

        self.error_var = tk.StringVar(value="Errors: 0")
        ttk.Label(toolbar, textvariable=self.error_var, foreground="red").pack(side=tk.RIGHT, padx=10)

        self.count_var = tk.StringVar(value="Messages: 0")
        ttk.Label(toolbar, textvariable=self.count_var).pack(side=tk.RIGHT, padx=10)

        # --- Message table ---
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        cols = ("time", "id", "ext", "dlc", "data")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")

        self.tree.heading("time",  text="Timestamp")
        self.tree.heading("id",   text="Arb ID (hex)")
        self.tree.heading("ext",  text="Frame")
        self.tree.heading("dlc",  text="DLC")
        self.tree.heading("data", text="Data (hex)")

        self.tree.column("time",  width=130, anchor=tk.W)
        self.tree.column("id",   width=110, anchor=tk.CENTER)
        self.tree.column("ext",  width=70,  anchor=tk.CENTER)
        self.tree.column("dlc",  width=45,  anchor=tk.CENTER)
        self.tree.column("data", width=500, anchor=tk.W)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # --- Status bar ---
        self.bar_var = tk.StringVar(value="Ready  —  install python-can:  pip install python-can")
        ttk.Label(self.root, textvariable=self.bar_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=(0, 4))

    # --------------------------------------------------------- event handlers

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
            self.bar_var.set(f"Found {len(channels)} device(s) on {iface.upper()}")
        else:
            self.channel_cb["values"] = []
            default = "PCAN_USBBUS1" if iface == "pcan" else "0"
            self.channel_var.set(default)
            self.bar_var.set(f"No {iface.upper()} devices detected — enter channel manually")

    def _on_iface_change(self, _=None):
        self._scan_channels()

    def _connect(self):
        iface   = self.iface_var.get()
        channel = self.channel_var.get()
        bitrate = int(self.bitrate_var.get())

        # Vector channel must be an integer
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
        self.bar_var.set(f"Connected  |  {iface.upper()}  channel={channel}  bitrate={bitrate} bps")

    def _disconnect(self):
        self.running = False
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.status_var.set("Disconnected")
        self.status_lbl.config(foreground="red")
        self.bar_var.set("Disconnected")

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.message_count = 0
        self.error_count = 0
        self.count_var.set("Messages: 0")
        self.error_var.set("Errors: 0")

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    # ------------------------------------------------------- background reader

    def _reader(self):
        """Runs in a daemon thread; pushes messages onto the queue."""
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
