# Native pointer HID acceptance: blocked

Created: 2026-08-30T07:08:34Z
Source commit: 87e16d8bea4446c1ca449045678f1bafc7fd6cb2
Reason: No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.
Device: nubia P0110 / pacific / Android 16 / serial redacted-pacific-serial
Requested serial: redacted-requested-serial
ADB was run: true
External mouse devices: 0
Observed Android pointer events: none
Observed Host pointer events: none
Stable signed/TCC Host ready: false
Visible Mac result: not recorded
Host readiness: blocked from a clean `origin/main` checkout; `host-readiness.json` reports `can_start_native_hid_gate=false`.

## Artifacts

- `result.json`: structured gate result, device identity, source devices, and checksums.
- `native-pointer-hid-summary.json`: independent gate summary with `can_close_native_pointer_hid_gate`.
- `host-readiness.json`: shared Host prerequisite snapshot captured from a clean current-base checkout.
- `host-signing-and-permissions.txt`: human-readable Host signing/TCC readiness report.
- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized.
- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.
- `host-log-appended.txt`: bounded Host log window for pointer injection.
- `host-readiness-make.exit`: retained Host readiness command exit; `2` is expected for blocked readiness.
- `make-exit.txt`: retained native pointer collector command exit; `2` is expected for blocked no-mouse evidence.
- `gate.stdout`, `gate.stderr`, `gate-exit.txt`: retained strict gate rerun; exit code `2` proves the blocked bundle is rejected when pass is required.
- `commands.txt`: command transcript with expected non-zero blocked exits.
- `sfltool-start.txt`, `sfltool-end.txt`: retained safety checks for `pgrep -x sfltool || true`; no process was observed.

A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.
This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.

## Host readiness blockers

- The `Vibe Screen Dev` codesign identity was not found in the current keychain.
- `/Applications/Vibe Screen.app` failed codesign inspection with a missing/invalid WebRTC framework subcomponent.
- Host listener was not observed on TCP port `54321`.
- The installed Host lacks `com.apple.developer.hid.virtual.device`.
- Screen Recording and Accessibility could not be verified as ready.
- Login/headless readiness remains unverified.

No Android install, launch, ADB reverse mutation, Host start/stop, synthetic pointer injection, or physical HID mouse observation window was performed. The collector ran only the no-mouse blocked branch after reading device identity and Android input-device inventory.
