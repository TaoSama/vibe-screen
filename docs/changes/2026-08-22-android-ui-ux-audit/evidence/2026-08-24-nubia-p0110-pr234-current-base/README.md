# PR234 current-base Android UI ergonomics check

This is a focused current-base verification for PR #234 on the connected
Nubia P0110 Android device. It records instrumented width-class coverage and a
general Android-device substitute run only. It does not claim that P0110 is a
tablet, does not claim Xiaomi 13/fuxi evidence, and does not close streaming,
latency, soak, native-pointer, stylus, controller, LAN, audio, signing, or
macOS hardware gates.

## Device

- Manufacturer: nubia
- Model: P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Serial: <device-serial>
- Physical display: 1264x2800 at 560 dpi

## Base

- Repository: TaoSama/vibe-screen
- Base: origin/main `6cdb34a1fd9e87174f6113ff34603d8bf297eaef`
- Tested branch: `codex/android-tablet-ui-optimization`
- Tested implementation revision: `873d56694a6daf35daf005c6ff37218902e49cf2`
  for the Android source and retained P0110 device/instrumented evidence. The
  PR head may advance by evidence-only metadata commits; report the final head
  from GitHub when merging.

## Commands

```sh
set -euo pipefail
ANDROID_PROJECT=baseline/AndroidClient
EVIDENCE_DIR=docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-08-24-nubia-p0110-pr234-current-base

git fetch origin --prune
git rev-parse origin/main HEAD

(cd "$ANDROID_PROJECT" && ./gradlew :app:testDebugUnitTest \
  --tests 'dev.telemachus.display.SettingsDialogLayoutPolicyTest' \
  --tests 'dev.telemachus.display.ControlBarLayoutPolicyTest' \
  --rerun-tasks)
(cd "$ANDROID_PROJECT" && ./gradlew :app:assembleDebug :app:assembleDebugAndroidTest)
(cd "$ANDROID_PROJECT" && ./gradlew :app:lintDebug)
adb -s <device-serial> get-state
adb -s <device-serial> shell getprop ro.product.manufacturer
adb -s <device-serial> shell getprop ro.product.model
adb -s <device-serial> shell getprop ro.product.device
adb -s <device-serial> shell getprop ro.build.version.release
adb -s <device-serial> shell getprop ro.build.version.sdk
adb -s <device-serial> shell wm size
adb -s <device-serial> shell wm density
adb -s <device-serial> install -r "$ANDROID_PROJECT/app/build/outputs/apk/debug/app-debug.apk"
adb -s <device-serial> install -r "$ANDROID_PROJECT/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
adb -s <device-serial> shell am instrument -w \
  -e class dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s <device-serial> pull /sdcard/Android/data/dev.telemachus.display/files/phase2-readiness/sustained-use-landscape.png "$EVIDENCE_DIR/sustained-use-landscape.png"
adb -s <device-serial> pull /sdcard/Android/data/dev.telemachus.display/files/phase2-readiness/sustained-use-portrait.png "$EVIDENCE_DIR/sustained-use-portrait.png"
```

## Results

- `git fetch origin --prune`: passed. The focused checks were collected from a
  clean PR-head checkout at `873d56694a6daf35daf005c6ff37218902e49cf2`; this
  record was then rebased onto `6cdb34a1fd9e87174f6113ff34603d8bf297eaef`.
- Focused JVM layout policy tests: passed with `BUILD SUCCESSFUL`; 39 tasks
  executed under `--rerun-tasks`; see `focused-unit-tests.txt`.
- `:app:assembleDebug :app:assembleDebugAndroidTest`: passed with
  `BUILD SUCCESSFUL`; see `assemble-debug-and-androidtest.txt`.
- `:app:lintDebug`: passed with `BUILD SUCCESSFUL`; the report was written to
  `baseline/AndroidClient/app/build/reports/lint-results-debug.html`; see
  `lint-debug.txt`.
- P0110 device identity commands returned `nubia`, `P0110`, `pacific`,
  Android `16`, SDK `36`, physical size `1264x2800`, and density `560`; see
  `device.txt`.
- Debug and androidTest APK installs both returned `Success`.
- Focused instrumentation completed with `OK (23 tests)` after running all
  `SettingsDialogLayoutInstrumentedTest` and `ControlBarLayoutInstrumentedTest`
  cases on the attached Nubia P0110 device selected by
  `adb -s <device-serial>`; see `instrumentation-settings-controlbar.txt`.

## UI evidence

- `sustained-use-landscape.png`: rendered by
  `SettingsDialogLayoutInstrumentedTest.capturesSustainedUseStatusEvidenceImages`
  using a 960dp x 600dp width-class context. This verifies the responsive
  settings layout path in instrumentation; it is not physical tablet hardware
  evidence.
- `sustained-use-portrait.png`: rendered by the same test using a 600dp x 960dp
  width-class context.

The instrumented assertions also explicitly cover the current-base gesture
shortcut groups: `gestureSwipeUpGroup` and `gestureSwipeDownGroup` are inside
`settingsControlsColumn`, remain readable, and are measured against the
controls-column width. A 600dp x 420dp landscape dialog-window case now verifies
the two-column decision uses the intended dialog/window width threshold rather
than the already-padded content-column width.

## Still open

- No 8-9 inch physical tablet acceptance was run.
- No real streaming Host session, display switch, latency, soak, native HID
  mouse, stylus, controller, LAN, audio, signing, TCC, or macOS hardware gate
  is closed by this record.
