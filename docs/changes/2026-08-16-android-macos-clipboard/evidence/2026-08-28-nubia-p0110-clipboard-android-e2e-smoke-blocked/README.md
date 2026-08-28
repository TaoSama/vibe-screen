# Nubia P0110 Clipboard Android E2E Smoke Blocked

Date: 2026-08-28 (local, Asia/Shanghai; UTC 2026-08-27T16:34:10Z)
The evidence directory and README use the local collection date
(2026-08-28 Asia/Shanghai). Machine-generated timestamps inside the
artifacts (host-readiness.json generated_at, usb-smoke-preflight.json
collected_at, trusted-lan-preflight.json collected_at) are emitted in
UTC and therefore read 2026-08-27. Both refer to the same run.
Source base: `origin/main` at `27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`
Branch: `codex/clipboard-android-e2e-smoke`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package records a fail-closed current-base attempt for the real Android
`ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 USB/LAN E2E gate. It
does not prove either clipboard transfer direction.

## What Passed

- The run started from clean `origin/main` and recorded no `sfltool` process
  before evidence collection. The Host readiness command did not opt into the
  login-item diagnostic and did not run `/usr/bin/sfltool dumpbtm`.
- The target device identity matched nubia P0110 / pacific / Android 16 / SDK
  36. All device commands were run while holding
  `/tmp/vibe-screen-android-REDACTED_P0110_USB_SERIAL.lock`, and every ADB
  command used `adb -s REDACTED_P0110_USB_SERIAL`.
- Debug and androidTest APKs built and installed on the device.
- Android local `ClipboardManagerInstrumentedTest` passed on device with
  `OK (3 tests)`. This proves only foreground Android system-clipboard access
  on the P0110.
- Android-focused clipboard JVM tests passed locally.
- Android debug and androidTest APK builds passed locally.
- Evidence-tool and repository privacy unit tests passed locally after adding the
  held-lock and privacy-safe-literal coverage.
- The `clipboard-e2e-gate` aggregator ran and preserved the blocked verdict
  instead of converting local/offline readiness into E2E proof.

## Blockers

- macOS Host readiness is blocked by missing stable signing identity, missing
  installed Host source provenance, read-only TCC verification failure, no Host
  listener on TCP 54321, missing virtual HID entitlement, and unverified login
  item state.
- USB preflight remains blocked because the Android app was not foreground, the
  Mac Host was not listening on TCP 54321, and Host stable-signing/TCC preflight
  failed before a real product clipboard run could start. ADB reverse was
  configured and device identity matched P0110.
- Trusted LAN preflight remains blocked because the Android device Wi-Fi is not
  associated, `wlan0` has no IPv4 route to the Mac LAN candidate, and Host
  stable signing is blocked.
- No retained product E2E record exists for either Android `ClipboardManager` ->
  macOS `NSPasteboard` or macOS `NSPasteboard` -> Android `ClipboardManager`.

## Evidence Boundary

The Android instrumentation result proves only local Android system clipboard
access on this P0110. The USB/LAN preflight files prove readiness state only.
They did not start a signed Host/device clipboard session, did not exercise the
Protocol v1 clipboard UI actions, did not write the remote system pasteboard,
and did not compare final marker text across both systems.

The related 1 MiB ceiling, old-peer fallback, and clipboard deny-wins behavior
remain covered by offline Android/Mac/protocol tests and prior source audit, not
by this real product smoke. The real gate remains open until retained evidence
shows both transfer directions in a real Protocol v1 USB or trusted-LAN session
with explicit user action, source system clipboard read, remote system clipboard
write, and final marker match.

## Artifacts

- `clipboard-e2e-gate.json` - sanitized gate output, verdict `blocked`.
- `android-clipboard-instrumentation.txt` - sanitized local Android
  `ClipboardManagerInstrumentedTest` summary.
- `device-info.json` - sanitized P0110 identity.
- `host-readiness.json` - shared Host readiness JSON, verdict `blocked`.
- `usb-smoke-preflight.json` - USB readiness JSON, verdict `blocked`.
- `trusted-lan-preflight.json` - trusted-LAN readiness JSON, verdict `blocked`.
- `commands.txt` - sanitized commands used for this current-base run.
- `pgrep-sfltool.txt` / `.exit` - startup safety check output showing no
  retained `sfltool` process.
- `android-focused-jvm-tests.txt` / `.exit` - local Android clipboard JVM test
  output, exit 0.
- `android-apk-build.txt` / `.exit` - local debug and androidTest APK build
  output, exit 0.
- `mac-clipboard-xctest.txt` / `.exit` - local Mac clipboard XCTest attempt,
  exit 1 due to the local Command Line Tools environment lacking `XCTest`.
- `evidence-tool-unittest.txt` / `.exit` - focused evidence tool unit tests,
  exit 0.
- `repository-privacy-unittest.txt` / `.exit` - repository privacy unit tests,
  exit 0.
- `privacy-scan.json` - public evidence privacy scan.
- `SHA256SUMS` - artifact checksums.
