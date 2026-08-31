# Android physical stylus acceptance evidence

## Conclusion

- Status: blocked_physical_stylus_not_observed
- Result: Blocked. Android exposes stylus-capable input hardware, but this run
  did not observe a physical stylus drawing in a macOS drawing app. The README
  gate stays open.
- Stable signed/TCC Host ready: false
- Source: `origin/main` at `28b9d1a59ef026b45ada3cd7e665ef09ea9a7523` with
  `current_source_dirty=false` in `host-readiness.json`.

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

- codesign identity `Vibe Screen Dev` is not present in the keychain;
- installed Host codesign inspection fails because
  `/Applications/Vibe Screen.app/Contents/Frameworks/WebRTC.framework` has
  missing sealed resources;
- Host listener is not observed on TCP port `54321`;
- installed Host is missing `com.apple.developer.hid.virtual.device`;
- login/headless readiness is unverified.

Screen Recording and Accessibility grants were not inspected because Host bundle
signing was not ready. No stable signed/TCC-ready Host was available for a
physical stylus drawing session.

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
`goodix_stylus_input` candidate, so hardware capability is not the blocker. The
missing prerequisites are the real physical stylus drawing attempt, Protocol v1
same-session Android forwarding logs, stable signed/TCC-ready Host state, Host
`Stylus injected:` logs, and visible macOS drawing-app output.

## Evidence files

- `stylus-evidence.json`: structured collector output and status.
- `stylus-summary.json`: independent gate summary with
  `verdict=blocked` and `can_close_physical_stylus_gate=false`.
- `commands.txt`: start/end `sfltool` process check and commands used.
- `dumpsys-input.txt`: raw read-only Android input-device snapshot.
- `android-diag.log`: app private diagnostic log retained for this
  current-base refresh; it does not include a physical stylus drawing
  observation window.
- `host-readiness.json`: macOS Host signing/TCC/listener readiness snapshot.
- `host-signing-and-permissions.txt`: human-readable Host readiness summary.
- `host-readiness.stdout`: command output from the Host readiness script.
- `script-output.txt` / `script-stderr.txt`: stylus collector output.
- `SHA256SUMS`: artifact checksums.

## Gate rule

Do not close the physical-stylus drawing-app gate from device capability alone.
A pass requires a real stylus contacting the Android device while the Protocol
v1 session is active, stable signed/TCC-ready Host evidence, same-session
Android `Stylus forwarded:` logs, Host `Stylus injected:` logs for
pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app
result.

## Safety

`pgrep -x sfltool || true` returned no output at start and end. No
`/usr/bin/sfltool dumpbtm` command was executed, and the Host readiness command
did not use the login-item diagnostic opt-in. The target device serial is
redacted in checked-in evidence.
