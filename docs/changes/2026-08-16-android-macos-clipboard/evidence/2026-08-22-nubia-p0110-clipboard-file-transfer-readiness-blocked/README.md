# Nubia P0110 Clipboard + File Transfer Readiness Blocked

Date: 2026-08-22
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial: EP0110PZ0B9110300B
Source branch: codex/clipboard-file-transfer-gate
Fetched origin/main during collection: 47207c5bc82f9931eb82ec886d2d55e96c3f3e5b

## Verdict

Status: blocked. Gate closed: false.

This package records readiness work for Android <-> Mac clipboard and bounded
file transfer. It does not prove USB or LAN end-to-end transfer between Android
ClipboardManager or SAF and macOS NSPasteboard or Downloads.

## What passed

- Android device identity was collected with explicit serial
  adb -s EP0110PZ0B9110300B and matches nubia P0110 / pacific / Android 16 /
  SDK 36.
- Debug app and androidTest APKs installed on the P0110.
- ClipboardManagerInstrumentedTest passed on the device: OK (3 tests).
- Android focused clipboard JVM tests passed.
- Android focused file-transfer JVM tests passed, including non-blocking
  incoming file approval, negotiated peer file-size limit enforcement, and
  mismatched completion SHA-256 rejection.
- Android assembleDebug assembleDebugAndroidTest passed.
- Android lintDebug passed.
- Protocol fixtures passed: 16 tests, 0 failures.
- Evidence tool tests passed: 237 tests, 0 failures.
- MacHost swift build passed after adding file-transfer UI binding and sender
  integrity checks.

## What changed in readiness code

- Android incoming file approval is asynchronous and no longer blocks the
  outbound writer while the user decides.
- Android incoming files are saved to Downloads after completion, with SHA-256
  logged and staging cleaned up after save.
- Android and Mac senders validate completion SHA-256 before treating a transfer
  as successful.
- Android file offers apply the negotiated peer file-size limit before emitting
  a wire offer.
- Android outgoing file-transfer state is safe for cleanup races, and selected
  file staging plus digest preparation stays off the UI thread.
- Mac sender validates file-transfer progress acknowledgements against the
  sent offset before sending the next chunk.
- MacHost adds a status-menu file-transfer entry, receiver approval dialog, and
  Downloads save path for completed incoming files.

## Blockers

- security find-identity -v -p codesigning reports 0 valid identities found.
- xcode-select -p points to /Library/Developer/CommandLineTools.
- xcrun --find xcodebuild fails, and MacHost XCTest cannot import XCTest.
- No stable-signed, TCC-authorized Host was available for a real USB/LAN
  clipboard or file-transfer session.

## Gate boundary

The Android local clipboard smoke proves only Android system clipboard access on
the P0110. It does not prove Android <-> Mac clipboard E2E. The bounded
file-transfer code and local tests improve readiness, but without the signed
Host/TCC session and observed receiver approvals plus SHA-256 checks over USB
and LAN, both gates remain open.
