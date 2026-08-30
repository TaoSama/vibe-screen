# Native pointer HID acceptance: blocked

Created: 2026-08-30T20:48:10Z (2026-08-31 Asia/Shanghai local run date)
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial redacted-pacific-serial
Requested serial: redacted-requested-serial
ADB was run: true
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Stable signed/TCC Host ready: false
Visible Mac result: not recorded
Source commit: 075dc157c36ba71df9f757e571015905881a7154
Host readiness: blocked from current `origin/main`; `host-readiness.json` reports `can_start_native_hid_gate=false`.

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `native-pointer-hid-summary.json`: independent gate summary with `can_close_native_pointer_hid_gate`.
- `host-readiness.json`: shared Host prerequisite snapshot captured from the current source checkout.
- `host-signing-and-permissions.txt`: human-readable Host signing/TCC readiness report.
- `dumpsys-input.txt`: raw Android input-device inventory retained as an approved hardware-enumeration exception, with line-ending whitespace normalized.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.
- `host-readiness-make.stdout`, `host-readiness-make.stderr`, `host-readiness-make.exit`: retained Host readiness command result; exit code `2` is expected for blocked readiness.
- `make.stdout`, `make.stderr`, `make-exit.txt`: retained native pointer collector command result; exit code `2` is expected for blocked no-mouse evidence.
- `gate.stdout`, `gate.stderr`, `gate-exit.txt`: retained strict gate rerun; exit code `2` proves the blocked bundle is rejected when pass is required.
- `commands.txt`: command transcript with expected non-zero blocked exits.
- `sfltool-start.txt`, `sfltool-end.txt`: retained safety checks for `pgrep -x sfltool || true`; no process was observed.

A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.
This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`. `dumpsys-input.txt` is the approved raw hardware-enumeration exception for this gate: it may retain Android input source masks, bus/vendor/product/location fields, and local display/window identifiers needed to prove that no external mouse-like HID was attached. Treat it as hardware inventory evidence, not user identity or credential material.

## Host readiness blockers

- The `Vibe Screen Dev` codesign identity was not found in the current keychain.
- `/Applications/Vibe Screen.app` failed codesign inspection with a missing/invalid WebRTC framework subcomponent.
- Host listener was not observed on TCP port `54321`.
- The installed Host lacks `com.apple.developer.hid.virtual.device`.
- Screen Recording and Accessibility could not be verified as ready.
- Login/headless readiness remains unverified.

No Android install, launch, ADB reverse mutation, Host start/stop, synthetic pointer injection, or physical HID mouse observation window was performed. The collector ran only the no-mouse blocked branch after reading device identity and Android input-device inventory.
