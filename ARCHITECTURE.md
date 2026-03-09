# Architecture (Qt-Only)

Current release version: `0.1.0`

## Entrypoints

- [can_viewer_qt.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt.py): primary launcher
- [can_viewer.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer.py): compatibility shim to Qt launcher

## Modules

- [can_viewer_qt/app.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/app.py): app bootstrap/theme/icon
- [can_viewer_qt/main_window.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/main_window.py): UI + feature logic
- [can_viewer_qt/backend.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/backend.py): CAN connect/scan/read/send
- [can_viewer_qt/raw_model.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/raw_model.py): bounded raw table model
- [can_viewer_qt/icon.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/icon.py): icon resolution
- [can_viewer_qt/utils.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer_qt/utils.py): stderr-silencing helper
- [app_version.py](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/app_version.py): central app version

## Data Flow

1. `QtCanBackend` reader thread receives `can.Message` and enqueues to bounded queue.
2. Main-window poll timer drains queue in bounded batches.
3. Raw monitor updates via `RawTableModel`.
4. DBC decode resolves message from merged multi-DBC registry (frame-ID map).
5. Symbolic tree, watch-history, plot buffers, and trigger engine update.
6. Trigger captures write output in selected format (`CSV`, `ASC`, `BLF`).

## DBC Registry

- Multiple DBC files are loaded and merged.
- Message key format: `<dbc_file_stem>:<message_name>`.
- Frame-ID conflicts are deterministic: last loaded DBC wins for decode-by-ID.
- Send/trigger source dropdowns use merged message keys.

## Packaging

- [can_viewer.spec](/c:/Softwaredevtest/codexfirstprog/can-bus-viewer/can_viewer.spec) builds Qt executable.
- Hidden imports include CAN backends and PySide6 modules for packaged runtime detection.

## C# WinUI 3 Migration (In Progress)

- Solution: `CanBusViewer.sln`
- App: `src/CanViewer.App`
- Core: `src/CanViewer.Core`
- Adapters: `src/CanViewer.Adapters`
- Tests: `tests/CanViewer.Tests`

Current implemented C# data path:

1. Interface adapter (`ICanSessionService`) produces CAN frames.
2. Main window view-model consumes async frame stream.
3. Raw rows and decode rows update bounded collections.
4. Trigger evaluator runs against incoming frames.
5. Replay parser loads CSV replay entries for later playback integration.
