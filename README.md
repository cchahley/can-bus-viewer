# CAN Bus Viewer (Qt)

Qt-only CAN monitor, decode, send, replay, and trigger capture tool.

## Version

Current release version: `0.1.0`

## Run

```bash
pip install python-can cantools pyserial pyside6 matplotlib
python can_viewer_qt.py
```

`python can_viewer.py` is a compatibility shim that launches the same Qt app.

## Key Features

- Multiple DBC files:
  - `Add DBC` supports multi-select
  - loaded DBC file list with `Remove DBC`
  - merged message registry (latest loaded DBC overrides frame-ID conflicts)
- DBC decode/watch:
  - watch selected DBC messages only
  - full watched signal history table
  - value-change highlighting
- Send:
  - raw send
  - multiple DBC send cards
  - per-card collapse/expand
- Replay:
  - trace table + side DBC decode panel
- Bus load:
  - rolling 1-second bus-load percentage
- Triggers:
  - source from loaded DBC messages/signals
  - operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `rising`, `falling`, `changed`
  - capture `N` bytes after trigger
  - master output directory/format (`CSV`, `ASC`, `BLF`)
  - per-trigger `Use Master` toggle with per-trigger overrides

## Error Logs

- Runtime and uncaught exceptions are written to a daily file in the app working directory:
  - `can_viewer_qt_YYYYMMDD.log`
- Share that log file for debugging if a UI action fails.

## Executable Build

```bash
pip install pyinstaller
pyinstaller can_viewer.spec
```

Output: `dist/can_viewer_qt.exe` (single-file build)

`can_viewer.spec` includes CAN backend hidden imports (`pcan`, `vector`, `slcan`, `pyserial`) for improved dongle detection in packaged builds.

## CI/CD

- CI: [.github/workflows/ci.yml](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/.github/workflows/ci.yml)
  - lint, type check, Qt tests
- Release: [.github/workflows/release.yml](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/.github/workflows/release.yml)
  - Windows build artifact on tag (`v*`) or manual dispatch
