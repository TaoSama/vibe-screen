# Native pointer HID acceptance: blocked_device_coordination_lock

Created: 2026-08-28T12:11:36Z
Source commit: 1430c3cc18948b93b50b7054e992844f287b6fbc
Reason: Android device coordination lock exists; no ADB command was run and native pointer HID acceptance could not start.
Device: not collected not collected / device-lock-blocked / Android not collected / serial not-collected-device-lock
Requested serial: redacted-requested-serial
ADB was run: false
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
- `host-readiness-make.stdout`, `host-readiness-make.stderr`, `host-readiness-make.exit`: retained Host readiness command result; exit code `2` is expected for blocked readiness.
- `make.stdout`, `make.stderr`, `make-exit.txt`: retained native pointer collector command result; exit code `2` is expected for a blocked device coordination lock.
- `gate.stdout`, `gate.stderr`, `gate-exit.txt`: retained strict gate rerun; exit code `2` proves the blocked bundle is rejected when pass is required.
- `commands.txt`: command transcript with expected non-zero blocked exits.
- `sfltool-start.txt`, `sfltool-end.txt`: retained safety checks for `pgrep -x sfltool || true`; no process was observed.

A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.
This evidence must remain scoped to the exact device identity above.
Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.

## Host readiness blockers

- The `Vibe Screen Dev` codesign identity was not available in the current keychain.
- The installed Host lacks source commit/tree provenance for the current source checkout.
- Screen Recording and Accessibility could not be verified from TCC read-only probes.
- The installed Host is missing `com.apple.developer.hid.virtual.device`.

No Android install, launch, ADB reverse mutation, Host start/stop, synthetic pointer injection, or physical HID observation window was performed. The device-specific P0110 identity was not re-collected in the latest collector run because the shared Android device coordination lock was present.

## Device coordination locks

- /tmp/vibe-screen-device-android.lock: p0110-android-uiux-smoke-20260828 30805 2026-08-28T12:10:26Z
