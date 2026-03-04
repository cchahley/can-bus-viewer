"""Tests for Qt migration components using virtual CAN and synthetic DBC data."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import can
import cantools
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from can_viewer_qt.backend import QtCanBackend
from can_viewer_qt.main_window import CANViewerQtMainWindow
from can_viewer_qt.raw_model import RawTableModel


DBC_TEXT = """
VERSION ""
NS_ :
BS_:
BU_: Vector__XXX
BO_ 256 EngineData: 8 Vector__XXX
 SG_ EngineSpeed : 0|16@1+ (1,0) [0|8000] "rpm" Vector__XXX
"""


def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_backend_virtual_loopback_receive():
    backend = QtCanBackend()
    ok, _ = backend.connect("virtual", "0", 500000)
    assert ok

    msg = can.Message(arbitration_id=0x123, data=b"\x11\x22", is_extended_id=False)
    sent, _ = backend.send_message(msg)
    assert sent

    deadline = time.time() + 1.0
    received = None
    while time.time() < deadline:
        try:
            item = backend.message_queue.get_nowait()
        except Exception:
            time.sleep(0.01)
            continue
        if isinstance(item, can.Message):
            received = item
            break

    backend.disconnect()
    assert received is not None
    assert received.arbitration_id == 0x123
    assert bytes(received.data) == b"\x11\x22"


def test_raw_model_max_rows_and_error_color():
    model = RawTableModel(max_rows=3)
    model.append_rows(
        [
            (["t1", "0.1", "0x1", "STD", "1", "01"], False),
            (["t2", "0.2", "0x2", "STD", "1", "02"], False),
            (["t3", "0.3", "0x3", "STD", "1", "03"], True),
            (["t4", "0.4", "0x4", "STD", "1", "04"], False),
        ]
    )
    assert model.rowCount() == 3
    # Oldest row should be dropped due to ring-buffer maxlen.
    assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "0x2"
    assert model.data(model.index(1, 2), Qt.ItemDataRole.DisplayRole) == "0x3"
    assert model.data(model.index(2, 2), Qt.ItemDataRole.DisplayRole) == "0x4"
    assert model.data(model.index(1, 0), Qt.ItemDataRole.ForegroundRole) is not None


def test_raw_model_incremental_append():
    model = RawTableModel(max_rows=10)
    model.append_rows([(["t1", "0.1", "0x1", "STD", "1", "01"], False)])
    model.append_rows([(["t2", "0.2", "0x2", "STD", "1", "02"], False)])
    assert model.rowCount() == 2
    assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "0x1"
    assert model.data(model.index(1, 2), Qt.ItemDataRole.DisplayRole) == "0x2"


def test_window_dbc_decode_path_updates_symbolic_tree():
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()

    db = cantools.database.load_string(DBC_TEXT)
    win.db = db
    win._dbc_msg_by_id = {msg.frame_id: msg for msg in db.messages}
    win._dbc_signal_units = {
        msg.frame_id: {sig.name: (sig.unit or "") for sig in msg.signals}
        for msg in db.messages
    }

    msg = can.Message(
        arbitration_id=0x100,
        data=bytes([0xE8, 0x03, 0, 0, 0, 0, 0, 0]),  # EngineSpeed=1000
        is_extended_id=False,
    )
    win._show_message(msg, render=False, decode=True)
    win._flush_decode_updates()

    assert 0x100 in win._msg_items
    assert (0x100, "EngineSpeed") in win._signal_items
    sig_item = win._signal_items[(0x100, "EngineSpeed")]
    assert sig_item.text(1) in {"1000", "1e+03"}
    assert sig_item.text(2) == "rpm"
    win.close()
