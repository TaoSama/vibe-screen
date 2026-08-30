# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_physical_stylus_not_observed
- Result: Blocked: Android exposes stylus-capable input hardware, but this run
  did not observe a physical stylus drawing in a macOS drawing app. The README
  gate stays open.
- Stable signed/TCC Host ready: false

## Device

- Manufacturer: nubia
- Model/device: P0110 / pacific
- Android: 16 / API 36
- Serial property: redacted-pacific-serial
- Fingerprint: redacted-build-fingerprint
- Display: Physical size: 1264x2800 / Physical density: 560

## Host readiness

`scripts/macos_dev_host.py readiness` reported `status=blocked`,
`signing_tcc_status=blocked`, and `can_start_stylus_gate=false`. The retained
blockers are:

- codesign identity `Vibe Screen Dev` not found in the keychain;
- installed Host codesign inspection failed because
  `/Applications/Vibe Screen.app/Contents/Frameworks/WebRTC.framework` is
  missing a sealed resource;
- Host listener is not observed on TCP port `54321`;
- installed Host is missing `com.apple.developer.hid.virtual.device`;
- login/headless readiness is unverified.

Because Host signing, Screen Recording/Accessibility, and listener readiness
are blocked, no stable signed/TCC-ready Host was available for a physical
stylus drawing session.

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

The Android capability snapshot still exposes a pass-eligible
`goodix_stylus_input` candidate, so the missing prerequisites are the real
physical stylus drawing attempt, Protocol v1 same-session forwarding/injection
logs, stable signed/TCC-ready Host state, and visible macOS drawing-app output.

## Evidence files

- stylus-evidence.json: structured summary and status.
- stylus-summary.json: independent gate summary with
  `can_close_physical_stylus_gate=false`.
- commands.txt: start/end sfltool process check and the commands used.
- dumpsys-input.txt: raw read-only Android input-device snapshot.
- android-diag.log: app private diagnostic log retained for this current-base
  refresh; it does not include a physical stylus drawing observation window.
- host-readiness.json: macOS Host signing/TCC/listener readiness snapshot.
- host-signing-and-permissions.txt: human-readable Host readiness summary.
- host-readiness.stdout: command output from the Host readiness script.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone.
A pass requires a real stylus contacting the Android device while the Protocol
v1 session is active, stable signed/TCC-ready Host evidence, host stylus
injection logs for pressure/tilt/barrel/proximity as applicable, and a visible
macOS drawing-app result.
