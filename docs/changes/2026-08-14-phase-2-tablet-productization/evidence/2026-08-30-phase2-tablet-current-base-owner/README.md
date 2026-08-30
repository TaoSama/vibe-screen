# Phase 2 tablet sustained-use current-base owner readiness

Result: `blocked`. This record refreshes the Phase 2 tablet sustained-use and
physical 8-9 inch tablet current-base owner on `origin/main` commit
`8626c760c0a2c9a519bef38bbf0d1725401f3e79`. It consumes the 2026-08-29 Nubia
P0110 soak preflight plus the retained device-environment, hardware-keyboard,
and macOS login/headless blocked summaries. It does not close any README Phase 2
tablet gate.

This refresh also tightens the final bundle preflight:
`phase2-tablet-preflight` now requires the physical-tablet bundle to include a
passing `soak-8h/phase2-device-memory-gate.json`, a passing
`soak-8h/phase2-device-environment-summary.json` with both stand-charging and
device-environment close signals, and a complete
`phase2-device-environment-observations.json`. A Nubia P0110/pacific phone
substitute remains explicitly rejected as formal tablet evidence and cannot
satisfy this preflight.

Input summaries used by the aggregate report:

- `../2026-08-29-nubia-p0110-phase2-soak-preflight-current-base/phase2-tablet-manifest.json`
- `../2026-08-29-nubia-p0110-phase2-soak-preflight-current-base/phase2-soak-readiness.json`
- `../2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json`
- `../2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json`
- `../2026-08-29-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json`

The source tablet manifest records nubia P0110 / pacific / Android 16 / SDK 36
as `android_substitute`. The aggregate report records this as substitute
readiness only and explicitly rejects it as physical 8-9 inch tablet evidence.

The aggregate verdict remains blocked because no physical 8-9 inch tablet
evidence package exists, no package-aware tablet gate pass was supplied, the
soak-readiness input does not provide a close signal, the retained
device-environment and hardware-keyboard summaries are blocked, the
login/headless summary is blocked, and tablet UI, recovery, and device-memory
current-base summaries were not supplied to this aggregate.

Generation command is in `phase2-aggregate-owner-command.txt`.

Validation:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `make phase2-aggregate-owner ...`: exit `0`, generated
  `phase2-aggregate-owner.json` with `verdict=blocked`,
  `source_baseline=origin/main 8626c760c0a2c9a519bef38bbf0d1725401f3e79`,
  and `can_close_readme_phase2_gates=false`.
- `shasum -a 256 -c SHA256SUMS`
- `pgrep -x sfltool || true` start/end outputs were captured as empty files.
  No `/usr/bin/sfltool dumpbtm` command was run and no login-item diagnostic
  opt-in flag was used.

Still requires human hardware conditions before the README gate can close:

- a physical 8-9 inch tablet identity with stand-mounted charging setup;
- real portrait/landscape tablet sustained-use UI and orientation evidence;
- live foreground/background and transport interruption recovery;
- a stable signed/TCC-ready Host with login/headless acceptance if that row is
  in scope;
- physical stylus and hardware-keyboard workflow passes where required;
- an uninterrupted eight-hour sustained-stream run with device-memory and
  device-environment gate passes;
- the aggregate report must then consume the package-aware tablet gate pass and
  still report `can_close_readme_phase2_gates=true`.
