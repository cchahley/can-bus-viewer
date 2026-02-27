# Architecture

## Package Map

```
can_viewer.py                  ← thin entry-point shim (13 lines)
                                 "from can_viewer import main; main()"

can_viewer/                    ← application package
├── __init__.py                ← exports CANViewer + main()
├── app.py                     ← CANViewer class definition + __init__ (state only)
├── utils.py                   ← _silence_stderr() context manager
└── mixins/
    ├── __init__.py
    ├── ui_builder.py          ← _build_ui, _build_send_panel, canvas helpers
    ├── connection.py          ← _scan_channels, _connect, _disconnect, _clear
    ├── reader.py              ← _reader, _poll_queue, _insert_raw_row, stats timer
    ├── message_display.py     ← _show_message, _load_dbc, _decode_and_display
    ├── send.py                ← raw/DBC send rows, periodic transmit, mode toggle
    ├── log_writer.py          ← _toggle_logging, _start_logging, _stop_logging
    ├── filtering.py           ← _on_filter_change, _passes_filter, token cache
    ├── theme.py               ← _toggle_dark_mode, _apply_theme
    ├── plot.py                ← signal plot window + live refresh loop
    └── replay.py              ← trace import/replay window + background thread

test_can_viewer.py             ← 37 pytest unit tests
can_viewer.spec                ← PyInstaller spec (entry script = can_viewer.py shim)
.github/workflows/ci.yml       ← lint, type-check, test on every push/PR
```

---

## Mixin Inheritance

`CANViewer` is assembled by inheriting all ten mixins:

```python
class CANViewer(
    UIBuilderMixin,       # widget construction
    ConnectionMixin,      # bus open/close lifecycle
    ReaderMixin,          # background reader thread + GUI poll loop
    MessageDisplayMixin,  # raw + symbolic display, DBC loading
    SendMixin,            # message transmission (raw + DBC-driven)
    LoggingMixin,         # CSV file logging
    FilterMixin,          # real-time keyword filtering
    ThemeMixin,           # light / dark theme
    PlotMixin,            # matplotlib signal plot
    ReplayMixin,          # trace import and replay
):
```

All methods in every mixin share the same `self` at runtime — Python's MRO resolves
cross-mixin calls (e.g., `SendMixin` calling `self._cancel_all_periodic()` which is
also defined in `SendMixin`, or `ConnectionMixin` calling `self._stop_logging()` from
`LoggingMixin`) through normal attribute lookup.

> **Why mixins instead of composition?**
> Every method accesses shared tkinter widgets and state variables stored on `self`
> (e.g., `self.tree`, `self.bus`, `self.message_queue`).  Mixins let the class be
> split across files with zero refactoring of method bodies — no dependency injection,
> no inter-object references, no interface contracts needed.  The trade-off is that
> mixin methods are not independently instantiable, but for a single-window GUI
> application that trade-off is acceptable.

---

## Data Flow

```
Hardware / virtual bus
        │
        │  can.Message (via python-can)
        ▼
  _reader()  ──[daemon thread]──► message_queue (Queue, maxsize=10 000)
                                          │
                                          │  put_nowait() — drops on Full
                                          ▼
                               _poll_queue()  ──[tkinter after loop, 20 ms]──►
                                   │
                                   ├─► _insert_raw_row()   → raw Treeview
                                   │        (ring-buffer, max 2 000 rows)
                                   │
                                   ├─► _show_message()     → message_count / error_count
                                   │
                                   ├─► _decode_and_display()  (if DBC loaded)
                                   │        → symbolic Treeview (insert / update-in-place)
                                   │
                                   └─► _log_message()      (if logging active)
                                              → CSV via csv.writer
                                              → BLF via can.BLFWriter

                               _update_stats_labels()  ──[tkinter after, 200 ms]──►
                                   → count_var.set(), error_var.set()
```

---

## Key Design Decisions

### Bounded queue + throttled poll loop

`message_queue` has `maxsize=10_000`.  The reader thread uses `put_nowait()` and
silently drops messages when the queue is full rather than blocking.  This keeps the
reader thread running at wire speed even when the GUI is slow.

`_poll_queue` processes at most `_MAX_PER_CYCLE = 150` messages per 20 ms tick.
This bounds the worst-case GUI work per frame to ~150 Treeview insertions even on a
fully-loaded 1 Mbit/s bus (≈ 8 000 frames/s theoretical max).

### Ring-buffer raw tree

`_insert_raw_row` caps the raw Treeview at `_MAX_RAW_ROWS = 2000` rows.  When the
cap is reached the oldest row (first child of the tree root) is deleted before the
new row is inserted.  This prevents unbounded memory growth during long-running sessions.

### Cached filter tokens

`_filter_tokens` is a pre-split list of lowercase strings refreshed only when the
filter entry changes (`_on_filter_change`).  The hot-path check (`_passes_filter`)
iterates a Python list rather than re-splitting the filter string on every message.

### Cached DBC name lookup

`_msg_name_cache` is a `dict[int, str]` built once when a DBC is loaded, mapping
`frame_id → message_name`.  The raw-tree hot path uses this dict instead of calling
`db.get_message_by_frame_id()` on every received message.

### 200 ms stats label timer

Message and error counters are incremented on every received message but the
`StringVar` labels are only refreshed by a 200 ms repeating timer
(`_update_stats_labels`).  This eliminates two `StringVar.set()` calls per message
in the hot path — a significant saving at high message rates.

### `tag_configure("error")` moved to setup

The tkinter tag style for error frames is configured once in `_build_ui`.  Previously
it was called on every error frame in `_poll_queue`, which was wasteful because
`tag_configure` has non-trivial overhead when called thousands of times per second.

### `log_writer.py` naming

The mixin file is named `log_writer.py` rather than `logging.py` to avoid shadowing
Python's standard-library `logging` module, which is occasionally imported by
dependencies.
