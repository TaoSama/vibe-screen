# Native pointer HID acceptance: blocked_device_coordination_lock

Created: 2026-08-22T09:12:33Z
Reason: Android device coordination lock exists; no ADB command was run and native pointer HID acceptance could not start.
Device: not collected not collected / device-lock-blocked / Android not collected / serial not-collected-device-lock
Requested serial: redacted-requested-serial
ADB was run: false
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Visible Mac result: not recorded

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `native-pointer-hid-summary.json`: independent gate summary with `can_close_native_pointer_hid_gate`.
- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.

This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.

## Device coordination locks

- /tmp/vibe-screen-device-android.lock: pid=59387
agent=root
task=trusted-lan-p0110-pr261
created=2026-08-22T17:12:21+0800
