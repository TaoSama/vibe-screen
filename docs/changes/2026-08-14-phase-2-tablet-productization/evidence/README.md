# Phase 2 evidence directory

Create one subdirectory per physical-tablet run:

```text
YYYY-MM-DD-<device-codename>-phase2-8h/
├── README.md
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
├── thermal-before.err       # present when thermal dump collection fails
├── thermal-after.err        # present when thermal dump collection fails
├── raw-logcat.txt
├── host.log
├── reconnects.log
├── frame-drops.log
├── decoder-telemetry.jsonl
└── screenshots/
```

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
