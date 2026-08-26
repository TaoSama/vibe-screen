# Nubia P0110 USB smoke preflight current-base: blocked

Date: 2026-08-27 local time / 2026-08-26 UTC
Repository base: `origin/main` at `e94d3a051e683d2a7d6f34fd03badd1b4ef264d0`
Target serial: `<P0110_USB_SERIAL>`
Expected target identity: nubia P0110 / pacific / Android 16 / SDK 36

## Result

`make evidence-usb-smoke-preflight` exited `2` and wrote a blocked readiness
record. No shared Android device lease lock was present, so the collector ran
only explicit `adb -s <P0110_USB_SERIAL> ...` read commands and verified the
attached target as nubia / P0110 / pacific / Android 16 / SDK 36.

The device identity and ADB reverse prerequisites were ready: `adb reverse
--list` reported `UsbFfs tcp:54321 tcp:54321`, and the device matched nubia
P0110 / pacific / Android 16 / SDK 36. The `dev.telemachus.display` package was
installed, but the app process was not running and `.MainActivity` was not
foreground at collection time. The macOS side had a Vibe Screen-owned listener
on TCP `54321`, but the supported Host preflight also failed because the
installed stable-signed Host lacked source commit/tree provenance and read-only
TCC permission verification was unavailable. The preflight therefore remains
blocked and did not proceed to a live USB smoke.

This is a fail-closed readiness record only. It does not prove USB streaming,
Protocol v1 interoperability, decoder output, reconnect, input, latency, soak
duration, Host RSS no-growth, native pointer HID, physical stylus, controller
runtime, rotated host-display, login startup, headless Mac behavior, LAN,
Internet, AV1, or primary-device behavior.

## Safety boundary

The collector is read-only. It did not install or launch Android, start the
Host, create or remove ADB reverse mappings, clear logcat, inject input, modify
TCC, touch Keychain state, or modify Android app data. The retained JSON records
`safety.ran_adb=true` because the lock check was clear and every Android probe
used the explicit target serial. Public artifacts replace that serial with
`REDACTED_P0110_USB_SERIAL` or `<P0110_USB_SERIAL>`.

## Blocker

- `android_app.pids`: the Android app process was not running.
- `android_app.foreground`: the Android app was not foreground.
- `host.preflight`: macOS Host stable-signing/TCC preflight failed because the
  installed Host lacks source commit/tree provenance and read-only TCC
  permission verification was unavailable.

## Next rerun conditions

1. Install a source-bound Host build from the current commit.
2. Grant Screen Recording and Accessibility to the stable installed Host bundle
   so the read-only TCC check can verify both permissions.
3. Keep the Android device lease clear or explicitly owned, then rerun
   `make evidence-usb-smoke-preflight` with `EVIDENCE_SERIAL=<P0110_USB_SERIAL>`
   and the expected Nubia/P0110/pacific identity fields.
4. Attempt the live USB smoke only after the preflight reports `result=ready`.

## Files

- `usb-smoke-preflight.json` - structured blocked readiness result.
- `commands.txt` - redacted command ledger for the current-base preflight.
- `usb-smoke-preflight.exit` - preserved Make exit code.
- `privacy-scan.json` - generated evidence privacy scan manifest.
- `SHA256SUMS` - checksums for retained text and JSON artifacts.
