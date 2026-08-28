# Phase 2 tablet current-base owner readiness

Result: `blocked`. This record refreshes the Phase 2 tablet sustained-use
current-base owner on `origin/main` commit
`e90463e5d24ee055686a9b6d3a1acd02c616b81b`. It consumes the latest Nubia
P0110 soak preflight plus the retained device-environment, hardware-keyboard,
and macOS login/headless blocked summaries. It does not close any README Phase 2
tablet gate.

Input summaries used by the aggregate report:

- `../2026-08-28-nubia-p0110-phase2-soak-preflight-current-base/phase2-tablet-manifest.json`
- `../2026-08-28-nubia-p0110-phase2-soak-preflight-current-base/phase2-soak-readiness.json`
- `../2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json`
- `../2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json`
- `../2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json`

The source tablet manifest records nubia P0110 / pacific / Android 16 / SDK 36
as `android_substitute`. The aggregate report records this as substitute
readiness only and explicitly rejects it as physical 8-9 inch tablet evidence.

The aggregate verdict remains blocked because no physical 8-9 inch tablet
evidence package exists, no package-aware tablet gate pass was supplied, the
soak-readiness input does not provide a close signal, the retained
device-environment and hardware-keyboard summaries are blocked, the
login/headless summary is blocked, and tablet UI, recovery, and device-memory
current-base summaries were not supplied to this aggregate.

Generation command:

```bash
make phase2-aggregate-owner \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-phase2-tablet-current-base-owner \
  PHASE2_TABLET_MANIFEST=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-phase2-soak-preflight-current-base/phase2-tablet-manifest.json \
  PHASE2_SOAK_READINESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-phase2-soak-preflight-current-base/phase2-soak-readiness.json \
  PHASE2_HARDWARE_KEYBOARD=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json \
  PHASE2_DEVICE_ENVIRONMENT=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json \
  PHASE2_LOGIN_HEADLESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json
```

Validation:

- `make phase2-tablet-soak-preflight ...` against `<device-serial>`: exit
  `2`, expected blocked readiness.
- `make phase2-tablet-preflight ...`: exit `2`, expected blocked bundle
  verifier.
- `make phase2-aggregate-owner ...`: exit `0`, generated
  `phase2-aggregate-owner.json` with `verdict=blocked` and
  `can_close_readme_phase2_gates=false`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest
  tools.tests.test_phase2_tablet_soak tools.tests.test_phase2_tablet_preflight
  tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `shasum -a 256 -c SHA256SUMS`
