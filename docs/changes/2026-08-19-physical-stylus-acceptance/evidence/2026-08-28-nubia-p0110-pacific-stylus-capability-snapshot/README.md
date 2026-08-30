# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_physical_stylus_not_observed
- Result: Blocked: Android exposes stylus-capable input hardware, but this run did not observe a physical stylus drawing in a macOS drawing app. The README gate stays open.
- Stable signed/TCC Host ready: false

## Device

- Manufacturer: nubia
- Model/device: P0110 / pacific
- Android: 16 / API 36
- Serial property: redacted-pacific-serial
- Fingerprint: redacted-build-fingerprint
- Display: Physical size: 1264x2800 / Physical density: 560

## Stylus input devices

- goodix_stylus_input
  - Sources: none
  - Axes: PRESSURE, TILT
  - Buttons: none
  - Pass eligible: no
- goodix_stylus_input
  - Sources: KEYBOARD, STYLUS, TOUCHSCREEN
  - Axes: ORIENTATION, PRESSURE, TILT, X, Y
  - Buttons: none
  - Pass eligible: yes

## Evidence files

- stylus-evidence.json: structured summary and status.
- stylus-summary.json: independent gate summary with can_close_physical_stylus_gate.
- host-stylus.log: new Host log bytes from the passing observation window, required only for a passing physical drawing run.
- dumpsys-input.txt: raw read-only Android input-device snapshot with line-ending whitespace normalized.
- android-diag.log: not retained; this capability-only snapshot did not start a physical drawing observation window.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone. A pass requires a real stylus contacting the Android device while the Protocol v1 session is active, stable signed/TCC-ready Host evidence, host stylus injection logs for pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app result.
