# P0110 rotated host-display current-base readiness: blocked

Date: 2026-08-28
Source base: `origin/main` at `27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`
Branch: `codex/rotated-host-display-readiness-2026-08-28`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package records a fail-closed current-base attempt for the rotated
physical/virtual host-display acceptance gate. It does not claim a completed
physical or virtual rotated macOS display run.

## What Passed

- The pre-run safety check found no `sfltool` process, and no `sfltool` opt-in
  command was executed.
- The P0110 device lock was acquired before every ADB probe, every ADB command
  used `adb -s REDACTED_P0110_USB_SERIAL`, and the lock was released after the
  read-only sample.
- The connected device identified as nubia P0110 / pacific / Android 16 / SDK
  36.
- `dev.telemachus.display` and `dev.telemachus.display.test` were installed,
  and `adb reverse --list` retained `UsbFfs tcp:54321 tcp:54321`.
- The existing client-local Fit/Fill and Follow Mac/90/180/270 matrix remains
  supporting evidence only and was not substituted for host-display rotation.

## Blockers

- Host preflight failed before any rotation run because the stable
  `Vibe Screen Dev` codesigning identity was not visible in the keychain.
- Screen Recording, Accessibility, and the signed Host/TCC match could not be
  proven from the read-only preflight.
- No Host listener was observed on TCP port `54321`, so the Android client could
  not establish a Protocol v1 stream for display rotation or touch mapping.
- No host-display rotation restoration plan was retained because no display was
  rotated.
- No physical or virtual 90/180/270 host-display run was captured, and
  `host-display-rotation.json` intentionally keeps `runs: []`.

## Evidence Boundary

This is readiness evidence only. No Android install, launch, force-stop,
input injection, Host start/stop, ADB reverse mutation, or macOS display
rotation was performed in this run. The real gate remains open until a fresh
device session records both physical and virtual macOS displays at 90, 180, and
270 degrees, with visual source orientation, stream stability, no session
teardown, original-rotation restoration, and structured four-corner plus center
inverse touch mapping in host logical-display coordinates.

The local readiness command also reports the repository as dirty because this
evidence package was being generated in the worktree. That is a provenance
blocker for a passing run, but the operational blocker for this attempt was
already reached earlier: stable Host signing/TCC and Host listener readiness
were not available.

## Gate Outputs

- `host-display-rotation-gate.json` returned `status=failed`, with missing
  physical and virtual rotated host-display evidence and missing 90/180/270
  coverage for both display kinds.
- `host-display-rotation-current-base-gate.json` returned `verdict=blocked`,
  `can_close_host_display_rotation_acceptance=false`,
  `can_close_current_base_aggregate=false`, and
  `can_claim_real_device_pass=false`.
- `privacy-scan.json` returned `result=pass` for the retained public evidence.

## Artifacts

- `host-readiness.json` and `host-signing-and-permissions.txt` - blocked Host
  signing/TCC/listener readiness.
- `host-preflight.txt` - strict installed Host preflight failure report.
- `device-identity.txt`, `adb-devices.txt`, `adb-get-state.txt`,
  `android-package.txt`, `android-test-package.txt`, `adb-reverse-list.txt`,
  and `android-foreground.txt` - read-only P0110 device and app state.
- `host-display-rotation.json` - intentionally empty run summary for a blocked
  readiness attempt.
- `host-display-rotation-gate.json` and
  `host-display-rotation-current-base-gate.json` - fail-closed gate summaries.
- `commands.txt`, `privacy-scan.json`, and `SHA256SUMS` - command log,
  publication scan, and checksums.
