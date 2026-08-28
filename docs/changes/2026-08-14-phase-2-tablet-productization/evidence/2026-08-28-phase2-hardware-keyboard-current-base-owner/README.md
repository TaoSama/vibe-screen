# Phase 2 hardware-keyboard current-base owner refresh

Result: blocked. This record refreshes the Phase 2 hardware-keyboard owner on
current `origin/main` (`20cd27b1d59dfcc66e28df41aba421e14b6171f4`) and keeps
the README Phase 2 gates open.

Input summaries used by the aggregate report:

- `../2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json`
- `../2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json`
- `../2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json`
- `../2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json`
- `../2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json`
- `../2026-08-27-nubia-p0110-phase2-soak-preflight-current-base-230933/phase2-soak-readiness.json`
- `../2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json`

The hardware-keyboard input summary records `verdict=blocked` and
`can_close_hardware_keyboard_gate=false`. The child readiness bundle records the
attached Android device as nubia P0110 / pacific / Android 16 / SDK 36 with the
serial redacted to `<device-serial>`. No external Android-attached physical
keyboard was visible in `dumpsys input`. Host TCP `54321` had a listener, but
stable signed/TCC Host readiness failed because the `Vibe Screen Dev` signing
identity was unavailable.

This aggregate report now consumes the refreshed hardware-keyboard summary
instead of reporting the hardware-keyboard row as a missing gate output. It still
cannot close any README Phase 2 gate: there is no physical 8-9 inch tablet
package, the retained P0110 package is a phone substitute, the tablet gate is
insufficient, hardware-keyboard evidence is blocked, device-memory evidence is
insufficient, device-environment evidence is blocked, and recovery and tablet UI
child outputs remain unavailable.

Generation command is recorded in `phase2-aggregate-owner-command.txt`.

Validation:

- `make phase2-aggregate-owner ...` generated `phase2-aggregate-owner.json` with
  `source_baseline=origin/main 20cd27b1d59dfcc66e28df41aba421e14b6171f4`,
  `verdict=blocked`, and `can_close_readme_phase2_gates=false`.
