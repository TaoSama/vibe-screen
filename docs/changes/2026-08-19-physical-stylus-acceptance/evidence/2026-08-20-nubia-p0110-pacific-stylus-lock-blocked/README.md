# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_device_coordination_lock
- Result: Blocked: an Android device coordination lock existed, so this run did not execute ADB commands or observe physical stylus input. The README gate stays open.

## Device

ADB was not run. Requested serial: EP0110PZ0B9110300B.

## Device coordination locks

- /tmp/vibe-screen-device-android.lock: present

## Stylus input devices

No input-device snapshot was collected because ADB was not run.

## Evidence files

- stylus-evidence.json: structured summary and status.
- host-stylus.log: required only for a passing physical drawing run.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone. A pass requires a real stylus contacting the Android device while the Protocol v1 session is active, host stylus injection logs for pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app result.
