# CAN Bus Viewer

![CI](https://github.com/YOUR_USERNAME/YOUR_REPO/actions/workflows/ci.yml/badge.svg)

A desktop GUI application for monitoring, decoding, and sending CAN bus messages.
Built with Python, [python-can](https://python-can.readthedocs.io/), and tkinter.

---

## Features

| Feature | Description |
|---|---|
| **Live monitoring** | Scrolling raw message table with Arb ID, DLC, data bytes, and timestamps |
| **DBC decoding** | Load a `.dbc` file to decode signals in a hierarchical symbolic tree |
| **Send panel** | Raw hex sends and DBC-driven card sends with configurable periodic transmit |
| **Logging** | One-click CSV logging; open the file in Excel or re-import for replay |
| **Trace replay** | Import a saved CSV, ASC, or BLF trace and replay it at adjustable speed |
| **Signal plot** | Live matplotlib plot of decoded signal values over time |
| **Filter** | Real-time keyword / hex-ID filter across both raw and symbolic views |
| **Dark mode** | Toggle between light and dark themes |
| **Statistics** | Message and error counters updated on a 200 ms timer |

---

## Requirements

- Python 3.11 or newer
- [python-can](https://pypi.org/project/python-can/) ≥ 4.0
- [cantools](https://pypi.org/project/cantools/) (for DBC decoding and DBC-driven sends)
- [matplotlib](https://pypi.org/project/matplotlib/) (optional — signal plot tab is hidden if not installed)

---

## Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO

# Install runtime dependencies
pip install python-can cantools matplotlib

# Run
python can_viewer.py

# Qt migration preview (Phase 6 monitor + send + replay/logging + plot + diagnostics preview)
pip install pyside6
python can_viewer_qt.py
```

---

## Hardware Support

| Interface | Notes |
|---|---|
| **PCAN** | Peak USB/PCI adapters — requires PEAK driver + `pip install python-can[pcan]` |
| **Vector** | Vector XL hardware — requires Vector driver + `pip install python-can[vector]` |
| **CANable / SLCAN** | USB-serial adapters in SLCAN firmware — requires `pip install pyserial` |
| **Virtual** | Software loopback — no hardware needed, good for testing |

---

## Usage

### Connect

1. Select **Interface** from the dropdown (PCAN / Vector / SLCAN / Virtual).
2. Click **Rescan** — available channels populate the **Channel** combobox.
3. Choose a **Bitrate** (default 500 000 bps).
4. Click **Connect**.

The status bar turns green and messages appear in the raw table immediately.

### DBC Decoding

Click **Load DBC…** and open a `.dbc` file.
Decoded signals appear in the **Symbolic** tree tab, grouped by message name.

### Sending Messages

Switch to the **Send** tab.

- **Raw mode** — fill in Arb ID (hex), DLC, and data bytes, then click **Send**.
  Tick **Periodic** and set an interval to transmit repeatedly.
- **DBC mode** — if a DBC is loaded, message cards appear.
  Edit signal values directly and click **Send** on the card.

### Logging

Click **Start Log** to begin recording to a timestamped CSV file.
Click **Stop Log** when done. The file can be replayed via **Replay…**.

### Trace Replay

Click **Replay…**, open a CSV/ASC/BLF file, set the speed multiplier, and click **Replay**.
Messages are sent on the currently connected bus.

### Signal Plot

Click **Plot…** (requires matplotlib).
Select signals from the list to overlay them on a live time-series chart.

### Filter

Type any text (message name, signal name, hex ID fragment) in the **Filter** box.
Both the raw and symbolic views update instantly.

---

## Building a Standalone .exe

```bash
pip install pyinstaller
pyinstaller can_viewer.spec
# Executable is at dist/can_viewer/can_viewer.exe
```

---

## Running Tests and Lint

```bash
pip install pytest ruff mypy
python -m pytest -q                        # tkinter + Qt tests (41 total)
python -m pytest test_can_viewer.py -v     # tkinter test suite
python -m pytest test_can_viewer_qt.py -v  # Qt preview tests (virtual CAN + DBC)
ruff check can_viewer/ can_viewer.py
mypy can_viewer/ --ignore-missing-imports
```

---

## Contributing

1. Fork and create a feature branch.
2. Make changes in the appropriate mixin module under `can_viewer/mixins/`.
3. Run tests and lint before opening a PR.
4. See [ARCHITECTURE.md](ARCHITECTURE.md) for a module map and design notes.

