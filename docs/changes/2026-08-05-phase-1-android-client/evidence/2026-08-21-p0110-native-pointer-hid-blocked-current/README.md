# Native pointer HID acceptance: blocked

Created: 2026-08-21T15:56:53Z
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial redacted-pacific-serial
Requested serial: redacted-requested-serial
ADB was run: true
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Visible Mac result: not recorded

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized, or empty when ADB was not run.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.

This evidence must remain scoped to the exact collected device identity above, or to the requested run when ADB was not run.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory is present only in `dumpsys-input.txt` from ADB-backed runs.
