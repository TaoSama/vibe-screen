# 2026-08-22 Nubia P0110 device-environment blocked preflight

This evidence is a non-destructive Phase 2 device-environment readiness record.
It does not close the stand-mounted charging stability, thermal-load, or
power-source stability gates.

## Device identity

- Manufacturer/model: nubia P0110
- Codename: pacific
- Android: 16 / SDK 36
- ADB serial: `EP0110PZ0B9110300B`
- Device class: Android phone substitute only

This run must not be relabeled as Xiaomi 13/fuxi evidence or as physical
8-9 inch tablet evidence.

## Commands

The shared Android lock was checked before using ADB, and no existing lock was
present. All ADB commands used the explicit target serial.

```bash
adb -s EP0110PZ0B9110300B get-state > adb-get-state.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.device_info \
  --serial EP0110PZ0B9110300B \
  --package dev.telemachus.display \
  --output device-info.json
adb -s EP0110PZ0B9110300B shell getprop > device.txt
adb -s EP0110PZ0B9110300B shell dumpsys battery > adb-battery-readonly.txt
adb -s EP0110PZ0B9110300B shell dumpsys power > adb-power-readonly.txt
adb -s EP0110PZ0B9110300B shell dumpsys thermalservice \
  > thermal-readonly.txt 2> thermal-readonly.err
make phase2-device-environment-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-22-nubia-p0110-device-environment-blocked
```

## Observed read-only state

- ADB state: `device`
- Battery: level 100, status 5/full, AC powered true, USB powered false
- Power manager: `mIsPowered=true`, `mPlugType=1`, `mBatteryLevel=100`
- Thermal service: `Thermal Status: 1`, battery temperature 34.0 C from HAL

These are instantaneous readiness observations only. They do not prove stable
stand-mounted charging, power-source stability, or thermal behavior under load.

## Gate result

`phase2-device-environment-summary.json` reports:

- `verdict=blocked`
- `can_close_device_environment_gates=false`
- `does_not_close_eight_hour_stream_gate=true`

Blocking reasons:

- no physical 8-9 inch tablet was observed;
- no stand-mounted charging setup was observed;
- no eight-hour environment window was retained;
- no controlled thermal-load step was performed.

## Artifacts

- `device-lock.txt`
- `adb-get-state.txt`
- `device-info.json`
- `device-info-command.txt` / `device-info-command.err`
- `device.txt`
- `adb-battery-readonly.txt`
- `adb-power-readonly.txt`
- `thermal-readonly.txt` / `thermal-readonly.err`
- `phase2-device-environment-observations.json`
- `phase2-device-environment-summary.json`
- `SHA256SUMS`

Future physical-tablet closure must follow the Phase 2 runbook, use a real
8-9 inch tablet in its stand-mounted charged setup, run the full environment
window, include a safe controlled thermal-load step, and retain the raw
battery, power, thermal, and UI/platform comparison artifacts in the same
evidence directory.
