# P0110 rotated host-display current-base acceptance: blocked

Created: 2026-08-26T23:03:09Z from current `origin/main`
`3b2ba11e832a3618eaedfc67f92414b161423a00`.
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial
`<redacted-adb-serial>`.

## Verdict

Blocked. This record refreshes the current-base owner state for the rotated
physical/virtual Host display acceptance gate. It does not claim a completed
physical or virtual rotated macOS display run.

The existing client-local Fit/Fill and Follow Mac/90/180/270 matrix remains
supporting evidence only because it was captured with `hostRotation=0`. The
current gate still requires real macOS Host display rotation evidence for both
physical and virtual displays at 90, 180, and 270 degrees, plus structured
inverse-touch mapping for the four corners and center.

## Local Preconditions

- The checkout started clean at the same revision as `origin/main`.
- Every Android command used `adb -s <redacted-adb-serial>`.
- Read-only identity probes identified the connected Android device as nubia
  P0110 / pacific / Android 16 / SDK 36.
- `dev.telemachus.display` and `dev.telemachus.display.test` were installed on
  the P0110 at sampling time.
- The installed `/Applications/Vibe Screen.app` has bundle identifier
  `dev.telemachus.display` and codesign Authority `Vibe Screen Dev`, but
  `security find-identity -v -p codesigning` returned `0 valid identities
  found`, so the required stable signing identity was not visible to this
  shell.
- `scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"`
  failed closed. The report could not prove source provenance for the installed
  Host bundle, Screen Recording, Accessibility, or signing/TCC match.
- `host-displays-before.txt` records the local display inventory before any
  rotation attempt. It shows a built-in display and an external DELL U2723QE
  whose rotation is reported as supported, but no display rotation was performed
  because the Host signing/TCC preflight failed first.

## Gate Status

`host-display-rotation.json` intentionally contains no completed runs. The
formal evidence gate therefore returns `status=failed` with missing physical and
virtual host-display evidence and missing 90/180/270 coverage for both display
kinds.

The aggregate current-base gate returns `verdict=blocked`,
`can_close_host_display_rotation_acceptance=false`,
`can_close_current_base_aggregate=false`, and
`can_claim_real_device_pass=false`. The Make target exits non-zero for this
blocked verdict by design; this evidence treats that non-zero exit as the
expected fail-closed result, not as a pass.

## Commands

The retained command list is in `commands.txt`. The only Android probes were
read-only identity/package checks using the explicit P0110 serial. This record
did not install or launch the Android client, mutate ADB reverse mappings,
rotate macOS displays, start a Host stream, or inject input.

## Next Attempt

Make the `Vibe Screen Dev` signing identity visible to `security find-identity`,
rebuild/install the Host with source commit/tree provenance, and obtain provable
Screen Recording plus Accessibility grants for the same installed bundle. Then
run the `docs/runbook/host-display-rotation-acceptance.md` sequence under an
exclusive device window. The gate can close only after retained physical and
virtual 90/180/270 real-device runs pass both `host_display_rotation_gate
--check-artifacts` and the current-base aggregate gate.
