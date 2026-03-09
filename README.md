# CAN Bus Viewer

This repo now contains:

- Legacy Python/Qt app (`can_viewer_qt.py`)
- Active C# / WinUI 3 migration app (`src/CanViewer.App`)

## Version

Current release version: `0.1.0`

## Run (Python/Qt)

```bash
pip install python-can cantools pyserial pyside6 matplotlib
python can_viewer_qt.py
```

`python can_viewer.py` is a compatibility shim that launches the same Qt app.

## Run (C# / WinUI 3)

```bash
dotnet run --project src/CanViewer.App/CanViewer.App.csproj
```

Current C# target framework: `net10.0-windows10.0.22621.0`

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

## C# WinUI 3 Migration Status

A migration scaffold now exists on branch `feature/csharp-winui3-port`:

- Solution: `CanBusViewer.sln`
- Core domain: `src/CanViewer.Core`
- Adapter layer: `src/CanViewer.Adapters`
- WinUI app shell: `src/CanViewer.App`
- Tests: `tests/CanViewer.Tests`

Current adapter status in scaffold:

- `virtual`: working loopback session
- `pcan`: live native adapter via `PCANBasic.dll` (`Initialize`/`Read`/`Write`)
- `vector`, `slcan`: interface scaffolds still pending native transport wiring

Current implemented C# functionality:

- WinUI app shell with dark theme + blue accents and multi-section workflow
- Interface selection/scanning (`pcan`, `vector`, `slcan`, `virtual`)
- Connect/disconnect and real-time frame ingest
- Raw table with bounded in-memory rows, headers, and optional auto-scroll
- Raw/Inspect render modes: `All frames` or `Latest per ID`, with `Pause`/`Play`
- Adaptive high-traffic rendering with live diagnostics (queue depth, render/decode stride, UI flush time, sampled count)
- Send tab with manual raw send + periodic send controls
- Symbolic DBC send cards (multiple cards, per-card periodic send)
- Decode section with DBC browse/add (multi-select), remove list, and signal decode rows
- Decode watch filters (watch selected DBC messages only)
- Inspect tab that always shows raw data plus symbolic summary when DBC matches
- Replay section (load/start/stop from CSV)
- Trigger section (add/remove trigger rules with live hit counters)
- Core replay CSV parser (`CanViewer.Core.Replay.CsvReplayParser`)
- Core trigger evaluator (`CanViewer.Core.Triggers.TriggerEvaluator`)
- Core DBC parser/decoder (`CanViewer.Core.Dbc`)

## PCAN Notes (C# App)

- Install PEAK PCAN-Basic / PCAN driver package so `PCANBasic.dll` is available.
- In app:
  - choose `Pcan`
  - click `Scan`
  - select channel like `PCAN_USBBUS1`
  - set bitrate (e.g. `500000` or `1000000`)
  - click `Connect`
- If `PCANBasic.dll` is missing, status text will show a clear error.

## DBC Workflow (C# App)

- Open `Decode` tab.
- Paste full `.dbc` path in `DBC file path`.
- Click `Add DBC`.
- Select an entry in the loaded DBC list and click `Remove Selected DBC` to unload it.
- Decoded rows will show message name + signal + physical value when frame IDs match loaded DBC messages.

Current test status:

- `dotnet test tests/CanViewer.Tests/CanViewer.Tests.csproj`
- Passing: 14 tests

## Hardware Validation Feedback Loop

For each hardware test run, capture:

1. Interface + channel + bitrate used
2. Observed ingest rate and UI responsiveness
3. Any dropped-frame spikes
4. Raw sample frames that looked incorrect
5. Repro steps

Then share those results so the next iteration can tune adapters/throughput and close parity gaps.

Current high-speed tuning already applied:

- adapter queue capacity raised to reduce frame drops under burst load
- UI batching for raw/decode row updates to avoid per-frame dispatcher thrash

Detailed planning docs:

- `CSharp_WinUI3_Migration_Plan.md`
- `CSharp_Parity_and_Performance_Plan.md`

Fixture generation:

```bash
py tools/build_parity_fixtures.py can_viewer_diag.log tests/CanViewer.Tests/Fixtures/diag_fixture.json
```
