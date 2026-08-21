# Phase 2 gate readiness smoke

This evidence record verifies the Phase 2 tablet gate tooling only. It does not
claim a physical 8-9 inch tablet run, stand-mounted charging stability,
controlled thermal-load behavior, power stability, recovery acceptance, or an
eight-hour productization pass.

## Device Identity

The manifest was generated from the retained
`../2026-08-20-nubia-p0110-readiness/device-info.json` record. That record
identifies the attached Android substitute as:

- Manufacturer: nubia
- Model: P0110
- Codename: pacific
- Android release: 16
- ADB serial: EP0110PZ0B9110300B

The manifest intentionally uses `PHASE2_DEVICE_CLASS=android_substitute`. This
device must not be relabeled as Xiaomi 13/fuxi or as physical 8-9 inch tablet
evidence.

## Commands

No ADB command was run for this smoke. If a future run uses the Nubia P0110, all
ADB commands must use `adb -s EP0110PZ0B9110300B ...`.

```bash
cp ../2026-08-20-nubia-p0110-readiness/device-info.json device-info.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m \
  vibescreen_evidence.phase2_tablet_manifest \
  --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json \
  --device-info docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/device-info.json \
  --device-class android_substitute \
  --stand-setup "tooling smoke only; no physical stand-mounted charging run" \
  --charger "not tested in this smoke" \
  --cable-or-dock "not tested in this smoke" \
  --ambient-temperature-celsius 24 \
  --transport usb \
  --video-preferences "synthetic exact-window fixture only" \
  --thermal-limit-status 2 \
  --battery-temperature-limit-celsius 45 \
  --maximum-net-battery-drain-percent 5 \
  --recovery-scenarios "background_foreground,transport_reconnect" \
  --host-identity "not tested in this smoke" \
  --host-build "not tested in this smoke" \
  --apk-sha256 "not-tested" \
  --notes "Tooling smoke only. Uses retained Nubia P0110/pacific Android 16 identity as android_substitute and does not claim physical 8-9 inch tablet, stand-mounted charging, thermal-load, power, recovery, or eight-hour acceptance." \
  -- make soak-8h EVIDENCE_SERIAL=EP0110PZ0B9110300B EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m \
  vibescreen_evidence.phase2_tablet_gate \
  --report docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/exact-window-report.json \
  --manifest docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json \
  --evidence-dir docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness \
  --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json
```

## Result

`phase2-tablet-gate.json` reports `verdict=insufficient`. The important
blocking reason is `manifest.physical_8_9_inch_tablet`, because this smoke uses
the Nubia P0110/pacific Android 16 phone substitute. The report also lists the
missing raw evidence-package artifacts that a real run must provide before this
gate can pass.

`exact-window-report.json` is a synthetic tool fixture used only to exercise the
gate evaluator. It is not an actual eight-hour device sample series.

## Artifacts

- `device-info.json` - retained Nubia P0110/pacific Android 16 identity.
- `phase2-tablet-manifest.json` - manifest generated with `android_substitute`.
- `exact-window-report.json` - synthetic stable report fixture.
- `phase2-tablet-gate.json` - package-aware gate output; expected
  `insufficient`.
- `phase2-tablet-gate-command.json` - stdout from the gate command.
- `SHA256SUMS` - checksum manifest for this readiness package.
