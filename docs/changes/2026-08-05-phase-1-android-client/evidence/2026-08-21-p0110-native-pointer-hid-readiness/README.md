# Native pointer HID acceptance: blocked

Created: 2026-08-20T19:12:40Z
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial EP0110PZ0B9110300B
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Visible Mac result: not recorded

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `dumpsys-input.txt`: raw Android input-device snapshot.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.

This evidence must remain scoped to the exact device identity above.
