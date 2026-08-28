# Native pointer HID acceptance: blocked

Created: 2026-08-26T23:08:16Z
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial redacted-pacific-serial
Requested serial: redacted-requested-serial
ADB was run: true
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Stable signed/TCC Host ready: false
Visible Mac result: not recorded

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `native-pointer-hid-summary.json`: independent gate summary with `can_close_native_pointer_hid_gate`.
- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.

A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.
This evidence must remain scoped to the exact device identity above.
Persistent device identifiers, local workstation paths, and Android window handles are redacted; `dumpsys-input.txt` retains only the sanitized input-device snapshot needed for the gate.
