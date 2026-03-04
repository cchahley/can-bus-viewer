"""CAN bus backend for the PySide6 preview app."""

from __future__ import annotations

import queue
import threading
import time
import logging
from dataclasses import dataclass

import can

from can_viewer.utils import _silence_stderr

try:
    import serial.tools.list_ports as serial_list_ports
except ImportError:  # pragma: no cover - optional dependency
    serial_list_ports = None


@dataclass(slots=True)
class ScanResult:
    """Result returned by interface channel scan."""

    channels: list[str]
    default_channel: str
    can_connect: bool
    status: str


class QtCanBackend:
    """Owns CAN connection lifecycle and background message reader."""

    def __init__(self) -> None:
        self.bus: can.BusABC | None = None
        self.running = False
        self.message_queue: queue.Queue = queue.Queue(maxsize=10_000)
        self.dropped_count = 0
        self._reader_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        """Return True when a bus session is active."""
        return self.running and self.bus is not None

    def scan_channels(self, iface: str) -> ScanResult:
        """Probe channels for a selected interface."""
        if iface == "virtual":
            return ScanResult(
                channels=["0"],
                default_channel="0",
                can_connect=True,
                status="Virtual CAN - no hardware required, loopback enabled",
            )

        if iface == "slcan":
            ports: list[str] = []
            if serial_list_ports is not None:
                ports = sorted(p.device for p in serial_list_ports.comports())
            default_port = ports[0] if ports else "COM3"
            return ScanResult(
                channels=ports,
                default_channel=default_port,
                can_connect=True,
                status="CANable/SLCAN - select or type serial port (for example COM3)",
            )

        try:
            with _silence_stderr():
                configs = can.detect_available_configs(interfaces=[iface])
            channels = [str(c["channel"]) for c in configs]
        except Exception:
            channels = []

        if channels:
            return ScanResult(
                channels=channels,
                default_channel=channels[0],
                can_connect=True,
                status=f"Found {len(channels)} {iface.upper()} device(s) - ready to connect",
            )

        return ScanResult(
            channels=[],
            default_channel="",
            can_connect=False,
            status=f"No {iface.upper()} devices found - plug in dongle and click Rescan",
        )

    def connect(self, iface: str, channel: str, bitrate: int) -> tuple[bool, str]:
        """Open CAN bus and start background reader."""
        if self.running:
            return True, "Already connected"

        # Suppress optional uptime warning emitted by can.pcan on some systems.
        logging.getLogger("can.pcan").setLevel(logging.ERROR)

        if iface == "vector":
            try:
                channel = str(int(channel))
            except ValueError:
                return False, "Vector channel must be an integer (for example 0 or 1)."

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
            self.bus = None
            return False, str(exc)

        self.running = True
        self.dropped_count = 0
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        label = (
            "Virtual (loopback)"
            if iface == "virtual"
            else f"{iface.upper()} channel={channel} bitrate={bitrate} bps"
        )
        return True, f"Connected | {label}"

    def disconnect(self) -> None:
        """Stop reader thread and close bus."""
        self.running = False
        bus = self.bus
        self.bus = None
        # Drop queued frames in O(1) instead of draining item-by-item on UI thread.
        self.message_queue = queue.Queue(maxsize=10_000)
        if bus is not None:
            threading.Thread(target=self._shutdown_bus, args=(bus,), daemon=True).start()

    def send_message(self, msg: can.Message) -> tuple[bool, str]:
        """Send one CAN frame on the active bus."""
        if not self.is_connected:
            return False, "Not connected to CAN bus."
        assert self.bus is not None
        try:
            self.bus.send(msg)
        except Exception as exc:
            return False, str(exc)
        return True, "Sent"

    def _reader_loop(self) -> None:
        """Read messages on background thread and enqueue for GUI thread."""
        consecutive_errors = 0
        while self.running and self.bus is not None:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is not None:
                    consecutive_errors = 0
                    try:
                        self.message_queue.put_nowait(msg)
                    except queue.Full:
                        self.dropped_count += 1
            except can.CanError as exc:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    try:
                        self.message_queue.put_nowait(("error", str(exc)))
                    except queue.Full:
                        pass
                    break
                time.sleep(0.05)
            except Exception as exc:  # pragma: no cover - hardware dependent
                try:
                    self.message_queue.put_nowait(("error", str(exc)))
                except queue.Full:
                    pass
                break

    @staticmethod
    def _shutdown_bus(bus: can.BusABC) -> None:
        """Shutdown bus in background to avoid blocking the UI thread."""
        try:
            with _silence_stderr():
                bus.shutdown()
        except Exception:
            pass
