# Nubia P0110 Clipboard E2E Current-Base Blocked

Date: 2026-08-27
Source base: `origin/main` at `32b05030cf4cff54029d9bffd4c9dd0cb7e1d6e3`
Branch: `codex/clipboard-protocol-e2e`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package records a fail-closed current-base attempt for the real Android
`ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 USB/LAN E2E gate. It
does not prove either clipboard transfer direction.

## What Passed

- The target device identity matched nubia P0110 / pacific / Android 16 / SDK
  36.
- ADB reverse for the USB smoke path was present, the Android app was launched
  foreground, and a loopback Host listener was observed.
- Android local `ClipboardManagerInstrumentedTest` passed on device with
  `OK (3 tests)`.
- The new `clipboard-e2e-gate` aggregator ran and preserved the blocked verdict
  instead of converting local/offline readiness into E2E proof.

## Blockers

- macOS Host readiness is blocked by missing stable signing identity, missing
  installed Host source provenance, read-only permission verification failure,
  and missing virtual HID entitlement.
- USB preflight remains blocked because the Host stable-signing/permission
  preflight failed before a real product clipboard run could start.
- Trusted LAN preflight remains blocked because the Android device Wi-Fi is not
  associated, `wlan0` has no IPv4 route to the Mac LAN candidate, and Host
  stable signing is blocked.
- No retained product E2E record exists for either
  Android `ClipboardManager` -> macOS `NSPasteboard` or macOS `NSPasteboard` ->
  Android `ClipboardManager`.

## Evidence Boundary

The Android instrumentation result proves only local Android system clipboard
access on this P0110. The USB/LAN preflight files prove readiness state only.
They did not start a signed Host/device clipboard session, did not exercise the
Protocol v1 clipboard UI actions, did not write the remote system pasteboard,
and did not compare final marker text across both systems.

The real gate remains open until retained evidence shows both transfer
directions in a real Protocol v1 USB or trusted-LAN session with explicit user
action, source system clipboard read, remote system clipboard write, and final
marker match.

## Artifacts

- `clipboard-e2e-gate.json` - sanitized gate output, verdict `blocked`.
- `android-clipboard-instrumentation.txt` - sanitized local Android
  `ClipboardManagerInstrumentedTest` summary.
- `commands.txt` - sanitized commands used for this current-base run.
- `privacy-scan.json` - public evidence privacy scan.
- `SHA256SUMS` - artifact checksums.
