# PR493 Android Mode Toggle Device Evidence

Final evidence uses this debug APK:

    076333b301475dfe3d949eab3c80f626053f3b68e95e500c4a8911ad669d4a87  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
    0f2c36d433dc855f3b8b1407ba984887894f90025954963eded29d8aa66536b9  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk

Device:

- Serial: `<redacted-adb-serial>`
- Model: `P0110`
- Android: `16`
- Physical size: `1264x2800`
- Physical density: `560`

## Final Device Matrix

Directory: `final-076333b-real-rotation-matrix/`

The final matrix contains eight Android-only captures from the installed APK. All eight scenarios passed screenshot and system-state validation. Portrait captures are `1264x2800` with `mDisplayRotation=ROTATION_0` and `port`. Landscape captures are real system-rotation captures at `2800x1264` with `cmd window user-rotation: lock 1`, `mDisplayRotation=ROTATION_90`, and `land`. No display-size override was used for this final matrix.

| Scenario | Screenshot | State | XML |
| --- | --- | --- | --- |
| Portrait, day, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-day-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-day-font1.state-after.txt` | present |
| Portrait, night, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-night-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-night-font1.state-after.txt` | present |
| Portrait, day, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-day-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-day-font13.state-after.txt` | unavailable |
| Portrait, night, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-night-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-night-font13.state-after.txt` | unavailable |
| Landscape, day, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-day-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-day-font1.state-after.txt` | unavailable |
| Landscape, night, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-night-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-night-font1.state-after.txt` | unavailable |
| Landscape, day, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-day-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-day-font13.state-after.txt` | unavailable |
| Landscape, night, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-night-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-night-font13.state-after.txt` | unavailable |

`final-076333b-real-rotation-matrix/metadata/validation.json` and `final-076333b-real-rotation-matrix/metadata/final-validation-summary.txt` record the 8/8 `png_ok=true` and `state_ok=true` result. The semantic XML coverage gate requires at least two `present` XML captures and specifically requires the two default portrait scenarios, `phone-portrait-day-font1` and `phone-portrait-night-font1`; this retained evidence satisfies that gate.
The validation metadata was rebuilt offline from the existing screenshots, state files, XML files, install logs, instrumentation log, the recorded app APK SHA-256, and the locally computed androidTest APK SHA-256 after the collector script was hardened. No device recapture or ADB command was run for that metadata rebuild. Because the rebuild did not rerun live cleanup or persist new `pidof` output, `restored.packages_stopped` is retained in the schema as `false` rather than omitted or marked true.

## Guardrails

- `final-076333b-real-rotation-matrix/metadata/adb-reverse-before.txt`, `adb-reverse-after.txt`, and `adb-reverse-final.txt` are empty.
- `final-076333b-real-rotation-matrix/metadata/device-model.txt` records `P0110`.
- `final-076333b-real-rotation-matrix/metadata/apk-sha256.txt` and `androidTest-apk-sha256.txt` record the app and instrumentation APK provenance.
- The scenario state files record physical dimensions only; the final matrix has no `Override size` entries.
- The final restore state is recorded at `final-076333b-real-rotation-matrix/metadata/final-restored.state-after.txt` and confirms `font_scale: 1.0`, `Night mode: Night mode: no`, `cmd window user-rotation: lock 0`, `accelerometer_rotation: 0`, `user_rotation: 0`, and `mDisplayRotation=ROTATION_0`.
- Post-restore package stop is `false` in the offline metadata rebuild because the original evidence did not persist `pidof` output. The current collector script runs `assert_packages_stopped` after `force-stop` for future live captures and records `restored.packages_stopped=true` only when that runtime assertion succeeds. This keeps generic `all(restored.values())` checks fail-closed for the offline rebuild.

## XML Boundary

The two available XML files are the minimum semantic XML coverage for this retained matrix. They cover the default portrait day and night cases, show USB selected, LAN and Internet unselected, `TRY AGAIN` before the diagnostic content, and the USB unavailable guidance text. Future live captures fail if fewer than two XML files validate, either default portrait XML is missing, or any captured XML is rejected.

The other six hierarchy captures are intentionally unavailable because `uiautomator` returned `ERROR: could not get idle state.` Their `*.pull-xml.txt` files record `dump invalid; not pulling XML`, and no stale XML file was reused.

Screenshots plus state metadata remain the primary evidence for all eight scenarios.
