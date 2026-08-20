# Nubia P0110 Phase 2 readiness check

## Result

Passed as a short Android substitute-device readiness check only. This record
does not close the Phase 2 8-9 inch tablet gate, the stand-mounted charging
gate, the thermal-load gate, the recovery-interruption gates, or the eight-hour
sustained-use gate.

## Device and build

- Device: nubia P0110, codename `pacific`, serial `EP0110PZ0B9110300B`.
- OS: Android 16, SDK 36, build fingerprint
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- Display state: `wm size` reported `1264x2800`; `wm density` reported `560`.
- Source state: base commit `18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee`
  plus the working-tree instrumentation screenshot helper added by this
  change.
- APK: `baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk`.
- APK SHA-256: `cebbaacfb7bc26a4fbdfee61a272b2f35247c8692b306afec0b6b99f3ffacfba`.

## Commands

The device was accessed under the shared `/tmp/vibe-screen-device-android.lock`
advisory lock and targeted explicitly with `adb -s EP0110PZ0B9110300B`.

Local build and focused unit test:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon \
  testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest \
  assembleDebug
./gradlew --no-daemon \
  testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest \
  assembleDebug assembleDebugAndroidTest
```

Target-device layout and screenshot instrumentation:

```bash
adb -s EP0110PZ0B9110300B install -r \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B install -r \
  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s EP0110PZ0B9110300B shell am instrument -w -r \
  -e class 'dev.telemachus.display.SettingsDialogLayoutInstrumentedTest#capturesSustainedUseStatusEvidenceImages' \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s EP0110PZ0B9110300B shell am instrument -w -r \
  -e class 'dev.telemachus.display.SettingsDialogLayoutInstrumentedTest' \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s EP0110PZ0B9110300B shell am start -n dev.telemachus.display/.MainActivity
```

Platform state snapshots:

```bash
make evidence-device-info EVIDENCE_SERIAL=EP0110PZ0B9110300B \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-20-nubia-p0110-readiness
adb -s EP0110PZ0B9110300B shell getprop > device.txt
adb -s EP0110PZ0B9110300B shell wm size > wm-size-before.txt
adb -s EP0110PZ0B9110300B shell wm density > wm-density-before.txt
adb -s EP0110PZ0B9110300B shell dumpsys battery > adb-battery-before.txt
adb -s EP0110PZ0B9110300B shell dumpsys power > adb-power-before.txt
adb -s EP0110PZ0B9110300B shell dumpsys thermalservice > thermal-before.txt 2> thermal-before.err
```

## Evidence

- `DeviceHealthMonitorTest` and `assembleDebug`: `BUILD SUCCESSFUL in 35s`.
- `assembleDebugAndroidTest`: `BUILD SUCCESSFUL in 9s`.
- Target P0110 `SettingsDialogLayoutInstrumentedTest`: 7 tests, 0 failures,
  `OK (7 tests)`, recorded in `p0110-settings-layout-test.txt` and
  confirmed after the final local build in `p0110-settings-layout-test-final.txt`.
- Target P0110 screenshot instrumentation: 1 test, 0 failures, `OK (1 test)`,
  recorded in `p0110-sustained-use-screenshot-test.txt`.
- Sustained-use card screenshots: `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png`.
- Native screen captures: `screenshots/portrait.png` and
  `screenshots/portrait-physical-landscape.png`. These files are intentionally
  named as portrait captures because `user_rotation` remained `0`; physically
  turning the handset did not change the captured Android buffer, and the two
  PNG files compare identical.
- The initial `am start` attempt recorded `Error type 3` in
  `am-start-initial-error-type-3.txt`; after reinstalling the final APK and
  holding the same device lock, `am-start-reverify.txt` recorded
  `Starting: Intent { cmp=dev.telemachus.display/.MainActivity }` with
  `am-start-reverify-status.txt` reporting `exit_code=0`.
- Platform state before/after remained consistent for this short check: battery
  100%, AC powered, power saver disabled, thermal status `0`.

## Limits

This is not physical-tablet acceptance. The device is a nubia P0110/pacific
Android phone substitute. The screenshots prove the settings sustained-use card
can be rendered readably by the instrumentation path on this device and in the
synthetic 600dp portrait/landscape tablet configurations exercised by the test.
They do not prove a real 8-9 inch tablet panel, split/freeform window behavior,
stand-mounted charging stability, controlled thermal behavior, background or
transport recovery, login startup, headless Mac recovery, or eight-hour memory /
thermal / power stability.
