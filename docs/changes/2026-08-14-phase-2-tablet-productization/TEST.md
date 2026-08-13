# Phase 2 tablet productization verification

## Automated scope

Run the focused Android checks within the task's ten-minute validation budget:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon \
  testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest \
  assembleDebug
```

When a coordinated device lease is available, run the settings layout
instrumentation separately. The test covers 600x960dp portrait and 960x600dp
landscape in addition to the existing narrow-window, large-text, and responsive
toggle-group cases:

```bash
adb -s DEVICE_SERIAL install -r -t app/build/outputs/apk/debug/app-debug.apk
./gradlew --no-daemon connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

## Required device evidence

No physical-device or long-duration result is recorded by this change. Before
closing Phase 2, retain evidence for all of the following:

- exact 8–9 inch tablet model, OS/build, logical window sizes, density, and both
  orientations, including split/freeform resizing where supported;
- settings status matching `dumpsys battery`, `dumpsys power`, and thermal status
  while charging, discharging, in power saver, and under controlled load;
- stand-mounted charging without cable/data instability or unsafe heat buildup;
- foreground/background and transport interruption recovery with new session
  epochs and no stale frame/input acceptance;
- login launch and headless Mac mini recovery after reboot;
- an eight-hour sample series for live processes, frames/drops, reconnects,
  Android RSS, battery/current/voltage where exposed, and thermal status.

The eight-hour run must not be replaced by this focused test or by a short soak.

## Focused offline result

On 2026-08-14, the focused validation completed well inside the ten-minute
budget:

- `DeviceHealthMonitorTest`: 3 tests, 0 skipped, 0 failures, 0 errors;
- final `assembleDebug`: successful in the same 13-second Gradle invocation;
- `compileDebugAndroidTestKotlin`: successful in 6 seconds;
- debug APK SHA-256:
  `e513325bc924059a423e2a4bc12ad7adf296a22b8d73f1e6b1eb97eff7f94d84`.

Including the earlier incremental compile used while reviewing the implementation,
all Gradle validation invocations consumed less than one minute of wall-clock
time in aggregate.

No ADB command, instrumentation execution, physical-tablet check, thermal load,
or soak was run. The result proves compilation and the focused pure policy/
lifecycle behavior only.
