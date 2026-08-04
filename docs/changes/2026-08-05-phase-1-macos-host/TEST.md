# Phase 1 macOS host verification record

## Environment

- host: macOS 26.4.1 (`25E253`), arm64;
- Swift: 6.3.1;
- selected developer directory: `/Library/Developer/CommandLineTools`;
- full Xcode/XCTest: unavailable (`xcodebuild` rejects the selected developer
  directory);
- Android soak lease was present during implementation and later released
  without starting its two-hour clock because the locked Mac exposed zero
  ScreenCaptureKit displays. Android Phase 1 and Internet work retain device
  priority, so this task ran no ADB, media-port, normal Host, or device action.

## Completed evidence

The following output is abridged; persistent display UUID values are omitted
from the document but were present in the local command output.

```text
make baseline-macos-self-test
Build complete!
Host display evidence: id=1, logical=1512x982, physical=3024x1964
Host display evidence: id=2, logical=1920x1080, physical=3840x2160
Private virtual display API shape check: available
(class/selector presence is not creation/capture evidence)
Host self-test: PASS (display identity/catalog, input/window geometry,
startup policy, bounded recovery backoff)
Transport self-test: PASS (config=true, keyframe=true, pong=true, touch=true,
malformedTouchRejected=true, portConflict=true, error=none)
Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)

make baseline-macos-app
.build/release-artifacts/Telemachus-macos-0.12.0-arm64.zip
.build/release-artifacts/Telemachus-macos-0.12.0-arm64.sha256

shasum -a 256 -c Telemachus-macos-0.12.0-arm64.sha256
Telemachus-macos-0.12.0-arm64.zip: OK
SHA-256: 6f782eed4cb63e0f3cc02e52540e06d907ef5cf5fa991614446600e24ab4c0ab

unzip -t Telemachus-macos-0.12.0-arm64.zip
No errors detected in compressed data

codesign --verify --deep --strict <extracted>/Telemachus.app
<extracted>/Telemachus.app: valid on disk
Signature=adhoc

spctl -a -vv <extracted>/Telemachus.app
<extracted>/Telemachus.app: rejected
(expected for the explicitly non-notarized ad-hoc development artifact)
```

The self-test covers stable display UUID enumeration/fallback, density-aware
virtual identity, negative-origin input mapping and malformed-coordinate
rejection, UUID-aware online/offline window recovery geometry, startup
eligibility, and the bounded recovery schedule. The loopback transport
self-test also proves malformed touch cancellation without posting a real
system event. XCTest sources add focused policy/lifecycle cases under
`Phase1HostCapabilityTests.swift` and `StreamingServerLifecycleTests.swift`.
The added cases cover concurrent double-start admission, stop invalidation of a
suspended start, current/stale fallback stop generations, blank/idle fallback
frames, missing private classes/selectors, and exact unchanged-bounds window
recovery. They remain source-level regression coverage until XCTest can run.

`make baseline-macos-test` compiles the application target but fails before
test execution with `error: no such module 'XCTest'`; full Xcode is not
installed/selected. No XCTest pass is claimed.

## Remaining gates

- `swift test` with full Xcode selected;
- private normal/HiDPI extension creation and first captured frame;
- true mirror state before start and cleared state after stop;
- AX migration/restore of a disposable real window, including display removal;
- Launch at Login approval plus logout/login relaunch;
- selected-display hot-plug while streaming;
- Android touch/reconnect/keyboard/native-mouse checks after the device lease
  is released (keyboard/native mouse also require a future transport entry);
- Phase 1 two-hour no-growth result and external input/glass-to-glass latency.

None of these gates is inferred from compilation or private-symbol presence.
