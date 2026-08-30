# Native pointer HID acceptance: blocked

Created: 2026-08-26T23:05:42Z
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
- Android native pointer logcat window: not retained because no physical mouse observation ran.
- Host pointer log window: not retained because no physical mouse observation ran.

A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.
This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.
