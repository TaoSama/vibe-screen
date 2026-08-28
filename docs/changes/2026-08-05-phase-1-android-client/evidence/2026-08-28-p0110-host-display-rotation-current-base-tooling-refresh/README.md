# P0110 rotated host-display current-base tooling refresh: blocked

Date: 2026-08-28
Source base: `origin/main` at `20cd27b1d59dfcc66e28df41aba421e14b6171f4`
Branch: `codex/host-display-rotation-current-base-refresh-2026-08-28`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package refreshes the rotated physical/virtual host-display current-base
record after tightening the offline tooling. It does not claim a completed
physical or virtual rotated macOS display run.

## What changed in tooling

- Added a `make host-display-rotation-gate` entry point for the formal retained
  artifact verifier so the runbook command can be executed without hand-writing
  the Python module invocation.
- Wrote the strict Host preflight report into the evidence directory when
  generating a current-base manifest, so the manifest's `host-preflight.txt`
  references resolve inside the retained package.
- Required each inverse-touch point's `within_tolerance` flag to be true in the
  formal verifier, in addition to checking numeric `error_px <= tolerance_px`.
- Added a current-base source check to the current-base gate so clean 40-character
  repository provenance is required before a complete synthetic manifest can
  pass.
- Updated the public evidence privacy scanner to accept standard redacted serial
  placeholders such as `<redacted-adb-serial>` and
  `[redacted-device-serial]`.

## Safe preflight result

- The start/end safety checks found no `sfltool` process. No
  `/usr/bin/sfltool dumpbtm` command and no login-item diagnostic opt-in flag was
  used.
- A serial-scoped lock was acquired at
  `/tmp/vibe-screen-android-REDACTED_P0110_USB_SERIAL.lock` before the ADB
  probes and released when the probe process exited.
- The connected device identified as nubia P0110 / pacific / Android 16 / SDK
  36.
- `dev.telemachus.display` was installed, the `dev.telemachus.display.test`
  package probe returned no package path with exit code 1, and
  `adb reverse --list` retained `UsbFfs tcp:54321 tcp:54321`.
- A Host listener was visible on local TCP `54321`, but the strict Host preflight
  still failed before the acceptance run could start.

## Blockers

- `security find-identity -v -p codesigning` reported zero valid identities, so
  the stable `Vibe Screen Dev` signing identity was unavailable.
- The strict Host preflight could not prove Screen Recording, Accessibility, or
  signed Host/TCC match for the installed bundle.
- The installed Host lacked source commit/tree provenance, and this tooling
  refresh evidence was generated from a dirty working tree after the tool fix.
- No host-display rotation restoration plan was retained because no display was
  rotated.
- No physical or virtual 90/180/270 host-display run was captured, and
  `host-display-rotation.json` intentionally keeps `runs: []`.

## Gate outputs

- `host-display-rotation-gate.json` returned `status=failed`, with missing
  physical and virtual rotated host-display evidence and missing 90/180/270
  coverage for both display kinds.
- `host-display-rotation-current-base-gate.json` returned `verdict=blocked`,
  `can_close_host_display_rotation_acceptance=false`,
  `can_close_current_base_aggregate=false`, and
  `can_claim_real_device_pass=false`.
- `privacy-scan.json` returned `result=pass` for the retained public evidence.

## Evidence boundary

This is readiness evidence only. No Android install, launch, force-stop, input
injection, Host start/stop, ADB reverse mutation, or macOS display rotation was
performed in this run. The real gate remains open until a fresh device session
records both physical and virtual macOS displays at 90, 180, and 270 degrees,
with visual source orientation, stream stability, no session teardown,
original-rotation restoration, and structured four-corner plus center inverse
touch mapping in host logical-display coordinates.

## Artifacts

- `host-readiness.json` and `host-signing-and-permissions.txt` - blocked Host
  signing/TCC/source-provenance readiness, plus observed TCP `54321` listener.
- `host-preflight.txt` - strict installed Host preflight failure report retained
  inside this evidence directory by the refreshed manifest tool.
- `device-identity.txt`, `adb-devices.txt`, `adb-get-state.txt`,
  `android-package.txt`, `android-test-package.txt`, and `adb-reverse-list.txt` -
  read-only P0110 device and app state.
- `host-display-rotation.json` - intentionally empty run summary for a blocked
  readiness attempt.
- `host-display-rotation-gate.json` and
  `host-display-rotation-current-base-gate.json` - fail-closed gate summaries.
- `commands.txt`, `privacy-scan.json`, and `SHA256SUMS` - command log,
  publication scan, and checksums.
