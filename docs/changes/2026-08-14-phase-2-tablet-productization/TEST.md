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
narrow-window, large-text, and responsive toggle-group cases. It also includes
an evidence-image test that renders the sustained-use card for portrait and
landscape review:

```bash
./gradlew --no-daemon connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

When more than one Android device is attached, bind the evidence run to the
intended device with explicit `adb -s` installs and instrumentation so emulator
results are not confused with the physical-device record:

```bash
adb -s "$ADB_SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk
adb -s "$ADB_SERIAL" install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s "$ADB_SERIAL" shell am instrument -w -r \
  -e class 'dev.telemachus.display.SettingsDialogLayoutInstrumentedTest' \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
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

## 2026-08-20 Nubia P0110 readiness result

This follow-up used the attached Nubia P0110/pacific (`EP0110PZ0B9110300B`) as
an Android phone substitute only. It must not be relabeled as 8-9 inch tablet
evidence and it does not replace the required eight-hour run. Evidence is under
[`evidence/2026-08-20-nubia-p0110-readiness`](evidence/2026-08-20-nubia-p0110-readiness/README.md).

- `DeviceHealthMonitorTest` plus `assembleDebug`: `BUILD SUCCESSFUL in 35s`.
- `assembleDebugAndroidTest`: `BUILD SUCCESSFUL in 9s`.
- Target-device `SettingsDialogLayoutInstrumentedTest`: 7 tests, 0 failures,
  `OK (7 tests)` from direct `adb -s EP0110PZ0B9110300B shell am instrument`.
- Sustained-use screenshot test: 1 test, 0 failures, `OK (1 test)` from direct
  `adb -s EP0110PZ0B9110300B shell am instrument`.
- The run captured the device identity, `wm size`/density, battery, power, and
  thermal dumps. The short sample read 100% battery, AC powered, power saver
  disabled, and thermal status `0`.
- The screenshot artifacts
  `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png` show the settings sustained-use card
  rendered from the instrumentation path.
- The native screen captures are named `screenshots/portrait.png` and
  `screenshots/portrait-physical-landscape.png` because `user_rotation` remained
  `0`; the physical-landscape capture produced the same portrait Android buffer
  and must not be treated as a real system-landscape screenshot.
- An initial launch attempt recorded `Error type 3`; the app launch was
  reverified afterward under the same device lock, and `am-start-reverify.txt`
  records `Starting: Intent { cmp=dev.telemachus.display/.MainActivity }` with
  exit code `0` in `am-start-reverify-status.txt`.

Still open after this result: real 8-9 inch tablet panel behavior, split or
freeform resizing on target hardware, stand-mounted charging stability,
controlled thermal-load behavior, background/foreground recovery, transport
interruption recovery, login startup, headless Mac recovery, stylus and hardware
keyboard workflows, and the eight-hour sample series required by
[RUNBOOK.md](RUNBOOK.md).

## 2026-08-21 Phase 2 evidence manifest readiness

This follow-up added a schema-backed `phase2-tablet-manifest.json` preparation
record for future eight-hour runs. It binds the run to `device-info.json`, the
declared device class, stand/charger/cable setup, host/APK identity, transport,
video preferences, pass/fail thresholds, and planned recovery scenarios before
the timer starts. It also maps the ADB `ro.product.device` value to the manifest
`codename` field so Nubia P0110/pacific and Xiaomi/fuxi evidence keep their real
device identity.

Validation performed for this tooling-only update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_manifest tools.tests.test_device_info tools.tests.test_schemas -v`
- `make phase2-tablet-manifest EVIDENCE_DIR=.build/phase2-manifest-smoke ...`
  using the retained P0110 readiness `device-info.json`; the generated manifest
  recorded `manufacturer=nubia`, `model=P0110`, `codename=pacific`,
  `android_release=16`, and `device_class=android_substitute`.

No device soak, physical-tablet run, controlled thermal load, background or
transport recovery pass, login startup, headless Mac recovery, stylus, or
hardware-keyboard evidence was produced by this tooling update. All Phase 2
device gates above remain open.

## 2026-08-21 Nubia P0110 lifecycle readiness result

This follow-up used the attached Nubia P0110/pacific (`EP0110PZ0B9110300B`) as
an Android phone substitute only. Evidence is under
[`evidence/2026-08-21-nubia-p0110-lifecycle-readiness`](evidence/2026-08-21-nubia-p0110-lifecycle-readiness/README.md).

Android lifecycle hardening in this change is covered by focused local tests:

- `StreamingWindowStatePolicyTest`: verifies that a connected foreground stream
  adds both `FLAG_KEEP_SCREEN_ON` and `FLAG_SECURE`, a connected background
  stream clears only `FLAG_KEEP_SCREEN_ON` while reapplying `FLAG_SECURE`, debug
  screenshot opt-in affects only foreground capture, and disconnect clears both
  streaming flags.
- `MainActivityControllerForwardingContractTest`: verifies that foreground
  return requests a fresh USB/LAN keyframe and an Internet-session keyframe, that
  background lifecycle cancellation runs before stop, and that key, touch, and
  generic-motion input paths are gated by foreground state before transport
  dispatch.

Validation performed:

- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest --tests dev.telemachus.display.MainActivityStatePrimitivesTest --tests dev.telemachus.display.StreamingWindowStatePolicyTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest assembleDebug assembleDebugAndroidTest`: `BUILD SUCCESSFUL in 10s`.
- Direct target-device install of the final debug APK with
  `adb -s EP0110PZ0B9110300B install -r ...`.
- Direct target-device `SettingsDialogLayoutInstrumentedTest` with
  `adb -s EP0110PZ0B9110300B shell am instrument`: 7 tests, 0 failures,
  `OK (7 tests)`.
- Final debug APK SHA-256:
  `112ceac607210546dfd8f7a8d4e8f7c0644ef9e67f35e94f7d4de83770d3e1e5`.

Observed short-device evidence:

- Device identity remained nubia P0110, codename `pacific`, Android 16 / SDK 36,
  1264x2800 at 560 dpi. This must not be relabeled as Xiaomi/fuxi or as tablet
  evidence.
- The sustained-use settings card screenshots are retained in
  `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png`; the final instrumentation run kept
  the settings layout test at 7/7 passing.
- Battery snapshots around the final check stayed at 100%, AC powered true, USB
  powered false, and 34.0 C. Power dumps were collected before and after the
  lifecycle pass. Thermal dumps were collected before and after; the final pass
  observed thermal status `1`, which is below the severe/critical states but was
  not produced by a controlled thermal-load test.
- App-filtered logcat recorded foreground -> background -> foreground lifecycle
  transitions and the background line `connected=false; retries paused`.
- Host transport was blocked: no local listener was present on TCP `54321`, even
  though `adb reverse` listed `UsbFfs tcp:54321 tcp:54321`. Logcat recorded
  repeated `Protocol upgrade probe closed before a response`, so no live stream
  was established.

Still open after this result: real 8-9 inch tablet panel behavior, stand-mounted
charging stability, controlled thermal-load behavior, live foreground/background
recovery with fresh keyframe or bounded reconnect, transport interruption
recovery, login startup, headless Mac recovery, stylus and hardware-keyboard
workflows, and the eight-hour sample series required by [RUNBOOK.md](RUNBOOK.md).
