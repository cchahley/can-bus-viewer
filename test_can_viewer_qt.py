"""Tests for Qt migration components using virtual CAN and synthetic DBC data."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import can
import cantools
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from can_viewer_qt.backend import QtCanBackend
from can_viewer_qt.logging_setup import initialize_logging
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

DBC_ENUM_TEXT = """
VERSION ""
NS_ :
BS_:
BU_: Vector__XXX
BO_ 300 DriveState: 8 Vector__XXX
 SG_ Mode : 0|8@1+ (1,0) [0|3] "" Vector__XXX
 SG_ Temp : 8|8@1+ (1,0) [0|255] "C" Vector__XXX
CM_ SG_ 300 Temp "Coolant temperature";
VAL_ 300 Mode 0 "Off" 1 "Init" 2 "Run" 3 "Fault" ;
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


def test_remove_selected_dbc_file_updates_registry(monkeypatch):
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()

    db = cantools.database.load_string(DBC_TEXT)
    path = Path("engine.dbc")
    win._dbc_files = [path]
    msg = db.messages[0]
    display = f"engine:{msg.name}"
    win._dbc_records_by_display = {display: {"display": display, "file": path, "msg": msg}}
    win._dbc_msg_by_id = {msg.frame_id: {"display": display, "file": path, "msg": msg}}
    win._on_dbc_registry_changed()
    assert win.about_dbc_files_list.count() == 1
    monkeypatch.setattr(win, "_prompt_dbc_removal_selection", lambda: ["engine.dbc"])
    win._remove_selected_dbc_files()
    assert win._dbc_records_by_display == {}
    assert win._dbc_msg_by_id == {}
    assert win.about_dbc_files_list.count() == 0
    win.close()


def test_remove_dbc_with_no_loaded_files_shows_info(monkeypatch):
    _qapp()
    win = CANViewerQtMainWindow()
    shown = {"called": False}

    def _info(*_args, **_kwargs):
        shown["called"] = True
        return 0

    monkeypatch.setattr("can_viewer_qt.main_window.QMessageBox.information", _info)
    win._remove_selected_dbc_files()
    assert shown["called"] is True
    win.close()


def test_trigger_signal_enum_and_units_and_default_formats():
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()

    db = cantools.database.load_string(DBC_ENUM_TEXT)
    msg = db.messages[0]
    display = f"drive:{msg.name}"
    win._dbc_records_by_display = {display: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._dbc_msg_by_id = {msg.frame_id: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._on_dbc_registry_changed()
    assert win.trigger_output_format.currentText() == "BLF"
    headers = [win.trigger_table.horizontalHeaderItem(i).text() for i in range(win.trigger_table.columnCount())]
    assert headers.index("Unit") == headers.index("Value") - 1

    row = win._trigger_rows[0]
    row["type"].setCurrentText("Signal")
    row["source"].setCurrentText(display)
    row["signal"].setCurrentText("Mode")
    assert row["unit"].text() == ""
    assert not row["value"].isEditable()
    labels = [row["value"].itemText(i) for i in range(row["value"].count())]
    assert set(labels) == {"Off", "Init", "Run", "Fault"}
    assert row["out_format"].currentText() == "BLF"

    row["signal"].setCurrentText("Temp")
    assert row["unit"].text() == "C"
    assert row["value"].isEditable()
    card = win._send_cards[0]
    card["msg_combo"].setCurrentText(display)
    win._on_dbc_send_card_change(card, display)
    assert card["meta"]["Temp"]["unit"] == "C"
    assert card["meta"]["Temp"]["description"] == "Coolant temperature"
    win.close()


def test_symbol_highlight_timer_is_two_seconds():
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()
    from PySide6.QtWidgets import QTreeWidgetItem  # local import for test scope

    node = QTreeWidgetItem(["Signal", "1", "", "", "", "", ""])
    win.sym_tree.addTopLevelItem(node)
    key = (0x100, "EngineSpeed")
    win._highlight_signal_item(key, node)
    timer = win._signal_highlight_timers[key]
    assert timer.remainingTime() >= 1500
    assert timer.remainingTime() <= 2100
    win.close()


def test_initialize_logging_creates_file():
    path = initialize_logging()
    assert path.exists()


def test_send_periodic_controls_present():
    _qapp()
    win = CANViewerQtMainWindow()
    assert win.send_raw_periodic.isEnabled() is False
    assert win.send_raw_period_ms.text() == "100"
    assert len(win._send_cards) >= 1
    card = win._send_cards[0]
    assert card["periodic_check"].isChecked() is False
    assert card["period_ms"].text() == "100"
    win.close()


def test_trigger_source_supports_signal_key_search():
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()

    db = cantools.database.load_string(DBC_ENUM_TEXT)
    msg = db.messages[0]
    display = f"drive:{msg.name}"
    win._dbc_records_by_display = {display: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._dbc_msg_by_id = {msg.frame_id: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._on_dbc_registry_changed()
    row = win._trigger_rows[0]
    row["type"].setCurrentText("Signal")
    row["source"].setCurrentText(f"{display}.Temp")
    assert row["source"].currentText() == display
    assert row["signal"].currentText() == "Temp"
    assert row["unit"].text() == "C"
    win.close()


def test_plot_signal_search_filters_results():
    _qapp()
    win = CANViewerQtMainWindow()
    win.poll_timer.stop()
    win.stats_timer.stop()
    win.render_timer.stop()
    win.decode_timer.stop()
    if hasattr(win, "plot_timer"):
        win.plot_timer.stop()
    db = cantools.database.load_string(DBC_ENUM_TEXT)
    msg = db.messages[0]
    display = f"drive:{msg.name}"
    win._dbc_records_by_display = {display: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._dbc_msg_by_id = {msg.frame_id: {"display": display, "file": "drive.dbc", "msg": msg}}
    win._on_dbc_registry_changed()
    assert win.plot_signal_list.count() >= 1
    win.plot_signal_search.setText("Temp")
    assert win.plot_signal_list.count() == 1
    assert "Temp" in win.plot_signal_list.item(0).text()
    win.close()


def test_matches_query_supports_wildcards_and_tokens():
    _qapp()
    win = CANViewerQtMainWindow()
    assert win._matches_query("drive:DriveState.Temp", "drive*temp")
    assert win._matches_query("drive:DriveState.Temp", "drive temp")
    assert not win._matches_query("drive:DriveState.Temp", "engine*temp")
    win.close()


def test_add_dbc_send_card_prompted_selects_requested_message(monkeypatch):
    _qapp()
    win = CANViewerQtMainWindow()
    db = cantools.database.load_string(DBC_ENUM_TEXT)
    msg = db.messages[0]
    path = Path("drive.dbc")
    display = f"drive:{msg.name}"
    win._dbc_files = [path]
    win._dbc_records_by_display = {display: {"display": display, "file": path, "msg": msg}}
    win._dbc_msg_by_id = {msg.frame_id: {"display": display, "file": path, "msg": msg}}
    win._on_dbc_registry_changed()

    responses = iter([["drive.dbc"], [display]])
    monkeypatch.setattr(win, "_prompt_select_from_list", lambda *args, **kwargs: next(responses))
    existing = len(win._send_cards)
    win._add_dbc_send_card_prompted()
    assert len(win._send_cards) == existing + 1
    assert win._send_cards[-1]["msg_combo"].currentText() == display
    win.close()
