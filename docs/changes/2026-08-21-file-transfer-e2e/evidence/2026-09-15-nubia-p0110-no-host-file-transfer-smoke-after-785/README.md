# 2026-09-15 Nubia P0110 no-Host file-transfer smoke after PR #785

This evidence package exercises the focused Android file-transfer UI smoke on
current `origin/main` commit `092f05c2208fa1833fb1d9e541ec2e30c2bd379f`,
after PR #785 added strict support for raw Android `INSTRUMENTATION_STATUS`
logs. The device was a nubia P0110 / pacific running Android 16 / SDK 36. Its
ADB serial is intentionally redacted and this evidence must not be relabeled as
Xiaomi 13 / fuxi evidence.

## Result

The focused on-device run passed all five required file-transfer UI smoke
methods. The retained raw log contains paired start/pass records, a consistent
`numtests=5`, `OK (5 tests)`, and final `INSTRUMENTATION_CODE: -1`. The formal
gate therefore reports `android_file_transfer_smoke=pass`.

The overall gate remains `blocked`, with `gate_closed=false` and
`can_close_file_transfer_android_smoke_gate=false`. This package does not prove
Android/macOS product file transfer.

## No-Host boundary

- No macOS Host was started.
- No Screen Recording, Accessibility, Microphone, or other TCC permission was
  requested or modified.
- `adb reverse --list` contained no mapping before or after the run; no
  `tcp:54321` reverse was created.
- `lsof -nP -iTCP:54321 -sTCP:LISTEN` found no listener before or after the
  run.
- Device commands ran while `/tmp/vibe-screen-device-android.lock` was held;
  the lock was released and the instrumentation package was uninstalled after
  the run.

## What remains open

The missing current signed/TCC-ready Host, missing real Protocol v1 USB or
trusted-LAN path, missing bidirectional `file-transfer-product-e2e.json`, and
missing cancel/disconnect cleanup product artifacts keep the Phase 0
`file_transfer_android_product_e2e` gate blocked. No file picker action,
receiver approval in a product session, remote destination write, retained
source/destination bytes, shared session ID, ordered chunk stream, or final
cross-endpoint SHA-256 equality was exercised here.

## Retained evidence

- `android-file-transfer-instrumentation.txt` is the raw five-test gate input.
- `android-test-results/test-results.log` retains the same raw status stream for
  independent inspection.
- `usb-smoke-preflight.json` is a current-run blocked, read-only identity and
  no-Host prerequisite record; it is not USB product evidence.
- `file-transfer-android-smoke-gate.json` is the formal fail-closed result.
- `logs/` retains the empty reverse listings and no-listener observations.
- `metadata/` records source, device identity, and scope boundaries.
- `SHA256SUMS` binds every retained file in this package.
