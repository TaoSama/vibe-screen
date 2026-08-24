# Phase 5 multi-client/display current-base blocked evidence

Date: 2026-08-24
Current-base target: `origin/main` at `8fcec1d9`
Scope: planned Phase 5 simultaneous multi-client display ownership

## Result

The current-base multi-client/display gate is blocked. No two-device or
multi-client Host run was collected for this record, and no Android ADB command
was needed or run. If a future run uses a connected Android device, it must use
`adb -s <device-serial> ...` and record the attached device model, codename,
Android version, and SDK level from the evidence run.

## Current-base audit

The current Host production path remains single-client:

- `baseline/MacHost/Sources/StreamingServer.swift:298` and
  `baseline/MacHost/Sources/StreamingServer.swift:447-456` show
  `StreamingServer` owns one active `NWConnection?`, one
  `ProtocolV1SessionCoordinator?`, one connection generation, and one Protocol
  v1 display identity at a time.
- `baseline/MacHost/Sources/StreamingServer.swift:701-724` stores the previous
  connection, advances a single generation/epoch, then assigns
  `connection = conn` instead of routing clients concurrently.
- `baseline/MacHost/Sources/ScreenCapture.swift:258-262` and
  `baseline/MacHost/Sources/ScreenCapture.swift:942-960` show `ScreenCapture`
  owns one capture stream, one encoder, and one current frame sink.
- `baseline/MacHost/Sources/VirtualDisplayManager.swift:37` destroys any
  existing virtual display before creating another.
- `baseline/MacHost/Sources/ReliabilityCore.swift:102-110` keeps one active
  `SessionEpochGate` epoch.
- `baseline/MacHost/Sources/ProtocolV1Session.swift:181-206` lists production
  Host capabilities without `.multiClient`.
- System input injection ultimately targets the single macOS event stream, so
  concurrent client input needs explicit route ownership before it can be
  claimed.

This means existing single-client display-selection and display-switch evidence
is useful for display identity, but it is not simultaneous multi-client
concurrency evidence.

## PR audit

- #201 adds an offline Host Protocol v1 routing boundary and records that
  production remains capped at one active Network.framework connection, one
  virtual display, and one video stream per client. It does not close
  multi-device, parallel capture, or multi-virtual-display acceptance.
- #248 is Phase 3 coordination documentation only.
- #284 adds a Phase 3 production E2E aggregate gate and does not own Phase 5
  multi-client/display concurrency.
- #314 is merged Phase 3 Internet release-gate work and does not own Phase 5
  multi-client/display concurrency.

## Required future evidence

A passing package must include at least:

- retained Host routing evidence for two simultaneous clients;
- independent transport ownership evidence for both clients;
- display identity and stream binding evidence that proves each client owns its
  target display/stream;
- retained macOS Host evidence showing the Host does not replace the old
  connection when a second client connects;
- two Android client artifacts proving visible distinct streams;
- input target isolation evidence showing input for one routed client/display
  cannot affect another live client/display;
- iOS and HarmonyOS owner status records so the cross-platform Phase 5 surface
  stays explicitly owned.

The generated gate output for this package is expected to remain `blocked`.
