"""
CANViewer application class.

This module contains only the class definition and ``__init__`` (state
initialisation).  All methods live in the mixin modules under ``can_viewer/mixins/``.
See ``ARCHITECTURE.md`` for the complete module map and data-flow diagram.

Mixin inheritance order (left-to-right follows Python MRO):
  UIBuilderMixin       → _build_ui, _build_send_panel
  ConnectionMixin      → _scan_channels, _connect, _disconnect, _clear
  ReaderMixin          → _reader, _poll_queue, _insert_raw_row
  MessageDisplayMixin  → _show_message, _load_dbc, _decode_and_display
  SendMixin            → raw/DBC send rows, periodic, mode toggle
  LoggingMixin         → _start_logging, _stop_logging
  FilterMixin          → _on_filter_change, _passes_filter
  ThemeMixin           → _toggle_dark_mode, _apply_theme
  PlotMixin            → _open_plot_window, signal plot refresh
  ReplayMixin          → _open_replay_window, trace import/replay
"""
import collections
import queue
import tkinter as tk
from tkinter import ttk

from .mixins.ui_builder      import UIBuilderMixin
from .mixins.connection      import ConnectionMixin
from .mixins.reader          import ReaderMixin
from .mixins.message_display import MessageDisplayMixin
from .mixins.send            import SendMixin
from .mixins.log_writer      import LoggingMixin
from .mixins.filtering       import FilterMixin
from .mixins.theme           import ThemeMixin
from .mixins.plot            import PlotMixin
from .mixins.replay          import ReplayMixin
from .mixins.diag            import DiagMixin


class CANViewer(
    UIBuilderMixin,
    ConnectionMixin,
    ReaderMixin,
    MessageDisplayMixin,
    SendMixin,
    LoggingMixin,
    FilterMixin,
    ThemeMixin,
    PlotMixin,
    ReplayMixin,
    DiagMixin,
):
    """CAN Bus Viewer — main application class.

    Composes ten mixin classes, each responsible for one functional area.
    ``__init__`` sets up all shared state (instance variables), then calls
    ``_build_ui``, ``_scan_channels``, and starts the two recurring timers
    (``_poll_queue`` and ``_update_stats_labels``).

    Parameters
    ----------
    root : tk.Tk
        The root tkinter window created by ``main()``.
    """

    _MAX_RAW_ROWS  = 2000   # max rows kept visible in the raw tree
    _MAX_PER_CYCLE = 150    # max messages processed per 10 ms poll cycle

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CAN Bus Viewer")
        self.root.geometry("1400x920")
        self.root.minsize(900, 620)

        # ── Bus and connection state ──────────────────────────────────────────
        self.bus = None
        self.running = False
        self.message_queue: queue.Queue = queue.Queue(maxsize=10_000)
        self.message_count: int = 0
        self.error_count: int = 0
        self._dropped_count: int = 0   # messages silently dropped (queue full)

        # ── Logging state ─────────────────────────────────────────────────────
        self.log_writer = None
        self.log_file = None
        self.log_format = None

        # ── DBC / symbolic tree state ─────────────────────────────────────────
        self.db = None
        self._signal_iids: dict = {}    # (arb_id, sig_name) → treeview iid
        self._msg_iids: dict = {}       # arb_id → message parent row iid
        self._trace_start = None   # float | None; no annotation avoids mixin inference conflict
        self._send_rows: list = []       # raw send rows
        self._dbc_send_rows: list = []   # DBC send rows

        # ── Signal statistics ─────────────────────────────────────────────────
        self._signal_stats: dict = {}        # (arb_id, sig_name) → {min, max, count}
        self._prev_sig_values: dict = {}     # (arb_id, sig_name) → last val_str
        self._highlight_after_ids: dict = {} # treeview iid → after-job id

        # ── Signal plot ───────────────────────────────────────────────────────
        self._plot_buffers: dict = {}        # "Msg.Sig" → deque of float values
        self._plot_win = None
        self._plot_active_signals: list = []

        # ── Raw message buffer and filter ─────────────────────────────────────
        self._filter_var = tk.StringVar()
        self._raw_buffer: collections.deque = collections.deque(maxlen=5000)
        self._raw_tree_count: int = 0        # rows currently in self.tree
        self._raw_iid_deque: collections.deque = collections.deque()  # O(1) eviction
        self._filter_tokens: list = []       # cached tokens — updated only on filter change
        self._msg_name_cache: dict = {}      # frame_id → msg name (built on DBC load)
        self._drop_var = tk.StringVar(value="")   # toolbar label, set by stats timer

        # ── Trace replay ──────────────────────────────────────────────────────
        self._replay_messages: list = []
        self._replay_speed_var = tk.StringVar(value="1.0")

        # ── Dark mode ─────────────────────────────────────────────────────────
        self._dark_mode = False
        self._original_theme = ttk.Style().theme_use()

        # ── Start up ──────────────────────────────────────────────────────────
        self._build_ui()
        self._setup_diag()       # rotating log file; must come after _build_ui
        self._scan_channels()
        self._poll_queue()
        self._update_stats_labels()
