# Nubia P0110 Clipboard E2E Current Main Blocked

Date: 2026-09-08 (local, Asia/Shanghai; UTC 2026-09-08)
Source base: `origin/main` at `a16271d349041516e63961846517a58690f860e3`
Branch: `codex/clipboard-e2e-current-main-gate`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package refreshes the Android/macOS clipboard product E2E gate on current
main after hardening the Android ClipboardManager smoke parser. It proves the
gate still accepts the retained current-main 8-test Android system clipboard
smoke as Android-local readiness while keeping the product E2E verdict blocked.
It does not prove Android `ClipboardManager` -> macOS `NSPasteboard` or macOS
`NSPasteboard` -> Android `ClipboardManager` transfer.

## What Passed

- The device identity matched nubia P0110 / pacific / Android 16 / SDK 36.
- The final gate run used the retained current-main 8/8
  `ClipboardManagerInstrumentedTest` log from the current-main Android baseline
  package as the Android smoke input. The new verifier accepted that log as
  `android_clipboardmanager_smoke=pass` because every required method has a
  passed raw instrumentation record, the raw run reports `numtests=8`, and the
  final instrumentation code is `-1`.
- The final `clipboard-e2e-gate.json` preserved `gate_closed=false` and
  `can_close_android_macos_clipboard_e2e_gate=false` because Host readiness,
  USB, trusted LAN, and bidirectional product evidence are still blocked.
- Read-only `adb reverse --list` snapshots were retained before and after this
  run. Both snapshots are empty, recording no product `tcp:54321` reverse
  mapping in the captured state.

## Negative Raw Rerun

A direct `adb shell am instrument` rerun was attempted under the no-Host boundary
and retained as negative evidence. That rerun did not complete: the
instrumentation process crashed during the sixth Android clipboard test and
ended with `INSTRUMENTATION_CODE: 0`. The companion
`clipboard-e2e-gate-raw-rerun.json` intentionally rejects that raw log with
`android_clipboardmanager_smoke=blocked`. This demonstrates the hardened gate no
longer trusts method-name text or partial instrumentation output as a passing
Android smoke.

The failed raw rerun is not used as passing evidence. The passing Android smoke
for the final gate remains the retained current-main 8/8 log copied into this
bundle.

## Blockers

- Host readiness is blocked by missing stable `Vibe Screen Dev` signing
  identity, stale installed Host CodeResources entries, no Host listener on TCP
  `54321`, missing virtual HID entitlement, and unverified login/headless state.
- USB readiness is blocked because `adb reverse tcp:54321 tcp:54321` is not
  configured, the Android package is not installed/foreground for product
  preflight, the Mac Host is not listening on TCP `54321`, and Host
  stable-signing/TCC readiness failed.
- Trusted LAN readiness is blocked because the device Wi-Fi is not associated,
  `wlan0` has no IPv4 address or route to the Mac LAN candidate, and Host stable
  signing is blocked.
- No retained bidirectional product E2E record exists for Android
  `ClipboardManager` -> macOS `NSPasteboard` or macOS `NSPasteboard` -> Android
  `ClipboardManager`.

## Evidence Boundary

This run did not start the Vibe Screen/MacHost/Telemachus GUI, did not run
`swift run`, did not request, reset, or modify Screen Recording, Accessibility,
Microphone, Keychain, TCC, or System Settings state, did not configure
`adb reverse tcp:54321 tcp:54321`, did not read or write macOS `NSPasteboard`,
and did not execute a bidirectional Android/macOS product clipboard transfer.

The Android smoke is no-Host readiness evidence only. It must not be used to
claim real USB/LAN system clipboard transfer. The P0110 evidence must not be
relabeled as Xiaomi 13/fuxi evidence.

## Artifacts

- `host-readiness.json`, `host-signing-and-permissions.txt` - blocked Host
  readiness snapshot.
- `usb-smoke-preflight.json` - blocked read-only USB readiness snapshot.
- `trusted-lan-preflight.json` - blocked read-only trusted-LAN readiness
  snapshot.
- `clipboard-e2e-gate.json` - sanitized final gate output, verdict `blocked`,
  with Android smoke `pass`.
- `clipboard-e2e-gate-raw-rerun.json` - sanitized companion gate output proving
  the incomplete direct raw instrumentation rerun is rejected.
- `logs/clipboard-manager-instrumentation.log` - retained current-main 8/8
  Android ClipboardManager smoke log used by the final gate.
- `logs/clipboard-manager-raw-am-instrumentation.log` - direct no-Host raw
  instrumentation rerun that crashed and is intentionally rejected.
- `logs/adb-reverse-list-before.txt`, `logs/adb-reverse-list-after.txt` -
  read-only reverse snapshots; both are empty.
- `commands.txt` - sanitized commands used for this current-main gate refresh.
- `SHA256SUMS` - artifact checksums.
