# Host multi-client allocator boundary blocked evidence

Date: 2026-08-21
Host: macOS local development machine
Scope: MacHost Protocol v1 session/display/input allocation only

## What was implemented

- `MultiClientDisplayAllocator` tracks client routes by `session_id` plus
  `session_epoch` and owns display-to-`stream_id` bindings independently of the
  Network.framework connection object.
- The allocator enforces configured `maximum_clients` and per-client video-stream
  caps, reuses a stream for repeated selection of the same display, rejects
  stale lower epochs after a newer epoch registers, and releases routes on
  protocol close.
- `ProtocolV1SessionCoordinator` uses the shared allocator for StartDisplay stream
  allocation, resource-limit reporting, runtime display rebinding, and input
  target validation. Touch, pointer, scroll, keyboard, controller, and host
  action messages must target a route owned by the same client session before
  they can dispatch Host-side actions.
- `StreamingServer` keeps conservative production caps of one client, one
  virtual display, and one video stream per client, and explicitly closes the
  active Protocol v1 session when a connection is replaced, ended, or the server
  stops so stale routes do not consume capacity.

## Local verification

```bash
swift build --package-path baseline/MacHost
make baseline-macos-self-test
make protocol
git diff --check
```

Observed result:

```text
Build complete!
Host self-test: PASS (display identity/catalog, input/window geometry, startup/recovery policy, callback generation, fallback replacement, ADB device selection)
Transport self-test: PASS (config=true, keyframe=true, pong=true, touch=true, malformedTouchRejected=true, portConflict=true, codecNegotiations=1, protocolV1Lifecycle=true, protocolV1ReadyLifecycle=true, protocolV1PreReadyStops=true, fileApprovalDispatch=true, error=none)
Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)
Protocol v1 self-test: PASS (framing, golden, negotiation, display/video gate, multi-client allocation, epoch, targeted input, heartbeat, graceful disconnect, error, media)
video encoder self-test passed (encoded callbacks: 1)
```

`make protocol` passed the Buf format/lint/build/breaking checks and 37 Python
protocol fixture/security tests. `git diff --check` reported no whitespace
errors.

## Blocked acceptance

No multi-device or multi-client real run was executed for this record. No ADB
command was needed. If a future Android run is used, it must address the device
explicitly as `adb -s <device-serial>` and record the device identity as
Nubia P0110 / pacific / Android 16 / SDK 36 unless a different attached device
is actually used and recorded.

The following gates remain open:

- simultaneous Host transport ownership for multiple Network.framework clients;
- parallel ScreenCapture and frame-queue ownership per routed display stream;
- more than one live virtual display from `VirtualDisplayManager`;
- two-client or two-device USB/LAN acceptance with visible display isolation;
- real input-injection proof that events targeted at one routed client/display
  cannot affect another live client/display.

Local XCTest coverage includes allocator caps, invalid IDs, stale epochs,
duplicate-display rebind error mapping, route cleanup, negotiated resource
limits, and cross-client touch/keyboard rejection. It remains blocked in this
Command Line Tools environment:
`swift test --package-path baseline/MacHost --filter ProtocolV1SessionTests/testHostDisplayAllocatorIsolatesClientsEpochsAndStreamLimits`
fails before test execution because SwiftPM cannot import `XCTest`. The XCTest
cases added with this change must run under the full-Xcode CI gate.

This evidence does not close any README real-device, multi-client,
multi-display-capture, signing, TCC, or public-network gate.
