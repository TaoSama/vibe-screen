# P0110 rotated host-display acceptance: current-base blocked

Created: 2026-08-22T09:33:38Z
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial EP0110PZ0B9110300B
PR: https://github.com/TaoSama/vibe-screen/pull/262
PR branch: `codex/rotated-host-display-readiness`
PR head: `71f0a96e721fdadbfd4601568237e9a6307474c0`
Base: `origin/main` at `4dc84505e6e0a07fa1052df12bca03824f161bf6`

## Verdict

Blocked. This record is a current-base readiness snapshot only. It does not
claim a real rotated physical or virtual macOS display pass, and it does not
close the Phase 1 rotated host-display acceptance gate.

The #262 branch was already update-branched onto current `origin/main`; its
merge base is `4dc84505e6e0a07fa1052df12bca03824f161bf6`. The branch contains
the fail-closed evidence-summary gate that requires physical and virtual
display coverage at 90, 180, and 270 degrees, plus structured inverse-touch
mapping for top-left, top-right, bottom-left, bottom-right, and center.

## Current preflight facts

- `/tmp/vibe-screen-device-android.lock` was absent before ADB sampling.
- The only ADB device used was explicitly addressed as
  `adb -s EP0110PZ0B9110300B`. It reported nubia / P0110 / pacific / Android 16
  / SDK 36 with fingerprint
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- `system_profiler SPDisplaysDataType` showed the built-in Color LCD online and
  DELL U2723QE online, with DELL U2723QE reporting `Rotation: Supported`.
- `security find-identity -v -p codesigning` reported `0 valid identities
  found`.
- `python3 scripts/macos_dev_host.py preflight --install-path "/Applications/Vibe Screen.app"`
  failed because the stable `Vibe Screen Dev` codesigning identity is not
  available in the keychain.
- The read-only user TCC database query for `dev.telemachus.display` returned
  `authorization denied`, so this task could not prove Screen Recording or
  Accessibility grants for the installed Host bundle.

## Gate status

`host-display-rotation.json` intentionally contains no completed runs. Running
the offline gate with `--check-artifacts` wrote
`host-display-rotation-gate.json` with `status=failed`. The retained errors
include missing rotated physical and virtual host-display evidence and missing
physical/virtual rotation coverage for `[90, 180, 270]`.

No macOS display was rotated, no app was installed or launched, no ADB reverse
mapping was changed, and no input was injected during this current-base
readiness snapshot.

## Re-run requirement

Restore the stable `Vibe Screen Dev` signing identity and verifiable Screen
Recording plus Accessibility grants for the same installed Host bundle. Then
run the full operator checklist in
`docs/runbook/host-display-rotation-acceptance.md` during an exclusive device
window, retaining physical and virtual host-display evidence at 90, 180, and
270 degrees before re-running the offline gate.
