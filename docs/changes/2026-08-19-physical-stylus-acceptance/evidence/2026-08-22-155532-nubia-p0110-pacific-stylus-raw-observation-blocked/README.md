# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_device_coordination_lock
- Result: Blocked: an Android device coordination lock existed, so this run did not execute ADB commands or observe physical stylus input. The README gate stays open.

## Device

ADB was not run. Requested serial: <redacted-adb-serial>.

## Device coordination locks

- /tmp/vibe-screen-device-android.lock: pid=57257
agent=root
task=android-ui-ux-nubia-audit
created=2026-08-22T15:37:19+08:00

## Stylus input devices

No input-device snapshot was collected because ADB was not run.

## Evidence files

- stylus-evidence.json: structured summary and status.
- commands.txt: repository setup, coordination preflight, observed lock, and the
  exact fail-closed evidence command.
- No device preflight, Host stylus log, or drawing-app screenshot was produced
  for this lock-blocked record because ADB and Host observation were not run.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone. A pass requires a real stylus contacting the Android device while the Protocol v1 session is active, host stylus injection logs for pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app result.
