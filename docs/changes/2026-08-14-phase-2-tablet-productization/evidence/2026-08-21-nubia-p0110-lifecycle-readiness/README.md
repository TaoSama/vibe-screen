# Nubia P0110 Phase 2 lifecycle readiness

## Result

Blocked readiness only. This run exercised the Android foreground/background
lifecycle and the sustained-use settings UI on the attached Nubia P0110, but it
does not close any Phase 2 physical-tablet gate. The device is an Android phone
substitute, no physical stand or charger model was verified, no macOS Host stream
was available, and no eight-hour sample series was collected.

## Device and build

- Device: nubia P0110, codename pacific, serial <redacted-adb-serial>.
- OS: Android 16, SDK 36, build fingerprint
  nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys.
- Display state: wm size reported 1264x2800; wm density reported 560.
- Original readiness source base: 0bf426dc657d2068f82cb93d897d89226b3c0524.
- Rebased validation head before this doc-only evidence update:
  38752d65a3dca02699500836dccf35aaaf34b409.
- Branch during the run: codex/phase2-p0110-readiness-recovery.
- Final debug APK SHA-256 after the lifecycle policy patch:
  112ceac607210546dfd8f7a8d4e8f7c0644ef9e67f35e94f7d4de83770d3e1e5.

## Commands

The device was targeted explicitly with adb -s <redacted-adb-serial> for all device
operations.

Local build and focused unit test:

~~~bash
cd baseline/AndroidClient
./gradlew --no-daemon \
  testDebugUnitTest \
  --tests dev.telemachus.display.DeviceHealthMonitorTest \
  --tests dev.telemachus.display.MainActivityStatePrimitivesTest \
  --tests dev.telemachus.display.StreamingWindowStatePolicyTest \
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest \
  assembleDebug assembleDebugAndroidTest
~~~

Target-device install, settings instrumentation, and lifecycle sampling:

~~~bash
adb -s <redacted-adb-serial> install -r \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s <redacted-adb-serial> install -r \
  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s <redacted-adb-serial> shell am instrument -w -r \
  -e class 'dev.telemachus.display.SettingsDialogLayoutInstrumentedTest' \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s <redacted-adb-serial> shell am force-stop dev.telemachus.display
adb -s <redacted-adb-serial> shell am start -n dev.telemachus.display/.MainActivity
adb -s <redacted-adb-serial> shell dumpsys activity activities
adb -s <redacted-adb-serial> shell dumpsys window
adb -s <redacted-adb-serial> shell input keyevent HOME
adb -s <redacted-adb-serial> shell dumpsys activity activities
adb -s <redacted-adb-serial> shell dumpsys window
adb -s <redacted-adb-serial> shell am start -n dev.telemachus.display/.MainActivity
adb -s <redacted-adb-serial> shell dumpsys battery
adb -s <redacted-adb-serial> shell dumpsys power
adb -s <redacted-adb-serial> shell dumpsys thermalservice
adb -s <redacted-adb-serial> logcat -d -s MA StreamClient VibeScreenTelemetry
~~~

## Evidence

- p0110-settings-layout-test-final-policy.txt: target-device
  SettingsDialogLayoutInstrumentedTest passed, OK (7 tests).
- screenshots/sustained-use-portrait.png and screenshots/sustained-use-landscape.png:
  settings sustained-use card rendered through the instrumentation path.
- adb-battery-final-policy-before.txt and adb-battery-final-policy-after.txt:
  battery stayed at 100%, AC powered was true, USB powered was false, and
  battery temperature stayed at 34.0 C during the short check.
- lifecycle-summary.txt: records the app foreground, background, and returned
  foreground states from the full dumpsys activity/window captures and notes
  that power saver was off in the full dumpsys power snapshots retained locally.
- thermal-final-policy-before.txt and thermal-final-policy-after.txt: thermal
  service snapshots were captured successfully; the after snapshot recorded
  Thermal Status: 1, not a severe or critical state. This was not a controlled
  thermal-load pass.
- vibescreen-logcat-final-policy.txt: app-filtered logcat recorded foreground ->
  background -> foreground lifecycle transitions with connected=false and
  background retries paused. It also records repeated Protocol upgrade probe
  failures because the Host stream was unavailable.
- host-transport-preflight.txt: no local listener was found on TCP 54321; adb
  reverse still listed UsbFfs tcp:54321 tcp:54321.
- Full activity/window/power dumps were captured during the local run but are
  not committed because they include broad system state unrelated to this app;
  lifecycle-summary.txt records the relevant app-owned facts.

## Blockers

- The device is a nubia P0110/pacific Android phone substitute, not a physical
  8-9 inch tablet.
- No physical stand, dock, charger model, ambient setup, or all-day charging
  geometry was verified.
- The macOS Host stream was unavailable; no fresh keyframe, first returned frame,
  session epoch, Host PID stability, stale-frame rejection, stale-input
  rejection, or bounded reconnect could be proven on a live stream.
- The run was a short readiness check, not an eight-hour sustained stream.
- Thermal data was sampled only from platform dumps during idle/short activity;
  no controlled thermal load or long-duration thermal threshold behavior was
  tested.
- Login startup, headless Mac recovery, stylus workflows, and hardware-keyboard
  workflows were not exercised.

## Gate status

All Phase 2 acceptance gates remain open after this evidence record:

- physical_8_9_inch_tablet: open.
- stand_mounted_charging: open.
- thermal_power_sampling: open.
- foreground_background_recovery: open; lifecycle hooks and short app state
  transitions were observed, but not under an active Host stream.
- transport_reconnect_recovery: open.
- login_startup_or_headless_recovery: open.
- eight_hour_sustained_stream: open.
