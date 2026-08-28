# Controller runtime acceptance gate

Date: 2026-08-19

## Scope

This record advances the controller runtime gate without converting offline
coverage into device evidence. Android production forwarding is present in the
current source path: controller key events enter `MainActivity.dispatchKeyEvent`,
controller motion events enter `MainActivity.handleGenericMotion`, and both route
through `StreamClient.sendController` when Protocol v1 negotiates
`CAPABILITY_CONTROLLER`.

That source wiring does not close runtime acceptance. The remaining gate needs a
named physical Android controller, accepted controller capability, an
identity-signed Host build with the approved virtual HID entitlement, Host
virtual-gamepad runtime availability, a visible Mac-side controller target, and
neutral release on disconnect.

## Current blocked evidence

The local environment used for this update did not have a physical Android
controller attached and did not have an identity-signed, entitled Host capable of
creating a virtual gamepad. The evidence summary is therefore intentionally
`blocked`, not `pass`:

- [blocked-local/controller-runtime-summary.json](evidence/blocked-local/controller-runtime-summary.json)
- [blocked-local/controller-runtime-observations.json](evidence/blocked-local/controller-runtime-observations.json)
- [2026-08-20-p0110-controller-runtime-readiness/controller-runtime-summary.json](evidence/2026-08-20-p0110-controller-runtime-readiness/controller-runtime-summary.json)
- [2026-08-20-p0110-controller-runtime-readiness/controller-runtime-readiness.json](evidence/2026-08-20-p0110-controller-runtime-readiness/controller-runtime-readiness.json)
- [2026-08-23-current-base-controller-runtime-readiness/controller-runtime-summary.json](evidence/2026-08-23-current-base-controller-runtime-readiness/controller-runtime-summary.json)
- [2026-08-23-current-base-controller-runtime-readiness/controller-runtime-readiness.json](evidence/2026-08-23-current-base-controller-runtime-readiness/controller-runtime-readiness.json)

The 2026-08-20 P0110 readiness run was collected under the shared Android device
lock with `adb -s <redacted-adb-serial>`. It recorded the connected Nubia P0110
identity and installed APK metadata, but `dumpsys input` did not expose a
physical `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` device. The running
`/Applications/Vibe Screen.app` was signed without an Apple team identifier and
without the `com.apple.developer.hid.virtual.device` entitlement, and the Host
log still reported controller forwarding unavailable for that reason. The gate
therefore remains blocked.

The 2026-08-23 current-base readiness run was also collected under
`/tmp/vibe-screen-device-android.lock` with `adb -s <redacted-adb-serial>`. It
again recorded the connected device as Nubia P0110 / pacific / Android 16 / SDK
36 and found no physical `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` controller. The
installed APK metadata was unavailable because `dumpsys package
dev.telemachus.display` reported no installed package. The local
`/Applications/Vibe Screen.app` was signed with `TeamIdentifier=not set`, had an
empty runtime entitlements dictionary, and the scanned Host log had no
controller availability line. The summary is intentionally `blocked` with
`can_close_runtime_gate=false`; it is not controller runtime acceptance.

Recreate the summary with:

```bash
set +e
PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime \
  docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-observations.json \
  --run-id 2026-08-19-blocked-local \
  --output docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-summary.json
status=$?
set -e
test "$status" -eq 2
```

For hardware/signing readiness, collect a current-device bundle with:

    python3 scripts/controller_runtime_readiness.py \
      --serial "$ADB_SERIAL" \
      --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
      --host-app "/path/to/Vibe Screen.app" \
      --write-blocked-on-lock \
      --evidence-dir docs/changes/2026-08-19-controller-runtime-acceptance/evidence/$(date -u +%F)-controller-runtime-readiness

## Offline verification

The source/documentation update was verified with the local offline gates listed
in [build-and-test-results.txt](evidence/blocked-local/build-and-test-results.txt).
The Android and evidence-tool checks passed. MacHost release build passed. MacHost
XCTest remained blocked in this local environment because `xcode-select` points to
Command Line Tools and SwiftPM cannot import `XCTest`; this does not prove or
disprove controller runtime acceptance.

## 2026-08-25 current-base refresh

The 2026-08-25 current-base readiness run refreshed the same owner gate from
`origin/main` commit `87605d6863e8f2372d3092f3e625459b8520124f`. It used the
shared Android device lock and `adb -s <device-serial>`, recorded the connected
device as Nubia P0110 / pacific / Android 16 / SDK 36, and found no physical
`SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` controller. The installed APK metadata was
unavailable because `dumpsys package dev.telemachus.display` reported no
installed package. `/Applications/Vibe Screen.app` existed, but was signed with
`TeamIdentifier=not set`, had no `com.apple.developer.hid.virtual.device`
entitlement, and the scanned Host log had no controller availability line. The
resulting `controller-runtime-summary.json` is `blocked` with
`can_close_runtime_gate=false`; it does not close the runtime gate.

- [2026-08-25-p0110-controller-runtime-current-base-blocked-87605d6/controller-runtime-summary.json](evidence/2026-08-25-p0110-controller-runtime-current-base-blocked-87605d6/controller-runtime-summary.json)
- [2026-08-25-p0110-controller-runtime-current-base-blocked-87605d6/controller-runtime-readiness.json](evidence/2026-08-25-p0110-controller-runtime-current-base-blocked-87605d6/controller-runtime-readiness.json)
