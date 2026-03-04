"""Main window for the PySide6 migration preview."""

from __future__ import annotations

import csv
import collections
import fnmatch
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import can
from PySide6.QtCore import Qt, QTimer, QStringListModel
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QCompleter,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QScrollArea,
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
from app_version import __version__

LOGGER = logging.getLogger("can_viewer_qt.main_window")


class CANViewerQtMainWindow(QMainWindow):
    _MAX_RAW_ROWS = 8000
    _MAX_PER_CYCLE = 60

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"CAN Bus Viewer {__version__}")
        self.resize(1420, 940)
        self.setMinimumSize(1080, 700)

        self.backend = QtCanBackend()
        self.message_count = 0
        self.error_count = 0
        self._trace_start: float | None = None

        self._dbc_files: list[Path] = []
        self._dbc_records_by_display: dict[str, dict] = {}
        self._dbc_msg_by_id: dict[int, dict] = {}
        self._signal_key_to_source_signal: dict[str, tuple[str, str]] = {}
        self._msg_items: dict[int, QTreeWidgetItem] = {}
        self._signal_items: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._signal_stats: dict[tuple[int, str], dict[str, float | int | None]] = {}
        self._prev_sig_values: dict[tuple[int, str], str] = {}
        self._dbc_watch_ids: set[int] = set()
        self._dbc_watch_name_to_id: dict[str, int] = {}
        self._dbc_selected_replay_row = -1
        self._signal_highlight_timers: dict[tuple[int, str], QTimer] = {}
        self._send_cards: list[dict] = []
        self._trigger_rows: list[dict] = []
        self._trigger_match_state: dict[int, bool] = {}
        self._prev_trigger_values: dict[int, float] = {}
        self._active_captures: list[dict] = []
        self._capture_index_by_base: dict[str, int] = {}
        self._raw_periodic_timer: QTimer | None = None

        self.log_writer = None
        self.log_file = None
        self.log_format: str | None = None

        self._replay_messages: list[can.Message] = []
        self._plot_buffers: dict[str, collections.deque[float]] = {}
        self._plot_active_signals: list[str] = []
        self._plot_all_signals: list[str] = []
        self._last_stride_notice_ts = 0.0
        self._last_stride_notice_value = 1
        self._dbc_signal_units: dict[int, dict[str, str]] = {}
        self._pending_raw_rows: collections.deque[tuple[list[str], bool]] = collections.deque()
        self._pending_decode: dict[int, tuple[can.Message, str, str]] = {}
        self._raw_needs_scroll = False
        self._raw_rollover_notified = False
        self._raw_model = RawTableModel(max_rows=self._MAX_RAW_ROWS)
        self._current_bitrate = 500000
        self._bus_bits_window: collections.deque[tuple[float, int]] = collections.deque()

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
        self._stop_raw_periodic_send()
        for card in self._send_cards:
            self._stop_dbc_card_periodic(card)
        self._disconnect()
        self._stop_logging()
        for capture in self._active_captures:
            try:
                writer = capture.get("writer")
                if writer is not None and hasattr(writer, "stop"):
                    writer.stop()
                if "fh" in capture:
                    capture["fh"].close()
            except Exception:
                pass
        self._active_captures.clear()
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

        self.load_dbc_btn = QPushButton("Add DBC")
        self.load_dbc_btn.clicked.connect(self._add_dbc_files)
        layout.addWidget(self.load_dbc_btn)
        self.remove_dbc_btn = QPushButton("Remove DBC")
        self.remove_dbc_btn.clicked.connect(self._remove_selected_dbc_files)
        layout.addWidget(self.remove_dbc_btn)

        self.log_btn = QPushButton("Start Log")
        self.log_btn.clicked.connect(self._toggle_logging)
        layout.addWidget(self.log_btn)

        self.dbc_label = QLabel("No DBC loaded")
        self.dbc_label.setStyleSheet("color: #586a7c;")
        layout.addWidget(self.dbc_label)

        layout.addStretch(1)
        self.bus_load_label = QLabel("Bus load: 0.0%")
        self.msg_count_label = QLabel("Messages: 0")
        self.err_count_label = QLabel("Errors: 0")
        self.drop_count_label = QLabel("")
        self.err_count_label.setStyleSheet("color: #8f1d21;")
        self.drop_count_label.setStyleSheet("color: #9a6700;")
        layout.addWidget(self.bus_load_label)
        layout.addWidget(self.drop_count_label)
        layout.addWidget(self.err_count_label)
        layout.addWidget(self.msg_count_label)
        return row

    def _build_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()
        self.monitor_tab = self._build_monitor_tab()
        self.plot_tab = self._build_plot_tab()
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.send_tab = self._build_send_tab()
        self.tabs.addTab(self.send_tab, "Send")
        self.tabs.addTab(self._build_replay_tab(), "Replay")
        self.tabs.addTab(self.plot_tab, "Plot")
        self.tabs.addTab(self._build_trigger_tab(), "Triggers")
        self.tabs.addTab(self._build_diag_tab(), "Diag")
        self.tabs.addTab(self._build_about_tab(), "About")
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
        watch_row = QHBoxLayout()
        watch_row.addWidget(QLabel("Watch DBC message:"))
        self.watch_msg_combo = QComboBox()
        self.watch_msg_combo.setMinimumWidth(230)
        watch_row.addWidget(self.watch_msg_combo, 1)
        self.watch_add_btn = QPushButton("+ Add")
        self.watch_add_btn.clicked.connect(self._add_watch_message)
        watch_row.addWidget(self.watch_add_btn)
        self.watch_clear_btn = QPushButton("Clear")
        self.watch_clear_btn.clicked.connect(self._clear_watch_messages)
        watch_row.addWidget(self.watch_clear_btn)
        sym_layout.addLayout(watch_row)

        self.watch_list = QListWidget()
        self.watch_list.setMaximumHeight(90)
        sym_layout.addWidget(self.watch_list)
        sym_split = QSplitter(Qt.Orientation.Vertical)
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
        sym_split.addWidget(self.sym_tree)

        self.dbc_history_table = QTableWidget(0, 5)
        self.dbc_history_table.setHorizontalHeaderLabels(
            ["Timestamp", "Rel (s)", "Message", "Signal", "Value"]
        )
        self.dbc_history_table.verticalHeader().setVisible(False)
        self.dbc_history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dbc_history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dbc_history_table.horizontalHeader().setStretchLastSection(True)
        self.dbc_history_table.setMaximumHeight(220)
        sym_split.addWidget(self.dbc_history_table)
        sym_split.setSizes([520, 180])
        sym_layout.addWidget(sym_split, 1)

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
        self.send_raw_periodic = QCheckBox("Periodic")
        self.send_raw_period_ms = QLineEdit("100")
        self.send_raw_period_ms.setMaximumWidth(90)
        self.send_raw_periodic.toggled.connect(self._toggle_raw_periodic_send)
        self.send_raw_periodic.setEnabled(False)
        self.send_raw_btn = QPushButton("Send Raw")
        self.send_raw_btn.setEnabled(False)
        self.send_raw_btn.clicked.connect(self._send_raw_message)
        raw_form.addRow("Arb ID (hex):", self.send_raw_id)
        raw_form.addRow("Data bytes (hex):", self.send_raw_data)
        raw_form.addRow("", self.send_raw_ext)
        raw_period_row = QHBoxLayout()
        raw_period_row.addWidget(self.send_raw_periodic)
        raw_period_row.addWidget(QLabel("ms:"))
        raw_period_row.addWidget(self.send_raw_period_ms)
        raw_period_row.addStretch(1)
        raw_period_widget = QWidget()
        raw_period_widget.setLayout(raw_period_row)
        raw_form.addRow("", raw_period_widget)
        raw_form.addRow("", self.send_raw_btn)

        dbc_group = QGroupBox("DBC Send")
        dbc_layout = QVBoxLayout(dbc_group)
        top = QHBoxLayout()
        add_card_btn = QPushButton("+ Add Message Card")
        add_card_btn.clicked.connect(self._add_dbc_send_card_prompted)
        top.addWidget(add_card_btn)
        top.addStretch(1)
        dbc_layout.addLayout(top)
        self.dbc_send_cards_host = QWidget()
        self.dbc_send_cards_layout = QVBoxLayout(self.dbc_send_cards_host)
        self.dbc_send_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.dbc_send_cards_layout.addStretch(1)
        cards_scroll = QScrollArea()
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_scroll.setStyleSheet(
            "QScrollArea { background: #f4f7fb; border: 1px solid #d7dee8; }"
            "QScrollArea > QWidget > QWidget { background: #f4f7fb; }"
        )
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setWidget(self.dbc_send_cards_host)
        dbc_layout.addWidget(cards_scroll, 1)

        layout.addWidget(raw_group)
        layout.addWidget(dbc_group, 1)
        self._add_dbc_send_card()
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

        split = QSplitter(Qt.Orientation.Horizontal)

        self.replay_table = QTableWidget(0, 5)
        self.replay_table.setHorizontalHeaderLabels(
            ["Timestamp (s)", "Arb ID", "Frame", "DLC", "Data (hex)"]
        )
        self.replay_table.verticalHeader().setVisible(False)
        self.replay_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.replay_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.replay_table.horizontalHeader().setStretchLastSection(True)
        self.replay_table.itemSelectionChanged.connect(self._update_replay_decode_view)
        split.addWidget(self.replay_table)

        self.replay_decode_tree = QTreeWidget()
        self.replay_decode_tree.setColumnCount(3)
        self.replay_decode_tree.setHeaderLabels(["Signal", "Value", "Unit"])
        self.replay_decode_tree.header().setStretchLastSection(True)
        split.addWidget(self.replay_decode_tree)
        split.setSizes([760, 360])
        layout.addWidget(split, 1)
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
        self.plot_signal_search = QLineEdit()
        self.plot_signal_search.setPlaceholderText("Search message or signal...")
        self.plot_signal_search.textChanged.connect(self._filter_plot_signal_list)
        left.addWidget(self.plot_signal_search)
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

    def _build_trigger_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        output_group = QGroupBox("Master Trigger Output")
        output_layout = QGridLayout(output_group)
        output_layout.addWidget(QLabel("Directory:"), 0, 0)
        self.trigger_output_dir = QLineEdit(str(Path.cwd()))
        output_layout.addWidget(self.trigger_output_dir, 0, 1)
        out_browse = QPushButton("Browse")
        out_browse.clicked.connect(self._browse_trigger_output_dir)
        output_layout.addWidget(out_browse, 0, 2)
        output_layout.addWidget(QLabel("Format:"), 1, 0)
        self.trigger_output_format = QComboBox()
        self.trigger_output_format.addItems(["BLF", "ASC", "CSV"])
        output_layout.addWidget(self.trigger_output_format, 1, 1)
        layout.addWidget(output_group)

        button_row = QHBoxLayout()
        add_btn = QPushButton("+ Trigger")
        add_btn.clicked.connect(self._add_trigger_row)
        del_btn = QPushButton("Remove Selected")
        del_btn.clicked.connect(self._remove_selected_trigger_rows)
        button_row.addWidget(add_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.trigger_table = QTableWidget(0, 12)
        self.trigger_table.setHorizontalHeaderLabels(
            [
                "Type",
                "Source",
                "Signal",
                "Op",
                "Unit",
                "Value",
                "Log Bytes",
                "Base Name",
                "Use Master",
                "Output Dir",
                "Format",
                "Enabled",
            ]
        )
        self.trigger_table.horizontalHeader().setStretchLastSection(True)
        self.trigger_table.verticalHeader().setVisible(False)
        self.trigger_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.trigger_table, 1)
        self._add_trigger_row()
        return tab

    def _build_about_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        about = QTextEdit()
        about.setReadOnly(True)
        about.setPlainText(
            f"CAN Bus Viewer\n\nVersion: {__version__}\n\n"
            "Qt preview includes monitor, send cards, replay, plotting, diagnostics, "
            "and trigger-based binary capture."
        )
        layout.addWidget(about, 1)
        layout.addWidget(QLabel("Loaded DBC files:"))
        self.about_dbc_files_list = QListWidget()
        self.about_dbc_files_list.setMaximumHeight(200)
        layout.addWidget(self.about_dbc_files_list)
        self.about_signal_search = QLineEdit()
        self.about_signal_search.setPlaceholderText("Search loaded DBC messages/signals...")
        self.about_signal_search.textChanged.connect(self._refresh_about_dbc_files)
        layout.addWidget(self.about_signal_search)
        self.about_signal_list = QListWidget()
        self.about_signal_list.setMaximumHeight(200)
        layout.addWidget(self.about_signal_list)
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
        self._current_bitrate = bitrate

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
        self.send_raw_periodic.setEnabled(True)
        self._set_send_cards_enabled(bool(self._dbc_records_by_display))
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
        self.send_raw_periodic.setEnabled(False)
        self._stop_raw_periodic_send()
        for card in self._send_cards:
            self._stop_dbc_card_periodic(card)
        self._set_send_cards_enabled(False)
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
        if self._dbc_records_by_display:
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
        decode_enabled = bool(self._dbc_records_by_display) and (on_monitor_tab or wants_plot_decode)

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
        bit_overhead = 67 if msg.is_extended_id else 47
        self._bus_bits_window.append((now, bit_overhead + (msg.dlc * 8)))
        self._feed_active_captures(msg)
        self._evaluate_raw_triggers(msg)
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

    def _browse_trigger_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Trigger Output Directory")
        if selected:
            self.trigger_output_dir.setText(selected)

    def _add_dbc_files(self) -> None:
        if cantools is None:
            QMessageBox.critical(self, "Missing Library", "cantools is not installed.")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add DBC Files", "", "DBC files (*.dbc);;All files (*.*)")
        if not files:
            return
        added = 0
        for filename in files:
            path = Path(filename).resolve()
            if path in self._dbc_files:
                continue
            try:
                db = cantools.database.load_file(str(path))
            except Exception as exc:
                QMessageBox.critical(self, "DBC Error", f"{path.name}: {exc}")
                continue
            self._dbc_files.append(path)
            for msg in db.messages:
                display = f"{path.stem}:{msg.name}"
                rec = {"display": display, "file": path, "msg": msg}
                self._dbc_records_by_display[display] = rec
                if msg.frame_id in self._dbc_msg_by_id:
                    prev = self._dbc_msg_by_id[msg.frame_id]["display"]
                    self._diag_log(
                        f"DBC frame-id override 0x{msg.frame_id:X}: {prev} -> {display}"
                    )
                self._dbc_msg_by_id[msg.frame_id] = rec
            added += 1
        if added:
            self._on_dbc_registry_changed()
            self.status.showMessage(f"Added {added} DBC file(s).")

    def _remove_selected_dbc_files(self) -> None:
        try:
            if not self._dbc_files:
                QMessageBox.information(self, "Remove DBC", "No DBC files are currently loaded.")
                return
            selected_names = self._prompt_dbc_removal_selection()
            if not selected_names:
                return
            self._dbc_files = [p for p in self._dbc_files if p.name not in selected_names]
            self._rebuild_dbc_registry()
            self._on_dbc_registry_changed()
            self.status.showMessage(f"Removed {len(selected_names)} DBC file(s).")
            LOGGER.info("Removed DBC files: %s", ", ".join(selected_names))
        except Exception as exc:
            LOGGER.exception("Failed removing DBC files")
            QMessageBox.critical(
                self,
                "Remove DBC Error",
                f"Failed to remove DBC files: {exc}\n\nCheck the Qt log file for details.",
            )

    def _prompt_dbc_removal_selection(self) -> list[str]:
        selected = self._prompt_select_from_list(
            title="Remove DBC Files",
            label="Select DBC files to remove:",
            items=[p.name for p in self._dbc_files],
            multi_select=True,
        )
        if selected is None:
            return []
        return selected

    def _prompt_select_from_list(
        self,
        title: str,
        label: str,
        items: list[str],
        multi_select: bool = False,
    ) -> list[str] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(520, 360)
        dialog.setStyleSheet(
            "QDialog { background: #ffffff; color: #17202a; }"
            "QListWidget { background: #ffffff; color: #17202a; border: 1px solid #c9d3e0; }"
            "QLabel { color: #17202a; }"
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(label))
        search = QLineEdit()
        search.setPlaceholderText("Search (* and ? wildcards supported)")
        layout.addWidget(search)
        lst = QListWidget()
        lst.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multi_select
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(lst, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def _refresh() -> None:
            query = search.text().strip()
            selected_before = {item.text() for item in lst.selectedItems()}
            lst.clear()
            for entry in items:
                if self._matches_query(entry, query):
                    lst.addItem(entry)
            if multi_select and selected_before:
                for i in range(lst.count()):
                    if lst.item(i).text() in selected_before:
                        lst.item(i).setSelected(True)
            elif lst.count() and not multi_select:
                lst.setCurrentRow(0)

        search.textChanged.connect(lambda _: _refresh())
        _refresh()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if multi_select:
            return [item.text() for item in lst.selectedItems()]
        current = lst.currentItem()
        return [current.text()] if current is not None else None

    def _rebuild_dbc_registry(self) -> None:
        self._dbc_records_by_display.clear()
        self._dbc_msg_by_id.clear()
        for path in self._dbc_files:
            try:
                db = cantools.database.load_file(str(path))
            except Exception:
                continue
            for msg in db.messages:
                display = f"{path.stem}:{msg.name}"
                rec = {"display": display, "file": path, "msg": msg}
                self._dbc_records_by_display[display] = rec
                self._dbc_msg_by_id[msg.frame_id] = rec

    def _on_dbc_registry_changed(self) -> None:
        self._msg_items.clear()
        self._signal_items.clear()
        self._signal_stats.clear()
        self._prev_sig_values.clear()
        self._plot_buffers.clear()
        self._dbc_signal_units.clear()
        self._signal_key_to_source_signal.clear()
        self._dbc_watch_ids.clear()
        self._dbc_watch_name_to_id.clear()
        self.sym_tree.clear()
        self.dbc_history_table.setRowCount(0)
        self.watch_list.clear()
        for rec in self._dbc_records_by_display.values():
            msg = rec["msg"]
            self._dbc_watch_name_to_id[rec["display"]] = msg.frame_id
            self._dbc_signal_units[msg.frame_id] = {sig.name: (sig.unit or "") for sig in msg.signals}
            for sig in msg.signals:
                key = f"{rec['display']}.{sig.name}"
                self._signal_key_to_source_signal[key] = (rec["display"], sig.name)
        self.watch_msg_combo.clear()
        watch_names = sorted(self._dbc_watch_name_to_id)
        self.watch_msg_combo.addItems(watch_names)
        self._set_combo_search_items(self.watch_msg_combo, watch_names)
        self.dbc_label.setText(f"DBCs: {len(self._dbc_files)} files, {len(self._dbc_records_by_display)} msgs")
        self._refresh_about_dbc_files()
        self._refresh_send_card_message_lists()
        self._populate_plot_signal_list()
        self._refresh_trigger_sources()
        self._set_send_cards_enabled(self.backend.is_connected and bool(self._dbc_records_by_display))

    def _refresh_about_dbc_files(self) -> None:
        if not hasattr(self, "about_dbc_files_list"):
            return
        self.about_dbc_files_list.clear()
        for path in self._dbc_files:
            self.about_dbc_files_list.addItem(path.name)
        if not hasattr(self, "about_signal_list"):
            return
        self.about_signal_list.clear()
        query = self.about_signal_search.text().strip() if hasattr(self, "about_signal_search") else ""
        for key in sorted(self._signal_key_to_source_signal):
            if self._matches_query(key, query):
                self.about_signal_list.addItem(key)

    def _decode_and_display(self, msg: can.Message, ts: str, rel: str) -> None:
        if (not self._dbc_records_by_display and not self._dbc_msg_by_id) or msg.is_error_frame:
            return
        rec_or_msg = self._dbc_msg_by_id.get(msg.arbitration_id)
        if rec_or_msg is None:
            return
        if isinstance(rec_or_msg, dict):
            rec = rec_or_msg
            db_msg = rec["msg"]
            display_name = rec["display"]
        else:
            db_msg = rec_or_msg
            display_name = db_msg.name
        if self._dbc_watch_ids and msg.arbitration_id not in self._dbc_watch_ids:
            return
        try:
            decoded = db_msg.decode(msg.data, decode_choices=False)
        except Exception:
            return

        parent = self._msg_items.get(msg.arbitration_id)
        if parent is None:
            parent = QTreeWidgetItem([display_name, "", "", ts, rel, "", ""])
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
                prev_val = self._prev_sig_values.get(key, "")
                # Keep timestamp/relative columns moving in real-time, and
                # always refresh value to avoid stale-looking rows.
                item.setText(1, val_str)
                item.setText(2, unit)
                item.setText(3, ts)
                item.setText(4, rel)
                item.setText(5, min_str)
                item.setText(6, max_str)
                if prev_val != val_str:
                    self._highlight_signal_item(key, item)
                self._prev_sig_values[key] = val_str

            if msg.arbitration_id in self._dbc_watch_ids:
                self._append_dbc_history(ts, rel, db_msg.name, sig_name, val_str)

            self._evaluate_signal_triggers(display_name, sig_name, val_str, msg)

    def _add_dbc_send_card_prompted(self) -> None:
        if not self._dbc_files:
            QMessageBox.information(self, "Add Message Card", "Load at least one DBC first.")
            return
        selected_file = self._prompt_select_from_list(
            title="Select DBC",
            label="Choose which DBC file to use for this message card:",
            items=[p.name for p in self._dbc_files],
            multi_select=False,
        )
        if not selected_file:
            return
        file_name = selected_file[0]
        messages = sorted(
            rec["display"]
            for rec in self._dbc_records_by_display.values()
            if rec["file"].name == file_name
        )
        if not messages:
            QMessageBox.information(self, "Add Message Card", "No messages found in selected DBC.")
            return
        selected_msg = self._prompt_select_from_list(
            title="Select Message",
            label=f"Choose a message in {file_name}:",
            items=messages,
            multi_select=False,
        )
        if not selected_msg:
            return
        self._add_dbc_send_card(initial_message=selected_msg[0])

    def _add_dbc_send_card(self, initial_message: str | None = None) -> None:
        card_frame = QGroupBox("DBC Message")
        card_layout = QVBoxLayout(card_frame)
        head = QHBoxLayout()
        msg_combo = QComboBox()
        msg_combo.setMinimumWidth(220)
        periodic_check = QCheckBox("Periodic")
        period_ms = QLineEdit("100")
        period_ms.setMaximumWidth(80)
        toggle_btn = QPushButton("Collapse")
        send_btn = QPushButton("Send")
        remove_btn = QPushButton("X")
        remove_btn.setMaximumWidth(28)
        head.addWidget(QLabel("Message:"))
        head.addWidget(msg_combo, 1)
        head.addWidget(periodic_check)
        head.addWidget(QLabel("ms:"))
        head.addWidget(period_ms)
        head.addWidget(toggle_btn)
        head.addWidget(send_btn)
        head.addWidget(remove_btn)
        card_layout.addLayout(head)

        signal_widget = QWidget()
        signal_form = QFormLayout(signal_widget)
        card_layout.addWidget(signal_widget)

        card = {
            "frame": card_frame,
            "msg_combo": msg_combo,
            "periodic_check": periodic_check,
            "period_ms": period_ms,
            "send_btn": send_btn,
            "toggle_btn": toggle_btn,
            "signal_widget": signal_widget,
            "signal_form": signal_form,
            "controls": {},
            "meta": {},
            "collapsed": False,
            "periodic_timer": None,
        }
        self._send_cards.append(card)
        self.dbc_send_cards_layout.insertWidget(max(0, self.dbc_send_cards_layout.count() - 1), card_frame)
        msg_combo.currentTextChanged.connect(lambda name, c=card: self._on_dbc_send_card_change(c, name))
        send_btn.clicked.connect(lambda _=False, c=card: self._send_dbc_card(c))
        toggle_btn.clicked.connect(lambda _=False, c=card: self._toggle_dbc_send_card(c))
        remove_btn.clicked.connect(lambda _=False, c=card: self._remove_dbc_send_card(c))
        periodic_check.toggled.connect(lambda checked, c=card: self._toggle_dbc_card_periodic(c, checked))
        self._refresh_send_card_message_lists()
        if initial_message:
            card["msg_combo"].setCurrentText(initial_message)
            self._on_dbc_send_card_change(card, initial_message)
        self._set_send_cards_enabled(self.backend.is_connected and bool(self._dbc_records_by_display))

    def _remove_dbc_send_card(self, card: dict) -> None:
        self._stop_dbc_card_periodic(card)
        if card in self._send_cards:
            self._send_cards.remove(card)
        card["frame"].deleteLater()

    def _toggle_dbc_send_card(self, card: dict) -> None:
        card["collapsed"] = not card["collapsed"]
        card["signal_widget"].setVisible(not card["collapsed"])
        card["toggle_btn"].setText("Expand" if card["collapsed"] else "Collapse")

    def _refresh_send_card_message_lists(self) -> None:
        names = sorted(self._dbc_records_by_display) if self._dbc_records_by_display else []
        for card in self._send_cards:
            combo = card["msg_combo"]
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if current and current in names:
                combo.setCurrentText(current)
            elif names:
                combo.setCurrentText(names[0])
            combo.blockSignals(False)
            self._set_combo_search_items(combo, names)
            self._on_dbc_send_card_change(card, combo.currentText())

    def _on_dbc_send_card_change(self, card: dict, msg_name: str) -> None:
        while card["signal_form"].rowCount():
            card["signal_form"].removeRow(0)
        card["controls"].clear()
        card["meta"].clear()
        if not self._dbc_records_by_display or not msg_name:
            return
        rec = self._dbc_records_by_display.get(msg_name)
        if rec is None:
            return
        db_msg = rec["msg"]
        for sig in sorted(db_msg.signals, key=lambda s: s.name):
            unit = sig.unit or ""
            comment = sig.comment if isinstance(sig.comment, str) else ""
            desc = comment.strip()
            suffix = f" [{unit}]" if unit else ""
            label_text = f"{sig.name}{suffix}"
            if sig.choices:
                ctrl = QComboBox()
                ctrl.addItems([str(v) for v in sig.choices.values()])
                card["meta"][sig.name] = {
                    "is_enum": True,
                    "choices": sig.choices,
                    "unit": unit,
                    "description": desc,
                }
            else:
                ctrl = QLineEdit(str(sig.minimum if sig.minimum is not None else 0))
                card["meta"][sig.name] = {
                    "is_enum": False,
                    "min": sig.minimum,
                    "max": sig.maximum,
                    "unit": unit,
                    "description": desc,
                }
            card["controls"][sig.name] = ctrl
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(ctrl)
            unit_lbl = QLabel(unit)
            unit_lbl.setMinimumWidth(48)
            unit_lbl.setStyleSheet("color: #5f6b7a;")
            row_layout.addWidget(unit_lbl)
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color: #5f6b7a;")
            row_layout.addWidget(desc_lbl, 1)
            card["signal_form"].addRow(f"{label_text}:", row_widget)

    def _send_raw_message(self) -> bool:
        if not self.backend.is_connected:
            QMessageBox.critical(self, "Send Error", "Not connected to CAN bus.")
            return False
        try:
            arb_id = int(self.send_raw_id.text().strip(), 16)
        except ValueError:
            QMessageBox.critical(self, "Send Error", "Arb ID must be hex.")
            return False
        data = []
        for token in self.send_raw_data.text().strip().split():
            try:
                b = int(token, 16)
            except ValueError:
                QMessageBox.critical(self, "Send Error", f"Invalid byte: {token}")
                return False
            if b < 0 or b > 255:
                QMessageBox.critical(self, "Send Error", f"Byte out of range: {token}")
                return False
            data.append(b)
        if len(data) > 8:
            QMessageBox.critical(self, "Send Error", "Classic CAN data must be at most 8 bytes.")
            return False
        ok, msg = self.backend.send_message(
            can.Message(arbitration_id=arb_id, data=bytes(data), is_extended_id=self.send_raw_ext.isChecked())
        )
        if not ok:
            QMessageBox.critical(self, "Send Error", msg)
            return False
        self.status.showMessage("Raw frame sent.")
        return True

    def _send_dbc_card(self, card: dict) -> bool:
        if not self.backend.is_connected or not self._dbc_records_by_display:
            QMessageBox.critical(self, "Send Error", "Connect bus and load DBC first.")
            return False
        msg_name = card["msg_combo"].currentText().strip()
        if not msg_name:
            QMessageBox.critical(self, "Send Error", "Select a DBC message.")
            return False
        rec = self._dbc_records_by_display.get(msg_name)
        if rec is None:
            QMessageBox.critical(self, "Send Error", "Selected DBC message is no longer available.")
            return False
        db_msg = rec["msg"]
        sig_data: dict[str, int | float] = {}
        for sig in db_msg.signals:
            meta = card["meta"].get(sig.name)
            ctrl = card["controls"].get(sig.name)
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
            return False
        ok, msg = self.backend.send_message(
            can.Message(arbitration_id=db_msg.frame_id, data=data, is_extended_id=db_msg.is_extended_frame)
        )
        if not ok:
            QMessageBox.critical(self, "Send Error", msg)
            return False
        self.status.showMessage(f"DBC message sent: {msg_name}")
        return True

    def _toggle_raw_periodic_send(self, checked: bool) -> None:
        if checked:
            self._schedule_raw_periodic_send()
        else:
            self._stop_raw_periodic_send()

    def _schedule_raw_periodic_send(self) -> None:
        if not self.send_raw_periodic.isChecked():
            return
        if self._raw_periodic_timer is None:
            self._raw_periodic_timer = QTimer(self)
            self._raw_periodic_timer.timeout.connect(self._raw_periodic_tick)
        try:
            interval = max(1, int(self.send_raw_period_ms.text().strip()))
        except ValueError:
            interval = 100
            self.send_raw_period_ms.setText("100")
        self._raw_periodic_timer.start(interval)

    def _raw_periodic_tick(self) -> None:
        if not self.send_raw_periodic.isChecked():
            self._stop_raw_periodic_send()
            return
        if not self._send_raw_message():
            self.send_raw_periodic.setChecked(False)
            self._stop_raw_periodic_send()

    def _stop_raw_periodic_send(self) -> None:
        if self._raw_periodic_timer is not None:
            self._raw_periodic_timer.stop()

    def _toggle_dbc_card_periodic(self, card: dict, checked: bool) -> None:
        if checked:
            self._schedule_dbc_card_periodic(card)
        else:
            self._stop_dbc_card_periodic(card)

    def _schedule_dbc_card_periodic(self, card: dict) -> None:
        if not card["periodic_check"].isChecked():
            return
        timer = card.get("periodic_timer")
        if timer is None:
            timer = QTimer(self)
            timer.timeout.connect(lambda c=card: self._dbc_card_periodic_tick(c))
            card["periodic_timer"] = timer
        try:
            interval = max(1, int(card["period_ms"].text().strip()))
        except ValueError:
            interval = 100
            card["period_ms"].setText("100")
        timer.start(interval)

    def _dbc_card_periodic_tick(self, card: dict) -> None:
        if not card["periodic_check"].isChecked():
            self._stop_dbc_card_periodic(card)
            return
        if not self._send_dbc_card(card):
            card["periodic_check"].setChecked(False)
            self._stop_dbc_card_periodic(card)

    def _stop_dbc_card_periodic(self, card: dict) -> None:
        timer = card.get("periodic_timer")
        if timer is not None:
            timer.stop()

    def _set_send_cards_enabled(self, enabled: bool) -> None:
        for card in self._send_cards:
            card["send_btn"].setEnabled(enabled)
            card["periodic_check"].setEnabled(enabled)

    def _toggle_logging(self) -> None:
        if self.log_writer is None:
            self._start_logging()
        else:
            self._stop_logging()

    def _start_logging(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save CAN Trace", "", "BLF files (*.blf);;CSV files (*.csv)"
        )
        if not filename:
            return
        if "." not in Path(filename).name:
            filename = f"{filename}.blf"
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
        if self.replay_table.rowCount():
            self.replay_table.selectRow(0)
        self._update_replay_decode_view()

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
        self._plot_all_signals.clear()
        self.plot_signal_list.clear()
        if not self._dbc_records_by_display:
            return
        for rec in sorted(self._dbc_records_by_display.values(), key=lambda r: r["display"]):
            msg = rec["msg"]
            for sig in sorted(msg.signals, key=lambda s: s.name):
                if not sig.choices:
                    self._plot_all_signals.append(f"{rec['display']}.{sig.name}")
        self._filter_plot_signal_list()

    def _filter_plot_signal_list(self) -> None:
        if not _MATPLOTLIB_AVAILABLE:
            return
        self.plot_signal_list.clear()
        query = self.plot_signal_search.text().strip().lower() if hasattr(self, "plot_signal_search") else ""
        for name in self._plot_all_signals:
            if self._matches_query(name, query):
                self.plot_signal_list.addItem(name)

    def _set_combo_search_items(self, combo: QComboBox, items: list[str]) -> None:
        combo.setEditable(True)
        completer = combo.completer()
        if completer is None:
            completer = QCompleter(combo)
            combo.setCompleter(completer)
        model = QStringListModel(items, completer)
        completer.setModel(model)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setProperty("_all_search_items", items)
        if combo.lineEdit() is not None and not combo.property("_wildcard_search_bound"):
            combo.lineEdit().textEdited.connect(lambda text, c=combo: self._update_combo_suggestions(c, text))
            combo.setProperty("_wildcard_search_bound", True)
        self._update_combo_suggestions(combo, combo.currentText())

    def _update_combo_suggestions(self, combo: QComboBox, query: str) -> None:
        all_items = combo.property("_all_search_items")
        if not isinstance(all_items, list):
            return
        matches = [item for item in all_items if self._matches_query(item, query)]
        if not matches:
            matches = all_items
        completer = combo.completer()
        if completer is None:
            return
        model = QStringListModel(matches, completer)
        completer.setModel(model)

    def _matches_query(self, candidate: str, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return True
        text = candidate.lower()
        tokens = [tok for tok in q.replace(",", " ").split() if tok]
        for token in tokens:
            if "*" in token or "?" in token:
                if not fnmatch.fnmatch(text, token):
                    return False
            elif token not in text:
                return False
        return True

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

    def _add_watch_message(self) -> None:
        msg_name = self.watch_msg_combo.currentText().strip()
        if not msg_name:
            return
        arb_id = self._dbc_watch_name_to_id.get(msg_name)
        if arb_id is None or arb_id in self._dbc_watch_ids:
            return
        self._dbc_watch_ids.add(arb_id)
        self.watch_list.addItem(msg_name)
        self._prune_symbolic_to_watch()

    def _clear_watch_messages(self) -> None:
        self._dbc_watch_ids.clear()
        self.watch_list.clear()
        self.sym_tree.clear()
        self._msg_items.clear()
        self._signal_items.clear()
        self._signal_stats.clear()
        self._prev_sig_values.clear()
        self.dbc_history_table.setRowCount(0)

    def _prune_symbolic_to_watch(self) -> None:
        if not self._dbc_watch_ids:
            return
        for arb_id in list(self._msg_items):
            if arb_id not in self._dbc_watch_ids:
                item = self._msg_items.pop(arb_id)
                index = self.sym_tree.indexOfTopLevelItem(item)
                if index >= 0:
                    self.sym_tree.takeTopLevelItem(index)
                for key in [k for k in self._signal_items if k[0] == arb_id]:
                    self._signal_items.pop(key, None)
                    self._signal_stats.pop(key, None)
                    self._prev_sig_values.pop(key, None)

    def _append_dbc_history(self, ts: str, rel: str, msg_name: str, sig_name: str, value: str) -> None:
        idx = self.dbc_history_table.rowCount()
        self.dbc_history_table.insertRow(idx)
        for col, text in enumerate([ts, rel, msg_name, sig_name, value]):
            self.dbc_history_table.setItem(idx, col, QTableWidgetItem(text))
        if self.dbc_history_table.rowCount() > 5000:
            self.dbc_history_table.removeRow(0)
        self.dbc_history_table.scrollToBottom()

    def _highlight_signal_item(self, key: tuple[int, str], item: QTreeWidgetItem) -> None:
        for col in range(7):
            item.setBackground(col, QBrush(QColor("#fff2a8")))
        timer = self._signal_highlight_timers.pop(key, None)
        if timer is not None:
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda k=key, it=item: self._clear_signal_highlight(k, it))
        timer.start(2000)
        self._signal_highlight_timers[key] = timer

    def _clear_signal_highlight(self, key: tuple[int, str], item: QTreeWidgetItem) -> None:
        for col in range(7):
            item.setBackground(col, QBrush())
        self._signal_highlight_timers.pop(key, None)

    def _update_replay_decode_view(self) -> None:
        self.replay_decode_tree.clear()
        if not self._dbc_records_by_display:
            return
        selected = self.replay_table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        if row >= len(self._replay_messages):
            return
        msg = self._replay_messages[row]
        rec_or_msg = self._dbc_msg_by_id.get(msg.arbitration_id)
        if rec_or_msg is None:
            return
        if isinstance(rec_or_msg, dict):
            rec = rec_or_msg
            db_msg = rec["msg"]
            display_name = rec["display"]
        else:
            db_msg = rec_or_msg
            display_name = db_msg.name
        root = QTreeWidgetItem([display_name, "", ""])
        self.replay_decode_tree.addTopLevelItem(root)
        try:
            decoded = db_msg.decode(msg.data, decode_choices=False)
        except Exception:
            return
        for sig_name, value in decoded.items():
            unit = self._dbc_signal_units.get(msg.arbitration_id, {}).get(sig_name, "")
            val_str = f"{value:.4g}" if isinstance(value, float) else str(value)
            root.addChild(QTreeWidgetItem([sig_name, val_str, unit]))
        root.setExpanded(True)

    def _add_trigger_row(self) -> None:
        row = self.trigger_table.rowCount()
        self.trigger_table.insertRow(row)
        type_combo = QComboBox()
        type_combo.addItems(["Signal", "Raw"])
        source_combo = QComboBox()
        source_combo.setEditable(True)
        signal_combo = QComboBox()
        unit_label = QLabel("")
        op_combo = QComboBox()
        op_combo.addItems(["==", "!=", ">", ">=", "<", "<=", "rising", "falling", "changed"])
        value_combo = QComboBox()
        value_combo.setEditable(True)
        bytes_edit = QLineEdit("256")
        base_edit = QLineEdit("trigger_capture")
        use_master = QCheckBox()
        use_master.setChecked(True)
        out_dir = QLineEdit(str(Path.cwd()))
        out_format = QComboBox()
        out_format.addItems(["BLF", "ASC", "CSV"])
        enabled = QCheckBox()
        enabled.setChecked(True)

        self.trigger_table.setCellWidget(row, 0, type_combo)
        self.trigger_table.setCellWidget(row, 1, source_combo)
        self.trigger_table.setCellWidget(row, 2, signal_combo)
        self.trigger_table.setCellWidget(row, 3, op_combo)
        self.trigger_table.setCellWidget(row, 4, unit_label)
        self.trigger_table.setCellWidget(row, 5, value_combo)
        self.trigger_table.setCellWidget(row, 6, bytes_edit)
        self.trigger_table.setCellWidget(row, 7, base_edit)
        self.trigger_table.setCellWidget(row, 8, use_master)
        self.trigger_table.setCellWidget(row, 9, out_dir)
        self.trigger_table.setCellWidget(row, 10, out_format)
        self.trigger_table.setCellWidget(row, 11, enabled)

        row_data = {
            "type": type_combo,
            "source": source_combo,
            "signal": signal_combo,
            "unit": unit_label,
            "op": op_combo,
            "value": value_combo,
            "bytes": bytes_edit,
            "base": base_edit,
            "use_master": use_master,
            "out_dir": out_dir,
            "out_format": out_format,
            "enabled": enabled,
            "enum_choices": None,
        }
        self._trigger_rows.append(row_data)
        type_combo.currentTextChanged.connect(lambda _: self._sync_trigger_row_widgets(row_data))
        source_combo.currentTextChanged.connect(lambda _: self._sync_trigger_row_widgets(row_data))
        signal_combo.currentTextChanged.connect(lambda _: self._sync_trigger_row_widgets(row_data))
        use_master.toggled.connect(lambda _: self._sync_trigger_row_widgets(row_data))
        self._refresh_trigger_sources()
        self._sync_trigger_row_widgets(row_data)

    def _remove_selected_trigger_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.trigger_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.trigger_table.removeRow(row)
            if row < len(self._trigger_rows):
                self._trigger_rows.pop(row)
        self._trigger_match_state.clear()
        self._prev_trigger_values.clear()

    def _refresh_trigger_sources(self) -> None:
        names = sorted(self._dbc_records_by_display)
        signal_keys = sorted(self._signal_key_to_source_signal)
        for row in self._trigger_rows:
            source_combo = row["source"]
            current_source = source_combo.currentText()
            source_combo.blockSignals(True)
            if row["type"].currentText() == "Signal":
                options = names + signal_keys
                source_combo.clear()
                source_combo.addItems(options)
                if current_source in options:
                    source_combo.setCurrentText(current_source)
                elif options:
                    source_combo.setCurrentText(options[0])
                self._set_combo_search_items(source_combo, options)
            else:
                source_combo.clear()
                source_combo.addItems(names)
                self._set_combo_search_items(source_combo, names)
            source_combo.blockSignals(False)
            self._sync_trigger_row_widgets(row)

    def _sync_trigger_row_widgets(self, row_data: dict) -> None:
        is_signal = row_data["type"].currentText() == "Signal"
        row_data["signal"].setEnabled(is_signal)
        row_data["enum_choices"] = None
        row_data["unit"].setText("")
        if is_signal:
            source_text = row_data["source"].currentText().strip()
            pending_signal = ""
            if source_text in self._signal_key_to_source_signal:
                display, pending_signal = self._signal_key_to_source_signal[source_text]
                if row_data["source"].currentText() != display:
                    row_data["source"].setCurrentText(display)
            display = row_data["source"].currentText().strip()
            sig_names: list[str] = []
            rec = self._dbc_records_by_display.get(display)
            if rec is not None:
                sig_names = sorted(sig.name for sig in rec["msg"].signals)
            current_sig = row_data["signal"].currentText()
            row_data["signal"].blockSignals(True)
            row_data["signal"].clear()
            row_data["signal"].addItems(sig_names)
            if pending_signal and pending_signal in sig_names:
                row_data["signal"].setCurrentText(pending_signal)
            elif current_sig in sig_names:
                row_data["signal"].setCurrentText(current_sig)
            row_data["signal"].blockSignals(False)
            self._set_combo_search_items(row_data["signal"], sig_names)
            selected_sig = row_data["signal"].currentText()
            if rec is not None and selected_sig:
                sig_def = next((s for s in rec["msg"].signals if s.name == selected_sig), None)
                if sig_def is not None:
                    row_data["unit"].setText(sig_def.unit or "")
                    value_box = row_data["value"]
                    value_box.blockSignals(True)
                    current_value = value_box.currentText()
                    if sig_def.choices:
                        row_data["enum_choices"] = {str(v): int(k) for k, v in sig_def.choices.items()}
                        value_box.clear()
                        value_box.addItems(sorted(row_data["enum_choices"]))
                        value_box.setEditable(False)
                        if current_value in row_data["enum_choices"]:
                            value_box.setCurrentText(current_value)
                    else:
                        value_box.clear()
                        value_box.setEditable(True)
                        if current_value:
                            value_box.setEditText(current_value)
                    value_box.blockSignals(False)
        else:
            row_data["source"].setEditable(True)
            row_data["signal"].clear()
            row_data["value"].blockSignals(True)
            row_data["value"].clear()
            row_data["value"].setEditable(True)
            row_data["value"].blockSignals(False)
        use_master = row_data["use_master"].isChecked()
        row_data["out_dir"].setEnabled(not use_master)
        row_data["out_format"].setEnabled(not use_master)

    def _parse_numeric(self, value: str) -> float | None:
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        try:
            return float(int(text, 0))
        except ValueError:
            return None

    def _compare_values(self, op: str, current: float, previous: float | None, target: float | None) -> bool:
        if op == "rising":
            return previous is not None and current > previous
        if op == "falling":
            return previous is not None and current < previous
        if op == "changed":
            return previous is not None and current != previous
        if target is None:
            return False
        if op == "==":
            return current == target
        if op == "!=":
            return current != target
        if op == ">":
            return current > target
        if op == ">=":
            return current >= target
        if op == "<":
            return current < target
        if op == "<=":
            return current <= target
        return False

    def _active_trigger_rows(self) -> list[tuple[int, dict]]:
        return [(idx, row) for idx, row in enumerate(self._trigger_rows) if row["enabled"].isChecked()]

    def _evaluate_raw_triggers(self, msg: can.Message) -> None:
        for row_index, row in self._active_trigger_rows():
            if row["type"].currentText() != "Raw":
                continue
            target = row["source"].currentText().strip()
            if not target:
                continue
            try:
                target_id = int(target, 16)
            except ValueError:
                continue
            if msg.arbitration_id != target_id:
                continue
            payload_num = float(int.from_bytes(bytes(msg.data) or b"\x00", byteorder="big"))
            target_val = self._parse_numeric(row["value"].currentText())
            op = row["op"].currentText()
            previous = self._prev_trigger_values.get(row_index)
            matched = self._compare_values(op, payload_num, previous, target_val)
            self._prev_trigger_values[row_index] = payload_num
            was_matched = self._trigger_match_state.get(row_index, False)
            if matched and not was_matched:
                self._start_trigger_capture(row, msg)
            self._trigger_match_state[row_index] = matched

    def _evaluate_signal_triggers(self, msg_name: str, signal_name: str, value: str, msg: can.Message) -> None:
        current_numeric = self._parse_numeric(value)
        if current_numeric is None:
            return
        for row_index, row in self._active_trigger_rows():
            if row["type"].currentText() != "Signal":
                continue
            target_msg = row["source"].currentText().strip()
            target_sig = row["signal"].currentText().strip()
            if not target_msg or not target_sig:
                continue
            if target_msg != msg_name or target_sig != signal_name:
                continue
            target_val: float | None
            if row["enum_choices"]:
                selected = row["value"].currentText()
                if selected in row["enum_choices"]:
                    target_val = float(row["enum_choices"][selected])
                else:
                    target_val = None
            else:
                target_val = self._parse_numeric(row["value"].currentText())
            op = row["op"].currentText()
            prev_key = 10_000 + row_index
            previous = self._prev_trigger_values.get(prev_key)
            matched = self._compare_values(op, current_numeric, previous, target_val)
            self._prev_trigger_values[prev_key] = current_numeric
            was_matched = self._trigger_match_state.get(prev_key, False)
            if matched and not was_matched:
                self._start_trigger_capture(row, msg)
            self._trigger_match_state[prev_key] = matched

    def _resolve_trigger_output(self, row_data: dict) -> tuple[Path, str]:
        use_master = row_data["use_master"].isChecked()
        if use_master:
            out_dir = Path(self.trigger_output_dir.text().strip() or ".")
            fmt = self.trigger_output_format.currentText().strip().upper()
        else:
            out_dir = Path(row_data["out_dir"].text().strip() or ".")
            fmt = row_data["out_format"].currentText().strip().upper()
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, fmt

    def _start_trigger_capture(self, row_data: dict, first_msg: can.Message) -> None:
        try:
            remaining = max(1, int(row_data["bytes"].text().strip()))
        except ValueError:
            remaining = 256
        base = row_data["base"].text().strip() or "trigger_capture"
        out_dir, fmt = self._resolve_trigger_output(row_data)
        idx = self._capture_index_by_base.get(base, 0) + 1
        ext = fmt.lower()
        while (out_dir / f"{base}_{idx:04d}.{ext}").exists():
            idx += 1
        self._capture_index_by_base[base] = idx
        path = out_dir / f"{base}_{idx:04d}.{ext}"
        capture = {"remaining": remaining, "path": path, "format": fmt}
        if fmt == "BLF":
            capture["writer"] = can.BLFWriter(str(path))
        elif fmt == "ASC":
            capture["writer"] = can.ASCWriter(str(path))
        else:
            fh = path.open("w", newline="")
            writer = csv.writer(fh)
            writer.writerow(["Timestamp", "Arb ID", "Frame", "DLC", "Data"])
            capture["fh"] = fh
            capture["writer"] = writer
        self._active_captures.append(capture)
        self._feed_active_captures(first_msg)
        self._diag_log(f"Trigger capture started: {path} ({remaining} bytes target)")

    def _feed_active_captures(self, msg: can.Message) -> None:
        if not self._active_captures:
            return
        keep: list[dict] = []
        for capture in self._active_captures:
            data_bytes = bytes(msg.data)
            take = min(capture["remaining"], len(data_bytes))
            if take > 0:
                writer = capture["writer"]
                if capture["format"] == "CSV":
                    arb = f"0x{msg.arbitration_id:08X}" if msg.is_extended_id else f"0x{msg.arbitration_id:03X}"
                    frame = "EXT" if msg.is_extended_id else "STD"
                    data = " ".join(f"{b:02X}" for b in data_bytes)
                    writer.writerow([f"{msg.timestamp:.6f}", arb, frame, msg.dlc, data])
                elif hasattr(writer, "on_message_received"):
                    writer.on_message_received(msg)
                capture["remaining"] -= take
            if capture["remaining"] <= 0:
                writer = capture["writer"]
                if hasattr(writer, "stop"):
                    writer.stop()
                if "fh" in capture:
                    capture["fh"].close()
                self._diag_log(f"Trigger capture complete: {capture['path']}")
            else:
                keep.append(capture)
        self._active_captures = keep

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
        self._bus_bits_window.clear()
        self.dbc_history_table.setRowCount(0)
        self.replay_decode_tree.clear()
        self._trigger_match_state.clear()
        self._prev_trigger_values.clear()
        self.message_count = 0
        self.error_count = 0
        self.backend.dropped_count = 0
        self._trace_start = None
        self._refresh_stats()
        self.status.showMessage("Cleared monitor views and counters.")
        self._diag_log("Cleared monitor views and counters")

    def _refresh_stats(self) -> None:
        now = time.time()
        while self._bus_bits_window and (now - self._bus_bits_window[0][0]) > 1.0:
            self._bus_bits_window.popleft()
        bits_last_sec = sum(bits for _, bits in self._bus_bits_window)
        bitrate = max(1, self._current_bitrate)
        bus_load = min(100.0, (bits_last_sec / bitrate) * 100.0)
        self.msg_count_label.setText(f"Messages: {self.message_count}")
        self.err_count_label.setText(f"Errors: {self.error_count}")
        self.bus_load_label.setText(f"Bus load: {bus_load:.1f}%")
        self.drop_count_label.setText(
            f"Dropped: {self.backend.dropped_count:,}" if self.backend.dropped_count else ""
        )

    def _diag_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.diag_text.append(f"[{ts}] {message}")
        LOGGER.info(message)
