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
complete current-source two-hour run and `host_rss_gate` with `verdict=pass`.

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

## Non-Claims

- This is not Xiaomi/fuxi evidence.
- This is not Nubia P0110/pacific evidence.
- This is not a Host binary run or Host self-test.
- This is not a short Host memory diagnostic.
- This is not a two-hour Host RSS no-growth result.
- The formal Host RSS gate remains open until `host_rss_gate` reports `pass` on
  a complete current-source telemetry-backed two-hour run.
