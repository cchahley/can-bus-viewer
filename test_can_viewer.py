"""
Unit tests for CANViewer.
Run with:  python -m pytest test_can_viewer.py -v
"""
import csv
import io
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import can

import can_viewer
from can_viewer import CANViewer

# One Tk root for the whole test session — creating/destroying multiple Tk()
# instances in the same process is broken in Python 3.14 on Windows.
_ROOT: tk.Tk | None = None


def setUpModule():
    global _ROOT
    _ROOT = tk.Tk()
    _ROOT.withdraw()


def tearDownModule():
    global _ROOT
    if _ROOT:
        _ROOT.destroy()
        _ROOT = None


def _make_app():
    """Destroy any previous app widgets and create a fresh CANViewer on _ROOT."""
    for w in _ROOT.winfo_children():
        w.destroy()
    with patch("can.detect_available_configs", return_value=[]):
        app = CANViewer(_ROOT)
    return app


def _normal_msg(arb_id=0x100, data=None, extended=False):
    return can.Message(
        arbitration_id=arb_id,
        data=data or [0x01, 0x02],
        is_extended_id=extended,
        timestamp=0,
    )


def _error_msg():
    return can.Message(is_error_frame=True, data=[0x04], timestamp=0)


# ---------------------------------------------------------------------------
# Device scan
# ---------------------------------------------------------------------------

class TestScan(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        pass

    def test_no_devices_disables_connect(self):
        with patch("can.detect_available_configs", return_value=[]):
            self.app._scan_channels()
        self.assertEqual(str(self.app.btn_connect["state"]), "disabled")
        self.assertEqual(self.app.channel_var.get(), "")

    def test_devices_found_enables_connect(self):
        devs = [{"interface": "pcan", "channel": "PCAN_USBBUS1"},
                {"interface": "pcan", "channel": "PCAN_USBBUS2"}]
        with patch("can.detect_available_configs", return_value=devs):
            self.app._scan_channels()
        self.assertEqual(str(self.app.btn_connect["state"]), "normal")

    def test_first_device_selected(self):
        devs = [{"interface": "pcan", "channel": "PCAN_USBBUS1"},
                {"interface": "pcan", "channel": "PCAN_USBBUS2"}]
        with patch("can.detect_available_configs", return_value=devs):
            self.app._scan_channels()
        self.assertEqual(self.app.channel_var.get(), "PCAN_USBBUS1")

    def test_all_devices_in_dropdown(self):
        devs = [{"interface": "pcan", "channel": f"PCAN_USBBUS{i}"} for i in range(1, 4)]
        with patch("can.detect_available_configs", return_value=devs):
            self.app._scan_channels()
        values = self.app.channel_cb["values"]
        self.assertEqual(len(values), 3)

    def test_scan_exception_disables_connect(self):
        with patch("can.detect_available_configs", side_effect=Exception("driver error")):
            self.app._scan_channels()
        self.assertEqual(str(self.app.btn_connect["state"]), "disabled")


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestClear(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        pass

    def test_clear_resets_message_count(self):
        self.app.message_count = 10
        self.app._clear()
        self.assertEqual(self.app.message_count, 0)
        self.assertEqual(self.app.count_var.get(), "Messages: 0")

    def test_clear_resets_error_count(self):
        self.app.error_count = 5
        self.app._clear()
        self.assertEqual(self.app.error_count, 0)
        self.assertEqual(self.app.error_var.get(), "Errors: 0")

    def test_clear_removes_raw_rows(self):
        self.app.tree.insert("", tk.END, values=("ts", "0x100", "STD", 2, "AA BB"))
        self.app._clear()
        self.assertEqual(len(self.app.tree.get_children()), 0)

    def test_clear_removes_symbolic_rows(self):
        iid = self.app.sym_tree.insert("", tk.END, values=("M", "S", "1", "V", "ts"))
        self.app._signal_iids[(0x100, "S")] = iid
        self.app._clear()
        self.assertEqual(len(self.app.sym_tree.get_children()), 0)
        self.assertEqual(len(self.app._signal_iids), 0)


# ---------------------------------------------------------------------------
# _show_message — raw CAN display
# ---------------------------------------------------------------------------

class TestShowMessage(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        pass

    def test_normal_message_increments_message_count(self):
        self.app._show_message(_normal_msg())
        self.assertEqual(self.app.message_count, 1)
        self.assertEqual(self.app.error_count, 0)

    def test_normal_message_added_to_raw_tree(self):
        self.app._show_message(_normal_msg(arb_id=0x123, data=[0xAB, 0xCD]))
        children = self.app.tree.get_children()
        self.assertEqual(len(children), 1)
        vals = self.app.tree.item(children[0])["values"]
        self.assertEqual(vals[1], "0x123")
        self.assertEqual(vals[2], "STD")
        self.assertEqual(vals[3], 2)
        self.assertEqual(vals[4], "AB CD")

    def test_extended_id_format(self):
        self.app._show_message(_normal_msg(arb_id=0x1FFFFFFF, data=[], extended=True))
        vals = self.app.tree.item(self.app.tree.get_children()[0])["values"]
        self.assertEqual(vals[1], "0x1FFFFFFF")
        self.assertEqual(vals[2], "EXT")

    def test_standard_id_format(self):
        self.app._show_message(_normal_msg(arb_id=0x7FF, data=[], extended=False))
        vals = self.app.tree.item(self.app.tree.get_children()[0])["values"]
        self.assertEqual(vals[1], "0x7FF")

    def test_error_frame_increments_error_count(self):
        self.app._show_message(_error_msg())
        self.assertEqual(self.app.error_count, 1)
        self.assertEqual(self.app.message_count, 0)

    def test_error_frame_shows_ERR_in_raw_tree(self):
        self.app._show_message(_error_msg())
        vals = self.app.tree.item(self.app.tree.get_children()[0])["values"]
        self.assertEqual(vals[1], "---")
        self.assertEqual(vals[2], "ERR")

    def test_multiple_messages_accumulate(self):
        for i in range(5):
            self.app._show_message(_normal_msg(arb_id=i, data=[i]))
        self.assertEqual(self.app.message_count, 5)
        self.assertEqual(len(self.app.tree.get_children()), 5)

    def test_count_label_updates(self):
        self.app._show_message(_normal_msg())
        self.assertEqual(self.app.count_var.get(), "Messages: 1")

    def test_error_label_updates(self):
        self.app._show_message(_error_msg())
        self.assertEqual(self.app.error_var.get(), "Errors: 1")


# ---------------------------------------------------------------------------
# _decode_and_display — symbolic DBC view
# ---------------------------------------------------------------------------

def _make_mock_db(arb_id, msg_name, signals: dict):
    """Build a minimal cantools-style mock for a single message."""
    db = MagicMock()
    db_msg = MagicMock()
    db_msg.name = msg_name
    db_msg.decode.return_value = signals
    sig_defs = {}
    for name, val in signals.items():
        sig = MagicMock()
        sig.unit = "rpm" if "RPM" in name else ("°C" if "Temp" in name else "")
        sig_defs[name] = sig
    db_msg.get_signal_by_name.side_effect = lambda n: sig_defs[n]
    db.get_message_by_frame_id.return_value = db_msg
    return db, db_msg


class TestDecode(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        pass

    def test_no_dbc_skips_decode(self):
        self.app.db = None
        self.app._decode_and_display(_normal_msg(), "ts")
        self.assertEqual(len(self.app.sym_tree.get_children()), 0)

    def test_error_frame_skips_decode(self):
        self.app.db = MagicMock()
        self.app._decode_and_display(_error_msg(), "ts")
        self.app.db.get_message_by_frame_id.assert_not_called()

    def test_unknown_id_skips_decode(self):
        self.app.db = MagicMock()
        self.app.db.get_message_by_frame_id.side_effect = KeyError
        self.app._decode_and_display(_normal_msg(arb_id=0x999), "ts")
        self.assertEqual(len(self.app.sym_tree.get_children()), 0)

    def test_known_id_adds_signals(self):
        self.app.db, _ = _make_mock_db(0x100, "EngineData",
                                        {"RPM": 1500.0, "Temp": 85.0})
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts")
        self.assertEqual(len(self.app.sym_tree.get_children()), 2)

    def test_signal_values_in_tree(self):
        self.app.db, _ = _make_mock_db(0x100, "EngineData", {"RPM": 2000.0})
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts")
        children = self.app.sym_tree.get_children()
        vals = self.app.sym_tree.item(children[0])["values"]
        self.assertEqual(vals[0], "EngineData")   # Message name
        self.assertEqual(vals[1], "RPM")           # Signal name
        self.assertIn("2000", str(vals[2]))        # Value

    def test_signal_updated_in_place(self):
        """Same signal arriving twice should update the row, not add a new one."""
        self.app.db, db_msg = _make_mock_db(0x100, "EngineData", {"RPM": 1000.0})
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts1")
        # Update mock to return new value
        db_msg.decode.return_value = {"RPM": 3000.0}
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts2")

        children = self.app.sym_tree.get_children()
        self.assertEqual(len(children), 1)           # Still only one row
        vals = self.app.sym_tree.item(children[0])["values"]
        self.assertIn("3000", str(vals[2]))          # Value updated
        self.assertEqual(vals[4], "ts2")             # Timestamp updated

    def test_decode_exception_is_silent(self):
        """Malformed data should not crash the app."""
        db = MagicMock()
        db_msg = MagicMock()
        db_msg.decode.side_effect = Exception("bad data")
        db.get_message_by_frame_id.return_value = db_msg
        self.app.db = db
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts")
        self.assertEqual(len(self.app.sym_tree.get_children()), 0)

    def test_two_different_messages_both_displayed(self):
        db = MagicMock()
        def get_msg(arb_id):
            m = MagicMock()
            m.name = f"Msg_{arb_id:X}"
            m.decode.return_value = {"Signal": float(arb_id)}
            sig = MagicMock(); sig.unit = ""
            m.get_signal_by_name.return_value = sig
            return m
        db.get_message_by_frame_id.side_effect = get_msg
        self.app.db = db
        self.app._decode_and_display(_normal_msg(arb_id=0x100, data=[0]*8), "ts")
        self.app._decode_and_display(_normal_msg(arb_id=0x200, data=[0]*8), "ts")
        self.assertEqual(len(self.app.sym_tree.get_children()), 2)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        if self.app.log_writer is not None:
            self.app.log_format = "csv"
            self.app.log_file = io.StringIO()
            self.app._stop_logging()

    def _attach_csv_log(self):
        buf = io.StringIO()
        self.app.log_file = buf
        self.app.log_writer = csv.writer(buf)
        self.app.log_writer.writerow(["Timestamp", "Arb ID", "Frame", "DLC", "Data"])
        self.app.log_format = "csv"
        self.app.btn_log.config(text="Stop Log")
        return buf

    def test_csv_logs_normal_message(self):
        buf = self._attach_csv_log()
        self.app._show_message(_normal_msg(arb_id=0x123, data=[0xDE, 0xAD]))
        content = buf.getvalue()
        self.assertIn("0x123", content)
        self.assertIn("DE AD", content)
        self.assertIn("STD", content)

    def test_csv_logs_error_frame(self):
        buf = self._attach_csv_log()
        self.app._show_message(_error_msg())
        content = buf.getvalue()
        self.assertIn("ERR", content)
        self.assertIn("---", content)

    def test_csv_has_header(self):
        buf = self._attach_csv_log()
        self.assertIn("Timestamp", buf.getvalue())

    def test_stop_logging_resets_state(self):
        self.app.log_format = "csv"
        self.app.log_file = io.StringIO()
        self.app.log_writer = csv.writer(self.app.log_file)
        self.app._stop_logging()
        self.assertIsNone(self.app.log_writer)
        self.assertIsNone(self.app.log_file)
        self.assertIsNone(self.app.log_format)
        self.assertEqual(self.app.btn_log["text"], "Start Log")

    def test_no_log_when_writer_is_none(self):
        """Messages should display normally even without logging active."""
        self.assertIsNone(self.app.log_writer)
        self.app._show_message(_normal_msg())   # Must not raise
        self.assertEqual(self.app.message_count, 1)


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

class TestDisconnect(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        pass

    def test_disconnect_shuts_down_bus(self):
        mock_bus = MagicMock()
        self.app.bus = mock_bus
        self.app.running = True
        self.app.btn_connect.config(state=tk.DISABLED)
        self.app.btn_disconnect.config(state=tk.NORMAL)
        self.app._disconnect()
        mock_bus.shutdown.assert_called_once()
        self.assertIsNone(self.app.bus)
        self.assertFalse(self.app.running)

    def test_disconnect_stops_active_logging(self):
        self.app.log_format = "csv"
        self.app.log_file = io.StringIO()
        self.app.log_writer = csv.writer(self.app.log_file)
        self.app._disconnect()
        self.assertIsNone(self.app.log_writer)

    def test_disconnect_drains_queue(self):
        self.app.message_queue.put(("error", "stale error"))
        self.app.message_queue.put(("error", "another stale error"))
        self.app._disconnect()
        self.assertTrue(self.app.message_queue.empty())

    def test_disconnect_when_bus_is_none(self):
        """Should not raise when already disconnected."""
        self.app.bus = None
        self.app.running = False
        self.app._disconnect()   # Must not raise

    def test_disconnect_bus_shutdown_exception_is_silent(self):
        """A failing shutdown should not crash the app."""
        mock_bus = MagicMock()
        mock_bus.shutdown.side_effect = Exception("hardware gone")
        self.app.bus = mock_bus
        self.app._disconnect()   # Must not raise
        self.assertIsNone(self.app.bus)

    def test_disconnect_updates_status(self):
        self.app._disconnect()
        self.assertEqual(self.app.status_var.get(), "Disconnected")


if __name__ == "__main__":
    unittest.main()
