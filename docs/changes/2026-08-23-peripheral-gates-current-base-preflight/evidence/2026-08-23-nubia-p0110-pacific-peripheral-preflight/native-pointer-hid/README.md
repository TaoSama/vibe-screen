# Native pointer HID acceptance: blocked

Created: 2026-08-22T17:31:11Z
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial redacted-pacific-serial
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Visible Mac result: not recorded

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.

This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.
