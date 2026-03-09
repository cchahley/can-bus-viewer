# C# + WinUI 3 Migration Plan (Big-Bang)

Status: Draft for implementation kickoff  
Branch: `feature/csharp-winui3-port`  
Date: 2026-03-06

## Current Implementation Snapshot (2026-03-09)

- C# solution and project structure created (`Core`, `Adapters`, `App`, `Tests`).
- App builds and launches via `dotnet run --project src/CanViewer.App/CanViewer.App.csproj`.
- Core and adapter test suite is passing.
- Implemented foundations:
  - interface-scoped adapter services for `pcan`, `vector`, `slcan`, `virtual`
  - bounded frame buffer
  - trigger evaluator core
  - replay CSV parser core
- Remaining high-priority gap:
  - WinUI multi-tab parity UI (decode/replay/trigger screens) still incomplete.

## 1) Goals

- Port the current Python/Qt CAN Bus Viewer to C# + WinUI 3.
- Preserve functional behavior, while allowing WinUI-native UX decisions where beneficial.
- Support all current interfaces from day one: `pcan`, `vector`, `slcan`, `virtual`.
- Optimize for real-time throughput and low-latency UI updates under sustained bus load.
- Ship on Windows 11 with MSIX packaging.

## 2) Scope + Priority

Feature priority confirmed:

1. Raw monitor + Send
2. Decode + Replay
3. Triggers

Big-bang delivery model:

- New app built in parallel and cut over once parity + performance gates pass.
- Python branch remains the fallback/reference baseline.

## 3) Recommended Solution Layout

Create a .NET solution with strict separation of concerns:

- `CanViewer.Core`
  - Frame models, DBC merge/lookup rules, decode pipeline
  - Trigger engine and operators
  - Replay parsing/writing orchestration
  - Logging abstractions
- `CanViewer.Adapters`
  - CAN interface adapters (`pcan`, `vector`, `slcan`, `virtual`)
  - File format adapters (`csv`, `asc`, `blf`)
  - DBC parser integration wrapper
- `CanViewer.App` (WinUI 3)
  - Views/ViewModels (MVVM)
  - Virtualized grids/charts
  - Dispatcher-safe UI projection of backend pipelines
- `CanViewer.Tests`
  - Unit tests (Core rules)
  - Integration tests (decode, replay, trigger capture)
  - Parity fixtures from Python logs/traces
- `CanViewer.Benchmarks` (optional but recommended)
  - Throughput/latency benchmarks for hot paths

## 4) Technology Choices

- Runtime: `.NET 10`
- UI: `WinUI 3` (Windows App SDK)
- Pattern: `MVVM` (CommunityToolkit.Mvvm recommended)
- DBC parser: approved to use a .NET package; wrap behind `IDbcCatalog` so package is swappable.
- Packaging: `MSIX` primary distribution target.

## 5) Real-Time Performance Strategy

Design for predictable throughput:

- Single ingest path per CAN channel using non-blocking producer pipeline.
- Use bounded channels/queues (`System.Threading.Channels`) to avoid unbounded memory growth.
- Keep UI thread read-only and projection-only; no blocking I/O, no decode in UI thread.
- Batch UI updates at fixed cadence (for example 30-60 Hz) instead of per-frame repaint.
- Use row virtualization for raw monitor and replay tables.
- Precompute DBC lookup maps keyed by arbitration ID.
- Minimize allocations in hot loops:
  - Reuse buffers where feasible
  - Avoid repeated string formatting in ingest path
  - Defer expensive formatting to UI projection stage
- Support backpressure with explicit dropped-frame counters and user-visible diagnostics.

## 6) Target Acceptance Metrics

Initial targets (adjust after first benchmark pass):

- Ingest and process: sustain high bus traffic without UI freeze.
- UI responsiveness: controls remain interactive during sustained capture.
- End-to-end display latency: stable and low enough for real-time monitoring use.
- Drop policy: no silent loss; every drop is counted and surfaced.
- Connect/disconnect/reconnect: deterministic and fast, no stale background tasks.

Note: exact numeric thresholds should be finalized after first test data run on your hardware.

## 7) Functional Mapping from Python

Reference Python modules:

- `can_viewer_qt/backend.py` -> `ICanSessionService` + interface adapters
- `can_viewer_qt/raw_model.py` -> bounded observable row buffer service
- `can_viewer_qt/main_window.py` -> split across ViewModels + domain services

Behavior to preserve:

- Multi-DBC merge with deterministic "last loaded wins" for frame-ID conflicts
- Watch/decode history behavior
- Send workflows (raw + DBC forms/cards)
- Replay decode panel behavior
- Trigger operators and capture outputs (`CSV`, `ASC`, `BLF`)

## 8) Implementation Milestones

## Milestone A: Foundation

- Create solution/projects and CI pipeline for .NET build + test.
- Implement logging, diagnostics, and global exception handling.
- Implement CAN abstraction and channel scanning contract for all interfaces.

Exit criteria:

- App launches, basic shell UI works, CAN interfaces enumerate via abstraction.

## Milestone B: Raw Monitor + Send (Priority 1)

- Implement connect/disconnect lifecycle, reader pipeline, and bounded queue.
- Implement raw monitor table with virtualization + auto-scroll + clear.
- Implement send:
  - Raw frame send
  - DBC-driven send cards (minimal first pass, then parity)

Exit criteria:

- Stable real-time monitoring + send under sustained traffic.

## Milestone C: Decode + Replay (Priority 2)

- DBC load/remove, merged catalog, lookup by ID.
- Decoded watch/history views and change highlighting equivalent behavior.
- Replay open/start/stop + side decode panel.

Exit criteria:

- Decoding parity verified against fixture traces.

## Milestone D: Triggers (Priority 3)

- Trigger conditions (`==`, `!=`, `>`, `>=`, `<`, `<=`, `rising`, `falling`, `changed`)
- Capture N bytes post-trigger, output format routing, per-trigger overrides.

Exit criteria:

- Trigger behavior parity with Python baseline in automated fixture tests.

## Milestone E: Packaging + Release Readiness

- MSIX packaging and install validation on Windows 11.
- Compliance docs and third-party notices refresh for .NET dependency set.
- Performance and parity signoff.

## 9) Risks and Mitigations

- Risk: CAN vendor SDK/API differences in .NET.
  - Mitigation: adapter interface + early hardware smoke tests per interface.
- Risk: UI jank from high-frequency updates.
  - Mitigation: fixed-rate UI batching + virtualization + background decode.
- Risk: behavior drift during big-bang.
  - Mitigation: parity fixtures and acceptance checks at each milestone.

## 10) Immediate Next Actions

1. Scaffold .NET solution and project structure.
2. Implement `ICanSessionService` + `virtual` adapter first (fast loopback testing).
3. Build raw monitor pipeline with throughput counters and dropped-frame telemetry.
4. Add parity fixture harness from existing logs and representative capture files.
5. Add first interface adapters (`pcan`, `vector`, `slcan`) and run hardware smoke tests.
