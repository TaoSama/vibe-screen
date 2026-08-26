# 2026-08-25 P0110 device-environment readiness

Result: `blocked`. This record is a current-base smoke for the Phase 2
stand-mounted charging, thermal-load, and power environment gate. It does not
close any README Phase 2 tablet gate.

Collection date is 2026-08-25 in the local Asia/Shanghai environment
(`date` reported 2026-08-25 03:41 CST; the simultaneous UTC date was
2026-08-24). The evidence directory uses the repository's local collection
date, not the UTC calendar date.

## Device

- Serial: `<adb-serial redacted>`
- Identity: nubia P0110 / pacific / Android 16 / SDK 36
- Device class: `android_substitute`
- Evidence role: phone substitute readiness only; not 8-9 inch tablet evidence

## Observed state

- Android device lock was checked before collection;
  `device-lock-check-exit.txt` records exit code `0`.
- `device-info.json` records manufacturer `nubia`, model `P0110`, codename
  `pacific`, Android release `16`, SDK `36`, and ABI `arm64-v8a`.
- `adb-battery-before.txt` and `adb-battery-after.txt` record AC powered
  `true`, Dock powered `false`, level `100`, status `5` (`FULL`), voltage
  about `4435` mV, and battery temperature `320` tenths C.
- `adb-power-before.txt` and `adb-power-after.txt` record `mIsPowered=true`,
  `mPlugType=1`, `mBatteryLevel=100`, and `mDockState=0`.
- `thermal-before.txt` and `thermal-after.txt` record `Thermal Status: 0`;
  battery temperature samples were visible in the retained dumps.
- `screenshots/p0110-current-screen.png` is a current-screen diagnostic only;
  it is not a sustained-use card pass, landscape pass, or formal tablet UI
  artifact.

## Blockers

- No physical 8-9 inch tablet was available.
- No stand-mounted tablet setup, charger/dock mount, or cable stability
  observation was available.
- No eight-hour environment window, `soak-8h/samples.jsonl`, Host telemetry,
  or exact-window report was collected.
- No controlled thermal-load or thermal recovery observation was performed.
- The P0110 readiness snapshots cannot be relabeled as Xiaomi/fuxi evidence or
  physical-tablet evidence.

## Commands

The raw device snapshots were collected with an explicit redacted serial, using
commands equivalent to:

```bash
EVIDENCE_SERIAL="<adb-serial>"
EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness
make evidence-device-info \
  EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
  EVIDENCE_DIR="$EVIDENCE_DIR"
adb -s "$EVIDENCE_SERIAL" shell getprop > "$EVIDENCE_DIR/device.txt"
adb -s "$EVIDENCE_SERIAL" shell dumpsys battery > "$EVIDENCE_DIR/adb-battery-before.txt"
adb -s "$EVIDENCE_SERIAL" shell dumpsys power > "$EVIDENCE_DIR/adb-power-before.txt"
adb -s "$EVIDENCE_SERIAL" shell dumpsys thermalservice > "$EVIDENCE_DIR/thermal-before.txt" 2> "$EVIDENCE_DIR/thermal-before.err"
adb -s "$EVIDENCE_SERIAL" shell screencap -p /sdcard/p0110-current-screen.png
adb -s "$EVIDENCE_SERIAL" pull /sdcard/p0110-current-screen.png "$EVIDENCE_DIR/screenshots/p0110-current-screen.png"
adb -s "$EVIDENCE_SERIAL" shell dumpsys battery > "$EVIDENCE_DIR/adb-battery-after.txt"
adb -s "$EVIDENCE_SERIAL" shell dumpsys power > "$EVIDENCE_DIR/adb-power-after.txt"
adb -s "$EVIDENCE_SERIAL" shell dumpsys thermalservice > "$EVIDENCE_DIR/thermal-after.txt" 2> "$EVIDENCE_DIR/thermal-after.err"
```

Generate the fail-closed summary with:

```bash
make phase2-device-environment-gate \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness
```

Expected result: nonzero exit with
`soak-8h/phase2-device-environment-summary.json` reporting `verdict=blocked`,
`can_close_device_environment_gate=false`, and
`can_close_stand_charging_gate=false`.

## Future physical-tablet rerun

Use the Phase 2 runbook with a real 8-9 inch tablet and declared stand-mounted
setup. The future run must retain `phase2-device-environment-observations.json`,
`soak-8h/samples.jsonl`, `soak-8h/summary.json`,
`soak-8h/exact-window-report.json`,
`soak-8h/phase2-device-memory-gate.json`,
`soak-8h/phase2-device-environment-summary.json`, and
`soak-8h/phase2-tablet-gate.json` before Phase 2 can close.
