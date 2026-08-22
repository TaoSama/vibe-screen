# Nubia P0110 File Transfer Readiness Blocked

Date: 2026-08-22
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial: EP0110PZ0B9110300B
Source branch: codex/clipboard-file-transfer-gate
Fetched origin/main during collection: 47207c5bc82f9931eb82ec886d2d55e96c3f3e5b

## Verdict

Status: blocked. Gate closed: false.

The code path is materially closer to a device gate: Android receiver approval
is non-blocking, completed Android receives are saved to Downloads, MacHost has
a send-file menu and receiver approval/save path, and both senders now fail
closed on bad completion SHA-256. Android client-side file offers also apply
the negotiated peer file-size limit before emitting a wire offer. This package
also moves selected-file staging and digest preparation off the Android UI
thread, and keeps outgoing transfer cleanup safe across scheduler shutdown. It
is still not a USB/LAN end-to-end pass.

## Verified locally

- Android focused file-transfer JVM tests passed.
- Android assembleDebug assembleDebugAndroidTest passed.
- Android lintDebug passed.
- MacHost swift build passed.
- Protocol fixture tests passed: 16 tests, including file-transfer control and
  bulk fixtures.
- Evidence tool tests passed: 237 tests.
- P0110 APK installation succeeded and Android local clipboard instrumentation
  passed; this confirms device/app install readiness, not file-transfer E2E.

## Blockers

- No stable macOS signing identity: 0 valid identities found.
- Full Xcode is unavailable: xcrun --find xcodebuild failed.
- MacHost XCTest is blocked by no such module XCTest under Command Line Tools.
- No TCC-authorized current Host run was available to observe live Protocol v1
  CAPABILITY_FILE_TRANSFER negotiation with the P0110.

## Gate boundary

Do not cite this package as real-device file-transfer acceptance. A valid pass
still needs a signed, TCC-authorized Host and a recorded USB and/or LAN session
showing sender selection, receiver explicit approval, progress/cancel behavior,
completed file save, and matching SHA-256 on both sides.
