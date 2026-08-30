# Nubia P0110 clipboard E2E current-base blocked evidence

Date: 2026-08-30 (local, Asia/Shanghai; UTC 2026-08-30T07:08Z)
Source base: `origin/main` at `87e16d8bea4446c1ca449045678f1bafc7fd6cb2`
Branch: `codex/clipboard-e2e-p0110-usb-20260830`
Device: nubia P0110 / pacific / Android 16 / API 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package records a fail-closed current-base attempt for the real Android
`ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 USB/LAN E2E gate. It
does not prove either clipboard transfer direction and must not be treated as
Xiaomi 13/fuxi evidence.

## What Passed

- The run started from `origin/main` HEAD `87e16d8be` and recorded no `sfltool`
  process before collection. The Host readiness command did not opt into the
  login-item diagnostic and did not run `/usr/bin/sfltool dumpbtm`.
- The target device matched nubia P0110 / pacific / Android 16 / API 36 while
  holding `/tmp/vibe-screen-android-REDACTED_P0110_USB_SERIAL.lock`; ADB
  commands used `adb -s REDACTED_P0110_USB_SERIAL`.
- Current-source Android debug and androidTest APKs built and installed on the
  device.
- Android local `ClipboardManagerInstrumentedTest` passed on device with `OK
  (3 tests)`. This proves only foreground Android system-clipboard access on
  this P0110.
- The `clipboard-e2e-gate` aggregator preserved the blocked verdict instead of
  converting local/offline readiness into E2E proof.

## Blockers

- Host readiness is blocked by missing stable `Vibe Screen Dev` signing
  identity, broken installed Host bundle seal inspection, no Host listener on
  TCP `54321`, missing virtual HID entitlement, and unverified login item state.
- USB preflight is blocked because the Mac Host is not listening on TCP
  `54321` and Host stable-signing/TCC preflight failed before a strict USB
  smoke could be admitted.
- Trusted-LAN preflight is blocked because the Android device Wi-Fi is not
  associated, `wlan0` is down without an IPv4 route to the Mac LAN candidate,
  and Host stable signing is blocked.
- No retained product E2E record exists for either Android `ClipboardManager` ->
  macOS `NSPasteboard` or macOS `NSPasteboard` -> Android `ClipboardManager`.

## Evidence Boundary

The Android local instrumentation result proves foreground Android system
clipboard access on this P0110 only. The USB/LAN preflight files prove
readiness state only. This run did not start a signed Host/device Proto v1
clipboard session, did not exercise the clipboard UI actions, did not write the
remote system pasteboard, and did not compare final marker text across both
systems.

Offline, synthetic, local, or preflight-only evidence is explicitly marked as
insufficient for closing the real Android/macOS system-pasteboard gate. The
1 MiB ceiling, old-peer fallback, and clipboard deny-wins behavior remain
offline/protocol evidence only for this run.

## Artifacts

- `source-baseline.txt` - branch and HEAD snapshot.
- `pgrep-sfltool.txt` / `.exit` - startup safety check output showing no
  retained `sfltool` process.
- `pgrep-sfltool-end.txt` / `.exit` - final safety check output showing no
  retained `sfltool` process after collection.
- `host-readiness.json`, `host-signing-and-permissions.txt` - blocked Host
  readiness snapshot.
- `usb-smoke-preflight.json`, `usb-host-preflight.txt` - blocked USB preflight.
- `trusted-lan-preflight.json` - blocked trusted-LAN preflight.
- `android-current-base-build-jvm.txt` / `.exit` - Android current-source build
  plus focused clipboard JVM tests.
- `android-app-apk-install.txt`, `android-test-apk-install.txt` - APK install
  logs.
- `android-clipboard-instrumentation.txt` / `.exit` - local Android
  `ClipboardManagerInstrumentedTest` summary, exit 0.
- `clipboard-e2e-gate.json` - sanitized gate output, verdict `blocked`.
- `commands.txt` - sanitized commands used for this current-base run.
- `privacy-scan.json` - repository privacy scan manifest.
- `SHA256SUMS` - artifact checksums.
