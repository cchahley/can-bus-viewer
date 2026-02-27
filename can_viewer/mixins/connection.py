"""
Connection mixin — device scanning, connect, disconnect, and state reset.

Responsibilities
----------------
* ``_scan_channels``   — probe the selected interface for available hardware;
                         handles PCAN, Vector, CANable/SLCAN, and virtual.
* ``_connect``         — open the CAN bus and start the background reader thread.
* ``_disconnect``      — stop the reader, drain the queue, close the bus, stop logging.
* ``_clear``           — reset all live data: trees, counters, buffers, stats.
* ``_on_close``        — clean shutdown when the window is closed.
"""
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import can

from ..utils import _silence_stderr


class ConnectionMixin:
    """Mixin that manages the CAN bus connection lifecycle."""

    # --------------------------------------------------------- device scan --

    def _scan_channels(self):
        """Probe the selected interface and populate the device combobox.

        Silently suppresses hardware-driver output during probing.
        For SLCAN/CANable, lists available serial ports instead of using
        the python-can detection API (which requires the device to be open).
        """
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

    # -------------------------------------------------------------- connect --

    def _connect(self):
        """Open the CAN bus and start receiving messages.

        Validates the channel input (Vector requires an integer), then opens
        a ``can.interface.Bus``.  On success, a daemon reader thread is started
        and the UI state is updated to reflect the connection.
        """
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
        """Stop reading, cancel all periodic sends, close the bus, and stop logging."""
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
        """Reset all live data: trees, counters, signal stats, and plot buffers."""
        self.tree.delete(*self.tree.get_children())
        self.sym_tree.delete(*self.sym_tree.get_children())
        self._signal_iids.clear()
        self._msg_iids.clear()
        self.message_count = 0
        self.error_count = 0
        self.count_var.set("Messages: 0")
        self.error_var.set("Errors: 0")
        self._trace_start = None
        self._signal_stats.clear()
        self._prev_sig_values.clear()
        self._plot_buffers.clear()
        self._raw_buffer.clear()
        self._raw_tree_count = 0
        self._filter_tokens = []
        for aid in self._highlight_after_ids.values():
            self.root.after_cancel(aid)
        self._highlight_after_ids.clear()

    def _on_close(self):
        """Disconnect cleanly and destroy the root window."""
        self._disconnect()
        self.root.destroy()
