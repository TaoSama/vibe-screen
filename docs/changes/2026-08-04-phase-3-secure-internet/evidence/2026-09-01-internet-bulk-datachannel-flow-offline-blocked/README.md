# Internet bulk DataChannel product flow - offline blocked

This record documents the 2026-09-01 current-worktree implementation check for
the Internet WebRTC `vibescreen.bulk.v1` file-transfer product flow. It is an
offline contract and build-readiness record, not a public Internet product E2E
pass.

## Result

**BLOCKED.** The Android and macOS Internet product sessions now wire the
file-transfer product flow through Protocol v1 control messages plus the
`vibescreen.bulk.v1` DataChannel boundary, but the retained public Internet
gate remains blocked. The generated gate report records
`can_close_public_internet_bulk_product_flow_gate=false`.

The `source_current_base` check passes for this evidence package. The generated
manifest and gate report point at clean implementation commit
`aed8c99ccb93ce35c65e5956c9de693eebf88dbd` and record
`tree_status=clean`. The runtime product gate remains blocked because no real
macOS Host plus Android public Internet run exists in this directory.

## Implemented offline scope

- Android Internet Protocol v1 advertises optional file-transfer and managed
  configuration capabilities without making them required for legacy peers.
- Android `InternetProductSession` reuses the existing `FileTransferProductOwner`
  for file offers, explicit approval, outgoing sends, incoming chunk writes,
  progress, cancel, completion, SHA-256 validation, and managed-policy deny-wins
  behavior.
- macOS Internet Protocol v1 advertises and negotiates file-transfer resource
  limits, including the minimum of host and peer maximum file/chunk sizes.
- macOS `InternetProductSession` binds the existing file-transfer UI server,
  requires explicit incoming approval, routes approved file chunks through the
  advanced bulk-channel gate, leaves unapproved or rejected file-shaped bulk
  payloads on the raw bulk path, and reports incoming completion to the existing
  save-to-Downloads flow.

## Verification

The following allowed offline checks were run in this worktree:

- `cd baseline/AndroidClient && ./gradlew testDebugUnitTest --tests 'dev.telemachus.display.internet.ProtocolV1ProductCodecTest' --tests 'dev.telemachus.display.internet.InternetProductSessionTest' --tests 'dev.telemachus.display.FileTransferProductOwnerTest'`
- `make baseline-android-check`
- `cd baseline/MacHost && swift build`
- `cd baseline/MacHost && swift build -c release`
- `cd baseline/MacHost && swiftc -parse Tests/TelemachusTests/InternetProductSessionTests.swift && swiftc -parse Tests/TelemachusTests/InternetProductProtocolCodecTests.swift`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase3_webrtc_bulk_product_flow tools.tests.test_phase3_internet_release_gate -v`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_schemas -v`
- `make phase3-webrtc-bulk-product-flow-blocked-baseline EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-09-01-internet-bulk-datachannel-flow-offline-blocked`

The local environment has only Command Line Tools selected, so `swift test` is
blocked before execution by missing XCTest (`no such module 'XCTest'`). The
focused Swift XCTest source files were parsed with `swiftc -parse`, and the
macOS product target built successfully in debug and release configurations.

## Missing product-flow evidence

- No real macOS Host and real Android device participated in this record.
- No public Internet WebRTC route or deployed remote TURN relay was selected.
- No identity-signed Host with Screen Recording permission was operated.
- No real ScreenCaptureKit or CGDisplayStream frames reached Android MediaCodec.
- No approved bidirectional product file transfer over a public
  `vibescreen.bulk.v1` WebRTC route was captured.
- No packet-capture proof exists for AES-256-GCM bulk channel/session/key
  separation on a public relay route.
- No network handoff, cross-service revocation, external-camera latency, or
  two-hour mixed-route soak package is present.

## Files

- `webrtc-bulk-product-flow-manifest.json`: default blocked manifest generated
  from the clean implementation commit.
- `webrtc-bulk-product-flow-gate.json`: machine-readable blocked gate result.
- `commands.txt`: commands used for this implementation and evidence record.
- `SHA256SUMS`: integrity binding for this evidence directory.

This child gate does not close the broader Phase 3 public Internet release gate.
