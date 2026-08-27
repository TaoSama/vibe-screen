# Nubia P0110 File Transfer Android Smoke Blocked

Date: 2026-08-28
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial: redacted from public evidence; device operations used the retained
Nubia P0110 handset identity only.
Source branch: codex/file-transfer-android-smoke-readiness
Starting point: clean origin/main commit 27d2b0e493e807ae439fbd43b06b4c2f0ce9c503

## Verdict

Status: blocked. Gate closed: false.

The dedicated `file-transfer-android-smoke` gate records that the README
single-file-transfer smoke cannot close from this run. The P0110 identity
matched nubia P0110 / pacific / Android 16 / SDK 36, ADB reverse for TCP 54321
was present, and the Android app was installed. The Android app was not running
or foreground, and no Protocol v1 single-file transfer offer/request/content
exchange was observed.

## Blockers

- The Android app was not running or foreground during the clean-commit
  readiness rerun.
- The macOS Host was not listening on TCP 54321.
- Stable Host signing/TCC readiness failed because the `Vibe Screen Dev`
  codesign identity was unavailable.
- The installed Host lacks source commit/tree provenance for this checkout.
- TCC permissions could not be verified read-only.
- Trusted-LAN preflight, Android file-transfer instrumentation output,
  bidirectional product E2E evidence, and cancel/cleanup evidence are missing.

## Safety

- `pgrep -x sfltool || true` returned no residual `sfltool` process before
  device readiness work.
- The default Host readiness path skipped the optional login-item diagnostic,
  and no `sfltool` opt-in diagnostic was used.
- Device probes were run under the explicit P0110 coordination lock and used
  `adb -s` for the retained serial; public evidence redacts the raw serial.
- The evidence is readiness-only and must not be cited as Android/macOS
  file-transfer acceptance.

## Files

- `blocked.json` is the fail-closed aggregate gate output.
- `usb-smoke-preflight.json` is the read-only USB readiness probe.
- `host-readiness.json` is the shared Host prerequisite readiness result.
- `host-signing-and-permissions.txt` is the human-readable Host preflight
  excerpt used by the USB readiness probe.
