# C# Port Parity + Performance Validation Plan

Date: 2026-03-06  
Applies to branch: `feature/csharp-winui3-port`

## Current Verification Snapshot (2026-03-09)

- Automated tests currently passing: 14
- Build verification:
  - `dotnet build src/CanViewer.App/CanViewer.App.csproj` passes
  - `dotnet test tests/CanViewer.Tests/CanViewer.Tests.csproj` passes
- Covered by tests now:
  - bounded raw buffer rollover semantics
  - virtual loopback send/read
  - adapter factory mapping and scan defaults
  - replay CSV parser contract
  - trigger evaluator operator behavior (baseline cases)

## 1) Purpose

Define how the C# WinUI 3 implementation is validated against the Python baseline for:

- Functional parity
- Real-time capability
- Stability under sustained load

## 2) Baseline Inputs

Use current project artifacts as source-of-truth references:

- `README.md` (documented behavior)
- `ARCHITECTURE.md` (data flow expectations)
- Existing logs and captures:
  - `can_viewer_diag.log`
  - `can_viewer_qt_*.log`
  - Representative trace files used for replay/trigger workflows

## 3) Parity Test Matrix

## A) Connection + Interfaces

- Interface scan and channel selection for `pcan`, `vector`, `slcan`, `virtual`
- Connect/disconnect/reconnect behavior
- Failure messaging when interface/channel is invalid/unavailable

## B) Raw Monitor

- Row append behavior under continuous traffic
- Bounded buffer rollover behavior
- Auto-scroll on/off behavior
- Error frame/row visual indication equivalent semantics

## C) Send

- Raw frame send correctness (ID, DLC, payload, standard/extended where applicable)
- DBC-driven send form behavior
- Repeated/periodic send behavior and cancellation

## D) Decode/Watch

- Multi-DBC load/remove
- Last-loaded-wins resolution for frame-ID collisions
- Signal value decode and update behavior
- Watch/history updates and change highlight semantics

## E) Replay

- Open and parse supported formats
- Replay run/stop lifecycle
- Side decode panel consistency vs baseline

## F) Triggers

- Operator correctness:
  - `==`, `!=`, `>`, `>=`, `<`, `<=`, `rising`, `falling`, `changed`
- Post-trigger byte capture behavior
- Master output settings + per-trigger overrides
- Output format correctness: `CSV`, `ASC`, `BLF`

## 4) Performance Validation

Measure and track per build:

- Ingest throughput (frames/sec)
- UI update latency from receive to visible row
- Drop count and drop rate under sustained load
- CPU and memory profile during long runs
- Connect/disconnect churn stability

Recommended runs:

- Low load sanity run
- Sustained medium load
- Burst/high load stress run
- Long soak run for resource leak detection

## 5) Automation Strategy

- Unit tests for core logic:
  - DBC merge rules
  - Trigger operator logic
  - Replay parsing/writing logic
- Integration tests:
  - End-to-end decode from fixture frame streams
  - Trigger capture outputs compared to expected artifacts
- Performance test harness:
  - Synthetic frame generator with deterministic patterns
  - Fixed-duration benchmark scenarios

## 6) Gating Rules (Per Milestone)

A milestone is complete only if:

- All in-scope parity tests pass.
- No crash/regression in smoke tests for all interfaces.
- Performance is acceptable for real-time monitoring use on target machine.
- Known gaps are documented with explicit deferral and owner.

## 7) Reporting Format

For each milestone, record:

- Build/commit ID
- Test set executed
- Pass/fail summary
- Performance metrics snapshot
- Open issues and severity

Use this format to keep comparisons consistent between runs.

## 8) Immediate Setup Tasks

1. Build fixture catalog from existing logs/traces.
2. Define expected outputs for decode and trigger capture fixtures.
3. Add initial test harness in `CanViewer.Tests`.
4. Add benchmark runner project and baseline metrics capture.
