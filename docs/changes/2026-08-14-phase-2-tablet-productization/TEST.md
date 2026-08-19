# Phase 2 tablet productization verification

## Automated scope

Run the focused Android checks within the task's ten-minute validation budget:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon \
  testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest \
  assembleDebug
```

Run the settings layout instrumentation separately when a device is available.
The test constrains the dialog to the production 85% screen-height viewport and
covers 600x960dp portrait and 960x600dp landscape in addition to the existing
narrow-window, large-text, and responsive toggle-group cases:

```bash
./gradlew --no-daemon connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

## Required device evidence

No target-tablet or long-duration result is recorded by this change. Before
closing Phase 2, execute [RUNBOOK.md](RUNBOOK.md) and retain evidence under
[`evidence/`](evidence/README.md) for all of the following:

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

- `DeviceHealthMonitorTest`: 4 tests, 0 skipped, 0 failures, 0 errors;
- `assembleDebug` and Android test compilation: successful in the same 9-second
  Gradle invocation;
- `SettingsDialogLayoutInstrumentedTest`: 6 tests passed on an Android 16
  `2211133C` device (1080x2400, 420 dpi) in 17 seconds. Its tablet cases use
  synthetic 600x960dp and 960x600dp configurations and do not prove behavior on
  a physical 8–9 inch tablet;
- debug APK SHA-256:
  `f1da0ce7fe726043b45f63ada90ec91e3d8a0a045cdd925a3b7366e414744fcf`.

This follow-up's Gradle validation invocations consumed less than one minute of
wall-clock time in aggregate.

No physical-tablet check, thermal load, or soak was run. The result proves the
focused policy/lifecycle behavior and settings layout under the tested Android
runtime and synthetic configurations only.
