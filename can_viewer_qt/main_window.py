"""Main window for the PySide6 migration preview."""

from __future__ import annotations

import csv
import collections
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import can
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    import cantools
except ImportError:  # pragma: no cover
    cantools = None

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    _MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MATPLOTLIB_AVAILABLE = False

from .backend import QtCanBackend
from .raw_model import RawTableModel


class CANViewerQtMainWindow(QMainWindow):
    _MAX_RAW_ROWS = 8000
    _MAX_PER_CYCLE = 60

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CAN Bus Viewer (Qt Preview)")
        self.resize(1420, 940)
        self.setMinimumSize(1080, 700)

        self.backend = QtCanBackend()
        self.message_count = 0
        self.error_count = 0
        self._trace_start: float | None = None

        self.db = None
        self._dbc_msg_by_id: dict[int, object] = {}
        self._msg_items: dict[int, QTreeWidgetItem] = {}
        self._signal_items: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._signal_stats: dict[tuple[int, str], dict[str, float | int | None]] = {}
        self._prev_sig_values: dict[tuple[int, str], str] = {}
        self._dbc_signal_controls: dict[str, QWidget] = {}
        self._dbc_signal_meta: dict[str, dict] = {}

        self.log_writer = None
        self.log_file = None
        self.log_format: str | None = None

        self._replay_messages: list[can.Message] = []
        self._plot_buffers: dict[str, collections.deque[float]] = {}
        self._plot_active_signals: list[str] = []
        self._last_stride_notice_ts = 0.0
        self._last_stride_notice_value = 1
        self._dbc_signal_units: dict[int, dict[str, str]] = {}
        self._pending_raw_rows: collections.deque[tuple[list[str], bool]] = collections.deque()
        self._pending_decode: dict[int, tuple[can.Message, str, str]] = {}
        self._raw_needs_scroll = False
        self._raw_rollover_notified = False
        self._raw_model = RawTableModel(max_rows=self._MAX_RAW_ROWS)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(self._build_connection_panel())
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_tabs(), 1)

        self.status = QStatusBar(self)
        self.status.showMessage("Qt preview loaded. Use Rescan, then Connect.")
        self.setStatusBar(self.status)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_queue)
        self.poll_timer.start(10)

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._flush_render_updates)
        self.render_timer.start(33)

        self.decode_timer = QTimer(self)
        self.decode_timer.timeout.connect(self._flush_decode_updates)
        self.decode_timer.start(80)

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._refresh_stats)
        self.stats_timer.start(200)

        if _MATPLOTLIB_AVAILABLE:
            self.plot_timer = QTimer(self)
            self.plot_timer.timeout.connect(self._refresh_plot)
            self.plot_timer.start(250)

        self._scan_channels()
        # Suppress noisy timestamp warning when optional `uptime` package is absent.
        logging.getLogger("can.pcan").setLevel(logging.ERROR)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._disconnect()
        self._stop_logging()
        super().closeEvent(event)

    def _build_connection_panel(self) -> QWidget:
        card = QGroupBox("Connection")
        grid = QGridLayout(card)

        grid.addWidget(QLabel("Interface:"), 0, 0)
        self.iface_combo = QComboBox()
        self.iface_combo.addItems(["pcan", "vector", "slcan", "virtual"])
        self.iface_combo.currentTextChanged.connect(self._scan_channels)
        grid.addWidget(self.iface_combo, 0, 1)

        grid.addWidget(QLabel("Channel:"), 0, 2)
        self.channel_combo = QComboBox()
        self.channel_combo.setEditable(True)
        self.channel_combo.setMinimumWidth(170)
        grid.addWidget(self.channel_combo, 0, 3)

        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self._scan_channels)
        grid.addWidget(self.rescan_btn, 0, 4)

        grid.addWidget(QLabel("Bitrate:"), 0, 5)
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.setEditable(True)
        self.bitrate_combo.addItems(["125000", "250000", "500000", "1000000"])
        self.bitrate_combo.setCurrentText("500000")
        self.bitrate_combo.setMinimumContentsLength(8)
        self.bitrate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.bitrate_combo.setMinimumWidth(120)
        grid.addWidget(self.bitrate_combo, 0, 6)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect)
        grid.addWidget(self.connect_btn, 0, 7)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self._disconnect)
        grid.addWidget(self.disconnect_btn, 0, 8)

        self.connection_state_label = QLabel("Disconnected")
        self.connection_state_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #fbe9e7; color: #8e2c1e;"
        )
        grid.addWidget(self.connection_state_label, 0, 9)
        grid.setColumnStretch(10, 1)
        return card

    def _build_toolbar(self) -> QWidget:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_all_views)
        layout.addWidget(clear_btn)

        self.autoscroll_checkbox = QCheckBox("Auto-scroll")
        self.autoscroll_checkbox.setChecked(True)
        layout.addWidget(self.autoscroll_checkbox)

        self.load_dbc_btn = QPushButton("Load DBC")
        self.load_dbc_btn.clicked.connect(self._load_dbc)
        layout.addWidget(self.load_dbc_btn)

        self.log_btn = QPushButton("Start Log")
        self.log_btn.clicked.connect(self._toggle_logging)
        layout.addWidget(self.log_btn)

        self.dbc_label = QLabel("No DBC loaded")
        self.dbc_label.setStyleSheet("color: #586a7c;")
        layout.addWidget(self.dbc_label)

        layout.addStretch(1)
        self.msg_count_label = QLabel("Messages: 0")
        self.err_count_label = QLabel("Errors: 0")
        self.drop_count_label = QLabel("")
        self.err_count_label.setStyleSheet("color: #8f1d21;")
        self.drop_count_label.setStyleSheet("color: #9a6700;")
        layout.addWidget(self.drop_count_label)
        layout.addWidget(self.err_count_label)
        layout.addWidget(self.msg_count_label)
        return row

    def _build_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()
        self.monitor_tab = self._build_monitor_tab()
        self.plot_tab = self._build_plot_tab()
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self._build_send_tab(), "Send")
        self.tabs.addTab(self._build_replay_tab(), "Replay")
        self.tabs.addTab(self.plot_tab, "Plot")
        self.tabs.addTab(self._build_diag_tab(), "Diag")
        return self.tabs

    def _build_monitor_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(10)

        raw_group = QGroupBox("Raw CAN")
        raw_layout = QVBoxLayout(raw_group)
        self.raw_table = QTableView()
        self.raw_table.setModel(self._raw_model)
        self.raw_table.verticalHeader().setVisible(False)
        self.raw_table.setAlternatingRowColors(True)
        self.raw_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.raw_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.raw_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.raw_table.setSortingEnabled(False)
        hdr = self.raw_table.horizontalHeader()
        hdr.setStretchLastSection(True)
        for i in range(6):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.raw_table.setColumnWidth(0, 118)
        self.raw_table.setColumnWidth(1, 76)
        self.raw_table.setColumnWidth(2, 110)
        self.raw_table.setColumnWidth(3, 58)
        self.raw_table.setColumnWidth(4, 48)
        raw_layout.addWidget(self.raw_table, 1)

        sym_group = QGroupBox("Symbolic (DBC Decoded)")
        sym_layout = QVBoxLayout(sym_group)
        self.sym_tree = QTreeWidget()
        self.sym_tree.setColumnCount(7)
        self.sym_tree.setHeaderLabels(
            ["Message / Signal", "Value", "Unit", "Timestamp", "Rel (s)", "Min", "Max"]
        )
        self.sym_tree.header().setStretchLastSection(False)
        self.sym_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        for i in range(1, 7):
            self.sym_tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.sym_tree.setColumnWidth(0, 260)
        self.sym_tree.setColumnWidth(1, 120)
        self.sym_tree.setColumnWidth(2, 80)
        self.sym_tree.setColumnWidth(3, 120)
        self.sym_tree.setColumnWidth(4, 80)
        self.sym_tree.setColumnWidth(5, 90)
        self.sym_tree.setColumnWidth(6, 90)
        sym_layout.addWidget(self.sym_tree, 1)

        split.addWidget(raw_group)
        split.addWidget(sym_group)
        split.setSizes([820, 580])
        layout.addWidget(split, 1)
        return tab

    def _build_send_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        raw_group = QGroupBox("Raw Send")
        raw_form = QFormLayout(raw_group)
        self.send_raw_id = QLineEdit("100")
        self.send_raw_data = QLineEdit("")
        self.send_raw_ext = QCheckBox("Extended ID")
        self.send_raw_btn = QPushButton("Send Raw")
        self.send_raw_btn.setEnabled(False)
        self.send_raw_btn.clicked.connect(self._send_raw_message)
        raw_form.addRow("Arb ID (hex):", self.send_raw_id)
        raw_form.addRow("Data bytes (hex):", self.send_raw_data)
        raw_form.addRow("", self.send_raw_ext)
        raw_form.addRow("", self.send_raw_btn)

        dbc_group = QGroupBox("DBC Send")
        dbc_layout = QVBoxLayout(dbc_group)
        top = QHBoxLayout()
        self.dbc_send_msg_combo = QComboBox()
        self.dbc_send_msg_combo.currentTextChanged.connect(self._on_dbc_send_msg_change)
        self.dbc_send_btn = QPushButton("Send DBC")
        self.dbc_send_btn.setEnabled(False)
        self.dbc_send_btn.clicked.connect(self._send_dbc_message)
        top.addWidget(QLabel("Message:"))
        top.addWidget(self.dbc_send_msg_combo, 1)
        top.addWidget(self.dbc_send_btn)
        self.dbc_send_form_widget = QWidget()
        self.dbc_send_form = QFormLayout(self.dbc_send_form_widget)
        dbc_layout.addLayout(top)
        dbc_layout.addWidget(self.dbc_send_form_widget)

        layout.addWidget(raw_group)
        layout.addWidget(dbc_group, 1)
        return tab

    def _build_replay_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.replay_open_btn = QPushButton("Open File")
        self.replay_open_btn.clicked.connect(self._replay_open_file)
        top.addWidget(self.replay_open_btn)
        top.addWidget(QLabel("Speed:"))
        self.replay_speed = QLineEdit("1.0")
        self.replay_speed.setMaximumWidth(70)
        top.addWidget(self.replay_speed)
        top.addWidget(QLabel("x"))
        self.replay_start_btn = QPushButton("Replay")
        self.replay_start_btn.setEnabled(False)
        self.replay_start_btn.clicked.connect(self._replay_start)
        top.addWidget(self.replay_start_btn)
        self.replay_info = QLabel("No file loaded")
        self.replay_info.setStyleSheet("color: #586a7c;")
        top.addWidget(self.replay_info, 1)
        layout.addLayout(top)

        self.replay_table = QTableWidget(0, 5)
        self.replay_table.setHorizontalHeaderLabels(
            ["Timestamp (s)", "Arb ID", "Frame", "DLC", "Data (hex)"]
        )
        self.replay_table.verticalHeader().setVisible(False)
        self.replay_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.replay_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.replay_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.replay_table, 1)
        return tab

    def _build_plot_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        if not _MATPLOTLIB_AVAILABLE:
            note = QLabel("matplotlib is not installed. Run: py -m pip install matplotlib")
            layout.addWidget(note)
            return tab

        left = QVBoxLayout()
        left.addWidget(QLabel("Signals"))
        self.plot_signal_list = QListWidget()
        self.plot_signal_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        left.addWidget(self.plot_signal_list, 1)
        self.plot_apply_btn = QPushButton("Plot Selected")
        self.plot_apply_btn.clicked.connect(self._apply_plot_selection)
        left.addWidget(self.plot_apply_btn)
        self.plot_clear_btn = QPushButton("Clear Plot")
        self.plot_clear_btn.clicked.connect(self._clear_plot)
        left.addWidget(self.plot_clear_btn)

        right = QVBoxLayout()
        self.plot_figure = Figure(figsize=(7, 4.6), tight_layout=True)
        self.plot_ax = self.plot_figure.add_subplot(111)
        self.plot_ax.set_xlabel("Sample index")
        self.plot_ax.set_ylabel("Value")
        self.plot_ax.grid(True)
        self.plot_canvas = FigureCanvasQTAgg(self.plot_figure)
        right.addWidget(self.plot_canvas, 1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 3)
        return tab

    def _placeholder_tab(self, text: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        note = QTextEdit()
        note.setReadOnly(True)
        note.setPlainText(text)
        layout.addWidget(note)
        return tab

    def _build_diag_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.diag_queue_label = QLabel("Queue: 0")
        self.diag_mode_label = QLabel("Render mode: full")
        top.addWidget(self.diag_queue_label)
        top.addWidget(self.diag_mode_label)
        top.addStretch(1)
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(lambda: self.diag_text.clear())
        top.addWidget(clear_btn)
        layout.addLayout(top)

        self.diag_text = QTextEdit()
        self.diag_text.setReadOnly(True)
        layout.addWidget(self.diag_text, 1)
        return tab

    def _scan_channels(self) -> None:
        iface = self.iface_combo.currentText().strip()
        result = self.backend.scan_channels(iface)
        self.channel_combo.clear()
        if result.channels:
            self.channel_combo.addItems(result.channels)
        self.channel_combo.setCurrentText(result.default_channel)
        self.connect_btn.setEnabled(result.can_connect and not self.backend.running)
        self.status.showMessage(result.status)

    def _connect(self) -> None:
        iface = self.iface_combo.currentText().strip()
        channel = self.channel_combo.currentText().strip()
        try:
            bitrate = int(self.bitrate_combo.currentText().strip())
        except ValueError:
            QMessageBox.critical(self, "Config Error", "Bitrate must be an integer.")
            return

        self.connect_btn.setEnabled(False)
        self.status.showMessage("Connecting...")
        ok, message = self.backend.connect(iface=iface, channel=channel, bitrate=bitrate)
        if not ok:
            QMessageBox.critical(self, "Connection Error", message)
            self.status.showMessage(f"Error: {message}")
            self.connect_btn.setEnabled(True)
            return

        self._trace_start = None
        self.disconnect_btn.setEnabled(True)
        self.send_raw_btn.setEnabled(True)
        self.dbc_send_btn.setEnabled(self.db is not None)
        self.replay_start_btn.setEnabled(bool(self._replay_messages))
        self.connection_state_label.setText("Connected")
        self.connection_state_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #e6f4ea; color: #1d6f42;"
        )
        self.status.showMessage(message)
        self._diag_log(f"Connect: {message}")

    def _disconnect(self) -> None:
        self.disconnect_btn.setEnabled(False)
        self.status.showMessage("Disconnecting...")
        self.backend.disconnect()
        self.connect_btn.setEnabled(True)
        self.send_raw_btn.setEnabled(False)
        self.dbc_send_btn.setEnabled(False)
        self.replay_start_btn.setEnabled(False)
        self.connection_state_label.setText("Disconnected")
        self.connection_state_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #fbe9e7; color: #8e2c1e;"
        )
        self.status.showMessage("Disconnected")
        self._diag_log("Disconnect")

    def _poll_queue(self) -> None:
        processed = 0
        qsize = self.backend.message_queue.qsize()
        render_stride = 1
        if self.db is not None:
            # DBC decode + symbolic updates are expensive; keep monitor responsive by default.
            render_stride = 2
        if qsize > 5000:
            render_stride = 20
        elif qsize > 2000:
            render_stride = 10
        elif qsize > 800:
            render_stride = 5
        elif qsize > 300 and render_stride < 2:
            render_stride = 2

        decode_stride = 1
        if qsize > 5000:
            decode_stride = 30
        elif qsize > 2000:
            decode_stride = 15
        elif qsize > 800:
            decode_stride = 8
        elif qsize > 300:
            decode_stride = 4

        on_monitor_tab = self.tabs.currentWidget() is self.monitor_tab
        on_plot_tab = self.tabs.currentWidget() is self.plot_tab
        wants_plot_decode = bool(self._plot_active_signals) and on_plot_tab
        decode_enabled = self.db is not None and (on_monitor_tab or wants_plot_decode)

        start = time.perf_counter()
        for idx in range(self._MAX_PER_CYCLE):
            try:
                item = self.backend.message_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item and item[0] == "error":
                self._disconnect()
                self.status.showMessage(f"CAN Error: {item[1]}")
                self._diag_log(f"CAN Error: {item[1]}")
                break
            render = (idx % render_stride) == 0
            decode = decode_enabled and ((idx % decode_stride) == 0)
            self._show_message(item, render=render, decode=decode)
            processed += 1
            # Keep UI responsive by capping work-time in the hot poll loop.
            if (time.perf_counter() - start) > 0.004:
                break
        if render_stride > 1:
            now = time.time()
            stride_changed = render_stride != self._last_stride_notice_value
            timed_out = (now - self._last_stride_notice_ts) >= 1.0
            if stride_changed or timed_out:
                self.status.showMessage(
                    f"High traffic: UI sampling 1/{render_stride} frames (queue={qsize})."
                )
                self._diag_log(
                    f"High traffic: render=1/{render_stride}, decode=1/{decode_stride} "
                    f"(queue={qsize}, processed={processed})"
                )
                self._last_stride_notice_ts = now
                self._last_stride_notice_value = render_stride
        elif self._last_stride_notice_value != 1:
            self._last_stride_notice_value = 1
        self.diag_queue_label.setText(f"Queue: {qsize}")
        self.diag_mode_label.setText(
            f"Render: 1/{render_stride}  Decode: {'off' if not decode_enabled else f'1/{decode_stride}'}"
        )

    def _show_message(self, msg: can.Message, render: bool = True, decode: bool = True) -> None:
        now = time.time()
        if self._trace_start is None:
            self._trace_start = now
        rel = f"{now - self._trace_start:.3f}"
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if msg.is_error_frame:
            self.error_count += 1
            if render:
                self._pending_raw_rows.append((
                    [ts, rel, "---", "ERR", "---", " ".join(f"{b:02X}" for b in msg.data)],
                    True,
                ))
                self._raw_needs_scroll = True
            self._write_log_message(msg, ts)
            return

        arb = f"0x{msg.arbitration_id:08X}" if msg.is_extended_id else f"0x{msg.arbitration_id:03X}"
        frame = "EXT" if msg.is_extended_id else "STD"
        data = " ".join(f"{b:02X}" for b in msg.data)
        self.message_count += 1
        if render:
            self._pending_raw_rows.append(([ts, rel, arb, frame, str(msg.dlc), data], False))
            self._raw_needs_scroll = True
        if decode:
            # Keep only latest message per arbitration ID; decode on timer.
            self._pending_decode[msg.arbitration_id] = (msg, ts, rel)
        self._write_log_message(msg, ts)

    def _flush_render_updates(self) -> None:
        if not self._pending_raw_rows:
            return
        # Bound per-frame widget churn.
        chunk: list[tuple[list[str], bool]] = []
        for _ in range(min(120, len(self._pending_raw_rows))):
            chunk.append(self._pending_raw_rows.popleft())

        self._raw_model.append_rows(chunk)
        if self._raw_needs_scroll and self.autoscroll_checkbox.isChecked():
            self.raw_table.scrollToBottom()
            self._raw_needs_scroll = False

    def _flush_decode_updates(self) -> None:
        if not self._pending_decode:
            return
        # Keep decode time bounded so UI cannot freeze under heavy DBC traffic.
        start = time.perf_counter()
        processed_arb: list[int] = []
        for arb_id, payload in list(self._pending_decode.items())[:120]:
            msg, ts, rel = payload
            self._decode_and_display(msg, ts, rel)
            processed_arb.append(arb_id)
            if (time.perf_counter() - start) > 0.012:
                break
        for arb_id in processed_arb:
            self._pending_decode.pop(arb_id, None)

    def _load_dbc(self) -> None:
        if cantools is None:
            QMessageBox.critical(self, "Missing Library", "cantools is not installed.")
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Load DBC File", "", "DBC files (*.dbc);;All files (*.*)")
        if not filename:
            return
        try:
            self.db = cantools.database.load_file(filename)
        except Exception as exc:
            QMessageBox.critical(self, "DBC Error", str(exc))
            return
        self._msg_items.clear()
        self._signal_items.clear()
        self._signal_stats.clear()
        self._prev_sig_values.clear()
        self._plot_buffers.clear()
        self._dbc_msg_by_id.clear()
        self._dbc_signal_units.clear()
        self.sym_tree.clear()
        self.dbc_label.setText(f"DBC: {Path(filename).name} ({len(self.db.messages)} msgs)")
        self.dbc_send_msg_combo.clear()
        self.dbc_send_msg_combo.addItems(sorted(m.name for m in self.db.messages))
        self._dbc_msg_by_id = {m.frame_id: m for m in self.db.messages}
        for msg in self.db.messages:
            self._dbc_signal_units[msg.frame_id] = {sig.name: (sig.unit or "") for sig in msg.signals}
        self._populate_plot_signal_list()
        if self.backend.is_connected:
            self.dbc_send_btn.setEnabled(True)
        self.status.showMessage(f"Loaded DBC: {Path(filename).name}")
        self._diag_log(f"Loaded DBC: {Path(filename).name} ({len(self.db.messages)} messages)")

    def _decode_and_display(self, msg: can.Message, ts: str, rel: str) -> None:
        if self.db is None or msg.is_error_frame:
            return
        db_msg = self._dbc_msg_by_id.get(msg.arbitration_id)
        if db_msg is None:
            return
        try:
            decoded = db_msg.decode(msg.data, decode_choices=False)
        except Exception:
            return

        parent = self._msg_items.get(msg.arbitration_id)
        if parent is None:
            parent = QTreeWidgetItem([db_msg.name, "", "", ts, rel, "", ""])
            self.sym_tree.addTopLevelItem(parent)
            self._msg_items[msg.arbitration_id] = parent
            parent.setExpanded(True)
        else:
            parent.setText(3, ts)
            parent.setText(4, rel)

        for sig_name, value in decoded.items():
            key = (msg.arbitration_id, sig_name)
            unit = self._dbc_signal_units.get(msg.arbitration_id, {}).get(sig_name, "")
            val_str = f"{value:.4g}" if isinstance(value, float) else str(value)
            stats = self._signal_stats.setdefault(key, {"min": None, "max": None, "count": 0})
            stats["count"] = int(stats["count"]) + 1
            if isinstance(value, (int, float)):
                fv = float(value)
                stats["min"] = fv if stats["min"] is None else min(float(stats["min"]), fv)
                stats["max"] = fv if stats["max"] is None else max(float(stats["max"]), fv)
                key_name = f"{db_msg.name}.{sig_name}"
                buf = self._plot_buffers.setdefault(key_name, collections.deque(maxlen=500))
                buf.append(fv)
            min_str = f"{stats['min']:.4g}" if stats["min"] is not None else ""
            max_str = f"{stats['max']:.4g}" if stats["max"] is not None else ""

            item = self._signal_items.get(key)
            if item is None:
                item = QTreeWidgetItem([sig_name, val_str, unit, ts, rel, min_str, max_str])
                parent.addChild(item)
                self._signal_items[key] = item
                self._prev_sig_values[key] = val_str
            else:
                # Keep timestamp/relative columns moving in real-time, and
                # always refresh value to avoid stale-looking rows.
                item.setText(1, val_str)
                item.setText(2, unit)
                item.setText(3, ts)
                item.setText(4, rel)
                item.setText(5, min_str)
                item.setText(6, max_str)
                self._prev_sig_values[key] = val_str

    def _on_dbc_send_msg_change(self, msg_name: str) -> None:
        while self.dbc_send_form.rowCount():
            self.dbc_send_form.removeRow(0)
        self._dbc_signal_controls.clear()
        self._dbc_signal_meta.clear()
        if self.db is None or not msg_name:
            return
        try:
            db_msg = self.db.get_message_by_name(msg_name)
        except Exception:
            return
        for sig in sorted(db_msg.signals, key=lambda s: s.name):
            if sig.choices:
                ctrl = QComboBox()
                ctrl.addItems([str(v) for v in sig.choices.values()])
                self._dbc_signal_meta[sig.name] = {"is_enum": True, "choices": sig.choices}
            else:
                ctrl = QLineEdit(str(sig.minimum if sig.minimum is not None else 0))
                self._dbc_signal_meta[sig.name] = {"is_enum": False, "min": sig.minimum, "max": sig.maximum}
            self._dbc_signal_controls[sig.name] = ctrl
            self.dbc_send_form.addRow(f"{sig.name}:", ctrl)

    def _send_raw_message(self) -> None:
        if not self.backend.is_connected:
            QMessageBox.critical(self, "Send Error", "Not connected to CAN bus.")
            return
        try:
            arb_id = int(self.send_raw_id.text().strip(), 16)
        except ValueError:
            QMessageBox.critical(self, "Send Error", "Arb ID must be hex.")
            return
        data = []
        for token in self.send_raw_data.text().strip().split():
            try:
                b = int(token, 16)
            except ValueError:
                QMessageBox.critical(self, "Send Error", f"Invalid byte: {token}")
                return
            if b < 0 or b > 255:
                QMessageBox.critical(self, "Send Error", f"Byte out of range: {token}")
                return
            data.append(b)
        if len(data) > 8:
            QMessageBox.critical(self, "Send Error", "Classic CAN data must be at most 8 bytes.")
            return
        ok, msg = self.backend.send_message(
            can.Message(arbitration_id=arb_id, data=bytes(data), is_extended_id=self.send_raw_ext.isChecked())
        )
        if not ok:
            QMessageBox.critical(self, "Send Error", msg)
            return
        self.status.showMessage("Raw frame sent.")

    def _send_dbc_message(self) -> None:
        if not self.backend.is_connected or self.db is None:
            QMessageBox.critical(self, "Send Error", "Connect bus and load DBC first.")
            return
        msg_name = self.dbc_send_msg_combo.currentText().strip()
        if not msg_name:
            QMessageBox.critical(self, "Send Error", "Select a DBC message.")
            return
        try:
            db_msg = self.db.get_message_by_name(msg_name)
        except Exception as exc:
            QMessageBox.critical(self, "Send Error", str(exc))
            return
        sig_data: dict[str, int | float] = {}
        for sig in db_msg.signals:
            meta = self._dbc_signal_meta.get(sig.name)
            ctrl = self._dbc_signal_controls.get(sig.name)
            if meta is None or ctrl is None:
                continue
            if meta["is_enum"]:
                assert isinstance(ctrl, QComboBox)
                label = ctrl.currentText()
                sig_data[sig.name] = int(next((k for k, v in meta["choices"].items() if str(v) == label), 0))
            else:
                assert isinstance(ctrl, QLineEdit)
                try:
                    val = float(ctrl.text().strip())
                except ValueError:
                    val = 0.0
                if meta["min"] is not None and val < meta["min"]:
                    val = float(meta["min"])
                if meta["max"] is not None and val > meta["max"]:
                    val = float(meta["max"])
                sig_data[sig.name] = val
        try:
            data = db_msg.encode(sig_data, padding=True, strict=False)
        except Exception as exc:
            QMessageBox.critical(self, "Send Error", str(exc))
            return
        ok, msg = self.backend.send_message(
            can.Message(arbitration_id=db_msg.frame_id, data=data, is_extended_id=db_msg.is_extended_frame)
        )
        if not ok:
            QMessageBox.critical(self, "Send Error", msg)
            return
        self.status.showMessage(f"DBC message sent: {msg_name}")

    def _toggle_logging(self) -> None:
        if self.log_writer is None:
            self._start_logging()
        else:
            self._stop_logging()

    def _start_logging(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save CAN Trace", "", "CSV files (*.csv);;BLF files (*.blf)"
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
            QMessageBox.critical(self, "Log Error", str(exc))
            return
        self.log_btn.setText("Stop Log")
        self.status.showMessage(f"Logging to: {filename}")
        self._diag_log(f"Logging started: {filename}")

    def _stop_logging(self) -> None:
        try:
            if self.log_format == "blf" and self.log_writer is not None:
                self.log_writer.stop()
            elif self.log_file is not None:
                self.log_file.close()
        except Exception:
            pass
        self.log_writer = None
        self.log_file = None
        self.log_format = None
        self.log_btn.setText("Start Log")
        self._diag_log("Logging stopped")

    def _write_log_message(self, msg: can.Message, ts: str) -> None:
        if self.log_writer is None:
            return
        try:
            if self.log_format == "blf":
                self.log_writer.on_message_received(msg)
            else:
                arb = "---" if msg.is_error_frame else (
                    f"0x{msg.arbitration_id:08X}" if msg.is_extended_id else f"0x{msg.arbitration_id:03X}"
                )
                frame = "ERR" if msg.is_error_frame else ("EXT" if msg.is_extended_id else "STD")
                data = " ".join(f"{b:02X}" for b in msg.data)
                dlc = "" if msg.is_error_frame else msg.dlc
                self.log_writer.writerow([ts, arb, frame, dlc, data])
        except Exception:
            pass

    def _replay_open_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open CAN Trace",
            "",
            "All supported (*.asc *.blf *.csv *.log);;ASC files (*.asc);;BLF files (*.blf);;CSV files (*.csv);;All files (*.*)",
        )
        if not filename:
            return
        messages: list[can.Message] = []
        try:
            if filename.lower().endswith(".csv"):
                with open(filename, newline="") as fh:
                    for row in csv.reader(fh):
                        if not row or row[0].startswith("Timestamp"):
                            continue
                        try:
                            arb = row[1]
                            frame = row[2]
                            data = row[4]
                            if arb in ("---", ""):
                                continue
                            messages.append(
                                can.Message(
                                    timestamp=float(len(messages)) * 0.01,
                                    arbitration_id=int(arb, 16),
                                    is_extended_id=frame.upper() == "EXT",
                                    data=bytes(int(x, 16) for x in data.split() if x),
                                )
                            )
                        except Exception:
                            continue
            else:
                with can.LogReader(filename) as reader:
                    for msg in reader:
                        if not msg.is_error_frame:
                            messages.append(msg)
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return

        self._replay_messages = messages
        self.replay_info.setText(f"{len(messages)} messages loaded")
        self.replay_start_btn.setEnabled(bool(messages) and self.backend.is_connected)
        self._diag_log(f"Replay file loaded: {Path(filename).name} ({len(messages)} messages)")

        self.replay_table.setRowCount(0)
        t0 = messages[0].timestamp if messages else 0.0
        for msg in messages[:2000]:
            idx = self.replay_table.rowCount()
            self.replay_table.insertRow(idx)
            arb = f"0x{msg.arbitration_id:08X}" if msg.is_extended_id else f"0x{msg.arbitration_id:03X}"
            row = [f"{msg.timestamp - t0:.4f}", arb, "EXT" if msg.is_extended_id else "STD", str(msg.dlc),
                   " ".join(f"{b:02X}" for b in msg.data)]
            for col, value in enumerate(row):
                self.replay_table.setItem(idx, col, QTableWidgetItem(value))

    def _replay_start(self) -> None:
        if not self._replay_messages or not self.backend.is_connected:
            return
        try:
            speed = max(0.01, float(self.replay_speed.text().strip()))
        except ValueError:
            speed = 1.0
            self.replay_speed.setText("1.0")
        self.replay_start_btn.setEnabled(False)
        self.replay_start_btn.setText("Replaying...")
        self._diag_log(f"Replay started: {len(self._replay_messages)} messages")

        def _run() -> None:
            msgs = self._replay_messages
            t0 = msgs[0].timestamp
            start = time.time()
            for msg in msgs:
                if not self.backend.is_connected:
                    break
                delay = (msg.timestamp - t0) / speed
                elapsed = time.time() - start
                if delay > elapsed:
                    time.sleep(delay - elapsed)
                ok, _ = self.backend.send_message(msg)
                if not ok:
                    break
            QTimer.singleShot(0, self._replay_done)

        threading.Thread(target=_run, daemon=True).start()

    def _replay_done(self) -> None:
        self.replay_start_btn.setText("Replay")
        self.replay_start_btn.setEnabled(bool(self._replay_messages) and self.backend.is_connected)
        self._diag_log("Replay finished")

    def _populate_plot_signal_list(self) -> None:
        if not _MATPLOTLIB_AVAILABLE:
            return
        self.plot_signal_list.clear()
        if self.db is None:
            return
        for msg in sorted(self.db.messages, key=lambda m: m.name):
            for sig in sorted(msg.signals, key=lambda s: s.name):
                if not sig.choices:
                    self.plot_signal_list.addItem(f"{msg.name}.{sig.name}")

    def _apply_plot_selection(self) -> None:
        if not _MATPLOTLIB_AVAILABLE:
            return
        self._plot_active_signals = [item.text() for item in self.plot_signal_list.selectedItems()]

    def _clear_plot(self) -> None:
        if not _MATPLOTLIB_AVAILABLE:
            return
        self._plot_active_signals = []
        self.plot_ax.cla()
        self.plot_ax.set_xlabel("Sample index")
        self.plot_ax.set_ylabel("Value")
        self.plot_ax.grid(True)
        self.plot_canvas.draw_idle()

    def _refresh_plot(self) -> None:
        if not _MATPLOTLIB_AVAILABLE or not self._plot_active_signals:
            return
        self.plot_ax.cla()
        self.plot_ax.set_xlabel("Sample index")
        self.plot_ax.set_ylabel("Value")
        self.plot_ax.grid(True)
        for key_name in self._plot_active_signals:
            values = self._plot_buffers.get(key_name)
            if values and len(values) > 1:
                self.plot_ax.plot(values, label=key_name.split(".")[-1], linewidth=1.5)
        if self._plot_active_signals:
            self.plot_ax.legend(loc="upper left", fontsize=8)
        self.plot_canvas.draw_idle()

    def _clear_all_views(self) -> None:
        self._raw_model.clear()
        self.sym_tree.clear()
        self._msg_items.clear()
        self._signal_items.clear()
        self._signal_stats.clear()
        self._prev_sig_values.clear()
        self._plot_buffers.clear()
        self._pending_raw_rows.clear()
        self._pending_decode.clear()
        self._raw_needs_scroll = False
        self._raw_rollover_notified = False
        self.message_count = 0
        self.error_count = 0
        self.backend.dropped_count = 0
        self._trace_start = None
        self._refresh_stats()
        self.status.showMessage("Cleared monitor views and counters.")
        self._diag_log("Cleared monitor views and counters")

    def _refresh_stats(self) -> None:
        self.msg_count_label.setText(f"Messages: {self.message_count}")
        self.err_count_label.setText(f"Errors: {self.error_count}")
        self.drop_count_label.setText(
            f"Dropped: {self.backend.dropped_count:,}" if self.backend.dropped_count else ""
        )

    def _diag_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.diag_text.append(f"[{ts}] {message}")
