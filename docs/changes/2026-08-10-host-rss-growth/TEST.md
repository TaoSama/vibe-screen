# Host RSS Observation Regression Test Record

## Scope

This change adds a deterministic offline regression gate for the historical
SwiftUI Observation accumulation candidate documented in `TECH.md`. It covers
the settings-publisher behavior that caused high-frequency stream metrics and
unchanged host-state refreshes to rebuild the SwiftUI settings observation
graph over long sessions.

The gate is intentionally offline and does not start the macOS Host, run a
memory soak, inspect TCC state, use ADB, or sample private heap internals. It
does not close the formal Host RSS no-growth gate. That gate still requires a
complete current-source two-hour run and `host_rss_gate` with `verdict=pass`,
including the same-session `host-readiness.json` proving stable signing,
current-source provenance, identity-bound TCC, observed listener, and read-only
readiness collection.

## Regression Invariants

- 10,000 changing FPS/bitrate samples update only the `StreamMetrics` Combine
  subjects and produce zero `DisplaySettings.objectWillChange` events.
- 10,000 duplicate FPS/bitrate samples produce zero metric-subject emissions
  after the initial replay and zero root settings publisher events.
- 10,000 unchanged periodic host-state refresh samples through `setIfChanged`
  produce zero writes and zero root settings publisher events.
- 10,000 changing periodic host-state refresh samples through `setIfChanged`
  produce exactly one root settings publisher event per real write, with no
  extra publisher amplification.
- The test asserts ownership by checking the `DisplaySettings` instance keeps a
  stable reference to its `StreamMetrics` object.

These are public publisher and ownership invariants. They deliberately avoid
counting `ObservationRegistrar` heap objects, matching SwiftUI private class
names, or depending on runtime implementation details that can change across
toolchains.

## Verification

Additional offline capture-lifecycle regression added on 2026-09-10: when
`ScreenCapture` installs transient streaming resources and then reaches a
terminal startup/switch/restart failure after `CGDisplayStream` fallback is
unavailable, it must clear the frame pacer, latest retained pixel buffer,
stream output callback, stream/delegate references, encoder, display reference,
SCStream-started state, and encoded-output marker log before surfacing the
failure. The same contract now also covers terminal-failure restart/start task
cancellation, single-fire terminal failure reporting, explicit deferred
`SCStream.stopCapture()` teardown, and main-thread-safe frame-monitor cleanup
when terminal failure arrives from asynchronous restart work. This covers resource-lifecycle risks
that are adjacent to Host RSS but does not run the Host or prove long-window
resident-memory behavior.

Focused offline checks for that lifecycle contract:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest \
  tools/tests/test_screen_capture_lifecycle_contract.py \
  tools/tests/test_host_rss_gate.py \
  tools/tests/test_host_memory_diagnostic.py \
  tools/tests/test_real_device_gate.py
```

Current local result: pass, 140 tests.

```sh
cd baseline/MacHost && swift build -c release
```

Current local result: pass. The release target built successfully without
starting the Host application.

```sh
cd baseline/MacHost && swift test --filter LatestRetainedSlotTests
```

Current local result: blocked before focused XCTest execution because this
machine's Command Line Tools environment cannot import XCTest. Representative
error:

```text
error: no such module 'XCTest'
```

No Host GUI, product binary, TCC prompt/change, signing change, Keychain access,
ADB reverse mapping, Android device session, or two-hour soak was run for this
offline cleanup check.

Expected focused gate when full Xcode XCTest is available:

```sh
cd baseline/MacHost && swift test --filter StreamMetricsTests
```

Current local result on this machine: blocked before test execution. The active
developer directory is Command Line Tools, not full Xcode, so SwiftPM cannot
import XCTest.

```sh
python3 scripts/macos_dev_host.py xctest-preflight
```

Result: blocked, exit 2. The read-only preflight reported `XCTest.framework
present: false`, `xcrun --find xcodebuild` exit 72, and the same Command Line
Tools developer directory.

```sh
cd baseline/MacHost && swift test --filter StreamMetricsTests
```

Result: blocked, exit 1. Representative error:

```text
error: no such module 'XCTest'
```

Toolchain snapshot:

```text
xcodebuild: active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance
xcode-select -p: /Library/Developer/CommandLineTools
swift-driver version: 1.148.6 Apple Swift version 6.3.3
```

Pure compile/static checks that do not require XCTest:

```sh
cd baseline/MacHost && swift build -c release
```

Result: pass. The production target built successfully. The build emitted
pre-existing Swift 6 `SendableClosureCaptures` warnings in `StreamingServer.swift`;
this change does not touch that file.

```sh
swiftc -parse baseline/MacHost/Tests/TelemachusTests/StreamMetricsTests.swift
```

Result: pass.

```sh
swift scripts/verify_macos_permission_prompt_contract.swift
```

Result: pass, `PASS macOS permission prompt contract`.

Whitespace/static check:

```sh
git diff --check
```

Result: pass.

Offline Host RSS evidence-tool checks:

```sh
PYTHONPATH=tools python3 -m unittest tools/tests/test_host_rss_gate.py
PYTHONPATH=tools python3 -m unittest tools/tests/test_host_memory_diagnostic.py
PYTHONPATH=tools python3 -m unittest tools/tests/test_real_device_gate.py
make phase0-stable-release-gate
```

Expected result: all unit tests pass, and the aggregate Phase 0 gate remains
blocked until a current-source two-hour Host RSS run produces a passing formal
`host_rss_gate` report with the same-session `host-readiness.json`.

## Non-Claims

- This is not Xiaomi/fuxi evidence.
- This is not Nubia P0110/pacific evidence.
- This is not a Host binary run or Host self-test.
- This is not a short Host memory diagnostic.
- This is not a two-hour Host RSS no-growth result.
- The formal Host RSS gate remains open until `host_rss_gate` reports `pass` on
  a complete current-source telemetry-backed two-hour run with a passing shared
  Host readiness report. Readiness-only, short-window, old-Host, non-stable
  signing, missing/incorrect TCC, or source-mismatched evidence cannot close it.
