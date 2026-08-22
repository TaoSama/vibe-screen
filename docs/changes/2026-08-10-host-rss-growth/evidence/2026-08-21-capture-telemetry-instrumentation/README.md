# 2026-08-21 Capture Telemetry Instrumentation

## Scope

This evidence records the offline validation for the `codex/host-rss-root-cause-fix`
branch. The branch addresses one real allocation hot path and adds production
telemetry that makes the next Host RSS short-window diagnostic able to distinguish
bounded capture/encoder frame ownership from unbounded retained growth.

This is not a two-hour Host RSS no-growth pass. No Screen Recording/TCC-authorized
real-device short-window run or two-hour soak was executed from this source
revision, so the README Phase 0 Host RSS no-growth gate remains open.

## Changes Under Test

- `TelemetryEvent` and `TelemachusLog.write` now use one locked shared
  `ISO8601DateFormatter` instead of constructing a formatter for every telemetry
  or log timestamp. This removes a repeated per-sample allocation source during
  streaming.
- `stream_stats` telemetry now includes `frame_registry_count` when encoder
  runtime stats are available, plus capture-side
  `latest_pixel_buffer_retained` and `latest_pixel_buffer_capacity` when capture
  lifecycle stats are available.
- `host_memory_analysis` keeps older telemetry readable when the new optional
  fields are absent, while failing closed if a partially emitted optional pair is
  present or if frame registry/latest pixel buffer ownership exceeds advertised
  capacity.

## Verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_memory_diagnostic -v
Ran 58 tests in 3.324s
OK
```

```text
cd baseline/MacHost && swift build
Build complete! (2.07s)
```

```text
cd baseline/MacHost && swift build -c release
Build complete! (0.68s)
```

```text
make baseline-macos-self-test
Host self-test: PASS (display identity/catalog, input/window geometry, startup/recovery policy, callback generation, fallback replacement, ADB device selection)
Transport self-test: PASS (config=true, keyframe=true, pong=true, touch=true, malformedTouchRejected=true, portConflict=true, codecNegotiations=1, protocolV1Lifecycle=true, protocolV1ReadyLifecycle=true, protocolV1PreReadyStops=true, fileApprovalDispatch=true, error=none)
Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)
Protocol v1 self-test: PASS (framing, golden, negotiation, display/video gate, epoch, targeted input, heartbeat, graceful disconnect, error, media)
video encoder self-test passed (encoded callbacks: 1)
```

```text
git diff --check
# no output
```

## Blocked Checks

```text
xcode-select -p
/Library/Developer/CommandLineTools

cd baseline/MacHost && swift test --filter StreamMetricsTests --filter VideoEncoderInFlightAdmissionTests --filter LatestRetainedSlotTests
error: no such module 'XCTest'
```

The local toolchain has Command Line Tools selected rather than a full Xcode
runtime with XCTest available, so the focused XCTest suite could not run here.

## Gate Status

- Current-source real-device short-window Host memory diagnostic: not run.
- Current-source two-hour Host RSS no-growth soak: not run.
- README Phase 0 Host RSS no-growth gate: still open.
