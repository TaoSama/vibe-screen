# 2026-08-29 Nubia P0110 file-transfer current-base readiness

This evidence package is a fail-closed current-base readiness record for the
Protocol v1 Android/macOS single-file transfer E2E gate. It starts from
origin/main at 567dae75da22b2faa49ab59e5d95b4a642be1d97 and records the
connected Android substitute as nubia P0110 / pacific / Android 16 / SDK 36. The
USB serial is intentionally redacted as REDACTED_P0110_USB_SERIAL; this P0110
evidence must not be relabeled as Xiaomi 13/fuxi evidence.

## Verdict

file-transfer-android-smoke-gate.json reports result=blocked, gate_closed=false,
and can_close_file_transfer_android_smoke_gate=false. The run does not claim
Android <-> macOS product file transfer over USB or LAN.

## Positive readiness

- The P0110 identity matched the expected general Android substitute.
- ADB reverse for tcp:54321 -> tcp:54321 was present.
- The Android app was installed, running, and foreground during USB preflight.
- A Host listener was observed on loopback TCP port 54321.
- Android file-transfer control-bar instrumentation passed with OK (2 tests).
- Focused Android JVM file-transfer/session tests passed.
- make protocol-tests passed 45 protocol/fixture/security tests.
- The file-transfer gate unit tests passed 12 tests.

## Blockers

- Host readiness is blocked because the stable Vibe Screen Dev signing identity
  is unavailable, the installed Host lacks source commit/tree provenance, TCC
  permissions cannot be verified read-only, the virtual HID entitlement is
  missing, and login/headless readiness is unverified.
- USB readiness cannot prove a real Protocol v1 file-transfer path while Host
  readiness is blocked.
- No trusted-LAN preflight was collected.
- No file-transfer-product-e2e.json exists, so no bidirectional Android-to-macOS
  and macOS-to-Android product transfer, receiver approval, remote file write,
  final SHA-256 equality, positive session epoch, or cancel/cleanup behavior is
  proven.

## Retained artifacts

- host-readiness.json and baseline-macos-host-readiness.exit record the
  sanitized Host prerequisite failure.
- usb-smoke-preflight.json and evidence-usb-smoke-preflight.exit record the
  sanitized USB readiness state.
- android-install-debug-test.txt and .exit summarize the Android install command.
- android-file-transfer-instrumentation.txt and .exit retain the on-device
  Android instrumentation result.
- android-focused-jvm-tests.txt and .exit retain focused JVM coverage.
- protocol-tests.txt and .exit retain Protocol v1 fixture coverage.
- file-transfer-gate-unit-tests.txt and .exit retain gate checker coverage.
- commands.txt records the sanitized command ledger.
