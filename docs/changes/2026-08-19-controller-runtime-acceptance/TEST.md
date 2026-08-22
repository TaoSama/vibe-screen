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
- [2026-08-22-current-base-controller-runtime-readiness/controller-runtime-summary.json](evidence/2026-08-22-current-base-controller-runtime-readiness/controller-runtime-summary.json)
- [2026-08-22-current-base-controller-runtime-readiness/controller-runtime-readiness.json](evidence/2026-08-22-current-base-controller-runtime-readiness/controller-runtime-readiness.json)
- [2026-08-20-p0110-controller-runtime-readiness/controller-runtime-summary.json](evidence/2026-08-20-p0110-controller-runtime-readiness/controller-runtime-summary.json)
- [2026-08-20-p0110-controller-runtime-readiness/controller-runtime-readiness.json](evidence/2026-08-20-p0110-controller-runtime-readiness/controller-runtime-readiness.json)

The 2026-08-22 current-base readiness run was collected from commit
`1b6f52a2c886c0615cff3c4b85069e29015e7869` under the shared Android device
lock with `adb -s EP0110PZ0B9110300B`. It records the Nubia P0110 / pacific /
Android 16 / SDK 36 device identity and installed APK metadata, but `dumpsys
input` did not expose a physical `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` device.
The installed `/Applications/Vibe Screen.app` was not an Apple identity-signed
Host with the approved virtual HID entitlement, and no Host virtual-gamepad
availability line was observed. The summary is therefore intentionally
`blocked`, with `can_close_runtime_gate=false`.

The 2026-08-20 P0110 readiness run was collected under the shared Android device
lock with `adb -s EP0110PZ0B9110300B`. It recorded the connected Nubia P0110
identity and installed APK metadata, but `dumpsys input` did not expose a
physical `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` device. The running
`/Applications/Vibe Screen.app` was signed without an Apple team identifier and
without the `com.apple.developer.hid.virtual.device` entitlement, and the Host
log still reported controller forwarding unavailable for that reason. The gate
therefore remains blocked.

Recreate the summary with:

```bash
set +e
PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime \
  docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-observations.json \
  --run-id 2026-08-19-blocked-local \
  --output docs/changes/2026-08-19-controller-runtime-acceptance/evidence/blocked-local/controller-runtime-summary.json
test $? -eq 2  # blocked evidence; pass is exit 0
```

For hardware/signing readiness, collect a current-device bundle with:

    python3 scripts/controller_runtime_readiness.py \
      --serial "$ADB_SERIAL" \
      --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
      --host-app "/path/to/Vibe Screen.app" \
      --evidence-dir docs/changes/2026-08-19-controller-runtime-acceptance/evidence/$(date -u +%F)-controller-runtime-readiness

## Offline verification

The source/documentation update was verified with the local offline gates listed
in [build-and-test-results.txt](evidence/blocked-local/build-and-test-results.txt).
The Android and evidence-tool checks passed. MacHost release build passed. MacHost
XCTest remained blocked in this local environment because `xcode-select` points to
Command Line Tools and SwiftPM cannot import `XCTest`; this does not prove or
disprove controller runtime acceptance.

## Overlapping PR audit

As of current base `1b6f52a2c886c0615cff3c4b85069e29015e7869`, the active
controller-runtime owner is this change record plus the shared runbook and
evidence verifier. The older overlapping draft PRs should not be treated as
parallel sources of truth:

- PR #181 (`codex/android-controller-forwarding-rescue`) is superseded by the
  current mainline Android Internet controller forwarding work and is also
  conflicting. Its useful `InternetControllerSendQueue`, `MainActivity`, and
  `InternetProductSession` behavior is already present in current main through
  later controller hardening.
- PR #217 (`codex/peripheral-input-framework`) remains a separate generic
  peripheral-admission framework. It is not required to close the controller
  runtime gate and should not replace the dedicated `ControllerEvent` path.
- PR #220 (`codex/host-virtual-gamepad-hid-injection`) is the source-readiness
  slice for Host virtual-gamepad teardown and packaging entitlement. The
  current-base closure path carries forward only that minimal Host hardening and
  blocked-readiness evidence; it still does not close runtime acceptance without
  hardware, signing, Host availability, and Mac-side observer proof.
