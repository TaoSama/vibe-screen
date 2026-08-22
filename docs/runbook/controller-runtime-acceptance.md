# Controller Runtime Acceptance

Use this runbook only for the controller runtime gate. Offline mapper,
Protocol v1, HID-report, and Host state-machine tests support readiness, but do
not prove macOS accepted a virtual gamepad.

## Preconditions

- Start from the exact source commit under test and record it in the evidence
  bundle.
- Hold `/tmp/vibe-screen-device-android.lock` while using a shared physical
  Android device.
- Use the intended Android serial explicitly, for example
  `adb -s EP0110PZ0B9110300B ...`.
- Attach a named physical controller to the Android device. The Android input
  snapshot must show `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` for that controller;
  synthetic ADB input is not enough.
- Run a matching macOS Host that is Apple identity-signed, not ad-hoc, and whose
  provisioning profile includes the approved
  `com.apple.developer.hid.virtual.device` entitlement.
- Keep a Mac-side controller observer ready, such as a small test target or app
  that logs visible button, axis, trigger, and hat changes from the virtual
  gamepad.

## Readiness Snapshot

Before an interactive run, collect a read-only readiness bundle:

    make baseline-macos-host-readiness EVIDENCE_DIR=docs/changes/2026-08-19-controller-runtime-acceptance/evidence/$(date -u +%F)-host-readiness

    python3 scripts/controller_runtime_readiness.py \
      --serial "$ADB_SERIAL" \
      --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
      --host-app "/path/to/Vibe Screen.app" \
      --write-blocked-on-lock \
      --evidence-dir docs/changes/2026-08-19-controller-runtime-acceptance/evidence/$(date -u +%F)-controller-runtime-readiness

`host-readiness.json` must report `can_start_controller_runtime_gate=true`
before the runtime run starts. If no physical controller, signed Host, approved
entitlement, Host listener, or Host virtual gamepad availability is present, the
summary must remain `blocked`. Do not turn that into a runtime pass. If
/tmp/vibe-screen-device-soak.lock or /tmp/vibe-screen-device-android.lock
already exists and you do not own it, the collector must not run ADB; use
--write-blocked-on-lock to preserve the lock state as blocked readiness
evidence.

## Runtime Run

1. Record Android device identity, APK version/signing identity, install time,
   battery state, display size/density, and `adb devices -l` output.
2. Capture `adb -s "$ADB_SERIAL" shell dumpsys input` and keep the controller
   name, descriptor, external state, and `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` line.
3. Start the Host, confirm its log reports controller forwarding available, and
   retain codesign and entitlement output for the running app.
4. Establish an active Protocol v1 USB, LAN, or Internet session. Record the
   negotiated capability set and verify controller is accepted.
5. With the Android client foregrounded on the streaming view, actuate the
   physical controller: one button press/release, one stick movement, and one
   trigger or hat movement when supported by the device.
6. Record Android production forwarding logs from MainActivity/StreamClient and
   Protocol v1 controller envelopes for `CONNECTED`, `STATE`, and `DISCONNECTED` with
   a stable `controller_id` and monotonic epoch.
7. Record Host controller injection logs and a Mac-side observer result showing
   the virtual gamepad input is visible to an ordinary macOS consumer.
8. Disconnect the Android client, unplug the controller, or intentionally drop
   the transport. Retain logs showing all-zero neutral release before teardown
   and verify the Mac-side observer no longer sees any pressed button or
   non-neutral axis.

## Evidence Bundle

Keep all artifacts under one dated directory:

- `README.md`: scope, source commit, device/controller/Host identity, verdict,
  and boundaries.
- `controller-runtime-observations.json` and `controller-runtime-summary.json` from
  `PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime`.
- `adb-devices.txt`, `device-info.json`, `dumpsys-input.txt`, `dumpsys-package.txt`,
  `android-diag.log`, and focused controller logcat.
- `host-codesign.txt`, `host-controller-availability.txt`, and Host controller
  injection log tail.
- Mac-side observer log, screenshot, or video showing visible controller input.
- Disconnect neutral-release log with before/after controller state.
- `commands.txt` and checksums for manually collected artifacts.

The gate closes only when `controller-runtime-summary.json` reports
`can_close_runtime_gate=true`. A `blocked` or `insufficient` verdict documents
readiness state only.
