# Phase 2 evidence directory

Create one subdirectory per physical-tablet run:

```text
YYYY-MM-DD-<device>-phase2-8h/
├── README.md
├── device-info.json
├── device.txt
├── host.txt
├── build.txt
├── apk-sha256.txt
├── phase2-tablet-manifest.json
├── soak-8h/
│   ├── samples.jsonl
│   ├── summary.json
│   ├── host-telemetry.jsonl
│   ├── exact-window-report.json
│   ├── phase2-device-memory-gate.json
│   └── phase2-tablet-gate.json
├── samples.csv              # optional derived conversion; keep raw JSONL
├── adb-battery-before.txt
├── adb-battery-after.txt
├── adb-power-before.txt
├── adb-power-after.txt
├── thermal-before.txt
├── thermal-after.txt
├── thermal-before.err       # stderr capture; use status and dump content for failure
├── thermal-after.err        # stderr capture; use status and dump content for failure
├── raw-logcat.txt
├── host.log
├── reconnects.log
├── frame-drops.log
├── decoder-telemetry.jsonl
├── stylus-evidence.json
├── hardware-keyboard-evidence.json
├── orientation-evidence.json
├── recovery-evidence.json
├── phase2-tablet-preflight.json
└── screenshots/
    ├── sustained-use-portrait.png
    └── sustained-use-landscape.png
```

Collect `device-info.json` with:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
```

Before starting the eight-hour timer, create the Phase 2 manifest with
`make phase2-tablet-manifest EVIDENCE_DIR="$RUN_DIR" ...` and fill in the
stand, charger, host build, APK hash, transport, video preferences, thresholds,
and planned recovery scenarios. The file must validate against
`tools/schemas/phase2-tablet-manifest.schema.json`. It also records the Android
PSS source, Host RSS source, Host PID, minimum eight-hour duration, sample
cadence, and required memory/charging/thermal fields.
After the eight-hour soak and `phase2-tablet-gate` derivation, run
`make phase2-tablet-preflight EVIDENCE_DIR="$RUN_DIR"`. The generated
`phase2-tablet-preflight.json` is the final machine-readable bundle check for
physical-tablet identity, portrait/landscape UI, stylus, hardware keyboard,
recovery, thermal/power, and the eight-hour soak gate.

The artifact must validate against `tools/schemas/device-info.schema.json`;
`device.txt` and `phase2-tablet-manifest.json` are supporting records, not substitutes for the
schema-backed device identity. `thermal-before.err` and `thermal-after.err` are
stderr captures created by the runbook commands on every run. Determine thermal
collection failure from the command status and whether the corresponding dump is
usable, not from stderr-file presence alone.

After deriving the exact-window report, run `make phase2-tablet-gate` from the
repository root. The gate consumes `phase2-tablet-manifest.json`, the eight-hour
soak report, and this raw evidence directory before it can report `pass`. Missing
raw artifacts, a phone substitute such as Nubia P0110/pacific/Android 16, or an
undeclared threshold leaves the result `insufficient`.

The run `README.md` must state the real tablet model, OS build, density,
orientation/window sizes, charger/cable/stand setup, Mac host identity, commit
SHA, APK SHA-256, transport, video preferences, predeclared pass/fail thresholds,
exact collection commands, raw-log links, first failure if any, measured
duration/cadence, and final result. A `phase2-8h` directory can close the
eight-hour gate only when `summary.json` records `duration_seconds >= 28800`,
`interval_seconds <= 60`, zero missing sample gaps, and
`soak-8h/phase2-device-memory-gate.json` reports `pass` from Android PSS, Host
RSS, charging/full-state, and thermal samples. Any app or host crash,
unrecovered interruption, stale frame/input acceptance, sustained severe or
critical thermal state, charging failure, missing Host PID/RSS, missing Android
PSS, or untrustworthy sample/transport data must record `first_failure_at` and
fail the run. A phone run, emulator run, synthetic layout test, focused unit
test, or short soak belongs in its own evidence record but does not close the
8-9 inch tablet, eight-hour sustained-use, or device-memory gates.

Hardware-keyboard workflow evidence uses a focused gate summary alongside any
tablet or substitute-device records. A passing directory must include
`hardware-keyboard-observations.json`, `hardware-keyboard-summary.json`,
`dumpsys-input.txt`, Android production forwarding logs, Host `Key injected:`
logs, Host listener/signing/TCC preflight records, and a screenshot or recording
of the visible Mac result. Generate the summary with:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

The summary closes the hardware-keyboard workflow gate only when
`verdict=pass` and `can_close_hardware_keyboard_gate=true`. A blocked record may
be kept here when the Android device lock, physical keyboard, Host listener, or
stable signed/TCC Host prerequisite is missing; blocked evidence must not run
ADB when the shared Android lock is already held.

## Blocked evidence

When no physical 8-9 inch tablet is available, create a blocked record instead
of a pass-shaped directory. The minimum blocked package is:

```text
YYYY-MM-DD-<device>-blocked-no-physical-tablet/
├── README.md
├── device-info.json
├── phase2-tablet-manifest.json    # PHASE2_DEVICE_CLASS=android_substitute
└── phase2-tablet-preflight.json   # verdict=blocked
```

The README must name the substitute device, state that it is not an 8-9 inch
tablet, link any short readiness evidence, and include the exact rerun commands
for the future physical-tablet pass. The blocked preflight should preserve all
missing gates rather than editing them out.

The `phase2-tablet-soak-preflight` wrapper may create readiness-only directories
such as `YYYY-MM-DD-nubia-p0110-phase2-soak-preflight/`. These records include
`phase2-soak-readiness.json` and usually a `soak-preflight/` subdirectory rather
than a formal `soak-8h/` result. A readiness result of `blocked` records why the
gate could not start, such as a phone substitute, missing Host PID, missing Host
JSONL telemetry, or an existing device lock. It is not evidence that the
eight-hour gate passed.

Hardware-keyboard workflow evidence uses a focused gate summary alongside any
tablet or substitute-device records. A passing directory must include
`hardware-keyboard-observations.json`, `hardware-keyboard-summary.json`,
`dumpsys-input.txt`, Android production forwarding logs, Host `Key injected:`
logs, Host listener/signing/TCC preflight records, and a screenshot or recording
of the visible Mac result. Generate the summary with:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

The summary closes the hardware-keyboard workflow gate only when
`verdict=pass` and `can_close_hardware_keyboard_gate=true`. A blocked record may
be kept here when the Android device lock, physical keyboard, Host listener, or
stable signed/TCC Host prerequisite is missing; blocked evidence must not run
ADB when the shared Android lock is already held.
