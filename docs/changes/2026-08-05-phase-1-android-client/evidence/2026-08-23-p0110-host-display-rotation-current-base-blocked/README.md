# P0110 rotated host-display current-base acceptance: blocked

Created: 2026-08-23T05:34:47Z; current-base manifest refreshed at
2026-08-25T12:57:06Z after rebasing this owner change onto
`c93a05069ede078a181e343497214d8bf9021853`.
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial <redacted-adb-serial>
Repository: source manifest sampled clean branch head
`88ff8dc74fe44ce2be392c502ea7de05a7eb375e`, whose parent is current
`origin/main` at `c93a05069ede078a181e343497214d8bf9021853`. The final PR
head changes after this sample only to retain regenerated gate outputs, this
README, `commands.txt`, `repository-state.txt`, and `SHA256SUMS`.
Owner: draft PR #262 (`codex/rotated-host-display-readiness`)

## Verdict

Blocked. This record establishes the current-base owner and keeps the rotated
physical/virtual host-display acceptance gate open. It does not claim a
completed physical or virtual rotated macOS display run.

The existing client-local Fit/Fill and Follow Mac/90/180/270 matrix remains
supporting evidence only because it was captured with `hostRotation=0`. The
current-base gate requires real macOS Host display rotation evidence for both
physical and virtual displays at 90, 180, and 270 degrees, plus structured
inverse-touch mapping for the four corners and center.

## Local Preconditions

- The shared Android coordination locks were absent before sampling.
- Every Android command in this record used `adb -s <redacted-adb-serial>`.
- Read-only identity probes identified the device as nubia P0110 / pacific /
  Android 16 / SDK 36, with fingerprint
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- The refreshed `android-package.txt` proves `dev.telemachus.display` and
  `dev.telemachus.display.test` are installed on the P0110. This removes the
  earlier package-presence blocker, but no app launch or stream run was
  performed.
- `codesigning-identities.txt` reports `0 valid identities found`.
- The installed `/Applications/Vibe Screen.app` has bundle identifier
  `dev.telemachus.display` and Authority `Vibe Screen Dev`, but the stable
  signing identity was not visible to the current keychain, so
  `scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"`
  failed closed.
- This task did not collect TCC database rows, so Screen Recording and
  Accessibility grants could not be proven from this task.
- `host-displays-before.txt` records the local displays before any attempted
  host rotation. No display rotation was performed by this task.

## PR State

- PR #262 was open and draft, head `codex/rotated-host-display-readiness` at
  `dd1e33327344c0234c28c66807d2dbc9d7f4653b`, and is the current-base owner
  for this gate.
- PR #272 was already merged and only affects Android display-selection UI
  confirmation behavior.
- PR #243 remained open but is scoped to disconnected settings opacity and is
  unrelated to rotated Host display acceptance.

## Gate Status

`host-display-rotation.json` intentionally contains no completed runs. The
offline evidence gate returned `status=failed` with missing physical and
virtual host-display evidence and missing 90/180/270 coverage for both display
kinds.

The refreshed aggregate current-base gate returned `verdict=blocked`,
`can_close_host_display_rotation_acceptance=false`,
`can_close_current_base_aggregate=false`, and
`can_claim_real_device_pass=false`. The Make target exits non-zero for this
blocked verdict by design; this evidence treats that non-zero exit as the
expected fail-closed result, not as a pass.

## Commands

The retained command list is in `commands.txt`. The only device probes were
read-only identity/package checks using the explicit P0110 serial. This record
did not install or launch the Android client, mutate ADB reverse mappings,
rotate macOS displays, start a Host run, or inject input.

## Next Attempt

Restore a visible `Vibe Screen Dev` signing identity and provable TCC grants for
the installed Host, then run `docs/runbook/host-display-rotation-acceptance.md`
under an exclusive device window with the installed P0110 client. The gate can
close only after retained physical and virtual 90/180/270 real-device runs pass
both `host_display_rotation_gate --check-artifacts` and the current-base
aggregate gate.
