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
├── manifest.json
├── samples.jsonl
├── summary.json
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
└── screenshots/
```

Collect `device-info.json` with:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
```

The artifact must validate against `tools/schemas/device-info.schema.json`;
`device.txt` and `manifest.json` are supporting records, not substitutes for the
schema-backed device identity. `thermal-before.err` and `thermal-after.err` are
stderr captures created by the runbook commands on every run. Determine thermal
collection failure from the command status and whether the corresponding dump is
usable, not from stderr-file presence alone.

The run `README.md` must state the real tablet model, OS build, density,
orientation/window sizes, charger/cable/stand setup, Mac host identity, commit
SHA, APK SHA-256, transport, video preferences, predeclared pass/fail thresholds,
exact collection commands, raw-log links, first failure if any, measured
duration/cadence, and final result. A `phase2-8h` directory can close the
eight-hour gate only when `summary.json` records `duration_seconds >= 28800`,
`interval_seconds <= 60`, and zero missing sample gaps; any app or host crash,
unrecovered interruption, stale frame/input acceptance, sustained severe or
critical thermal state, charging failure, or untrustworthy sample/transport data
must record `first_failure_at` and fail the run. A phone run, emulator run,
synthetic layout test, focused unit test, or short soak belongs in its own
evidence record but does not close the 8-9 inch tablet or eight-hour
sustained-use gates.
