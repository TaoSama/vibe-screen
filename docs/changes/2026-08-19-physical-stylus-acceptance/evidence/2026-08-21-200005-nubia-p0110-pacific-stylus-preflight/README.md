# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_physical_stylus_not_observed
- Result: Blocked: Android exposes stylus-capable input hardware, but this run did not observe a physical stylus drawing in a macOS drawing app. The README gate stays open.

## Device

- Manufacturer: nubia
- Model/device: P0110 / pacific
- Android: 16 / API 36
- Serial property: EP0110PZ0B9110300B
- Fingerprint: nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys
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
- host-stylus.log: new Host log bytes from the passing observation window, required only for a passing physical drawing run.
- dumpsys-input.txt: raw read-only Android input-device snapshot with line-ending whitespace normalized.
- android-diag.log: app private diagnostic log, present only when run-as succeeded and required for a passing physical drawing run.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone. A pass requires a real stylus contacting the Android device while the Protocol v1 session is active, host stylus injection logs for pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app result.
