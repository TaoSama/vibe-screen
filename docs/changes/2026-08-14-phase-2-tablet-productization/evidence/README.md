# Phase 2 evidence directory

Create one subdirectory per physical-tablet run:

```text
YYYY-MM-DD-<device-codename>-phase2-8h/
├── README.md
├── device.txt
├── host.txt
├── build.txt
├── apk-sha256.txt
├── samples.csv
├── adb-battery-before.txt
├── adb-battery-after.txt
├── adb-power-before.txt
├── adb-power-after.txt
├── thermal-before.txt
├── thermal-after.txt
├── raw-logcat.txt
├── host.log
├── reconnects.log
└── screenshots/
```

The run `README.md` must state the real tablet model, OS build, density,
orientation/window sizes, charger/cable/stand setup, Mac host identity, commit
SHA, APK SHA-256, transport, video preferences, predeclared pass/fail thresholds,
and final result. A phone run, emulator run, synthetic layout test, focused unit
test, or short soak belongs in its own evidence record but does not close the
8-9 inch tablet or eight-hour sustained-use gates.
