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
shared Android device lock and `adb -s <redacted-adb-serial>`, recorded the connected
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

## 2026-08-27 current-base refresh

The 2026-08-27 current-base readiness run refreshed the controller runtime gate
from `origin/main` commit `3b2ba11e832a3618eaedfc67f92414b161423a00` using a
clean detached worktree. Android commands used `adb -s <redacted-adb-serial>` and the
connected device was recorded as Nubia P0110 / pacific / Android 16 / SDK 36.
No physical `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` controller was visible. The
installed Host listener was present, but Host readiness remained blocked by
missing source provenance, unavailable read-only TCC verification, missing
`com.apple.developer.hid.virtual.device`, and missing virtual-gamepad
availability. The summary is intentionally `blocked` with
`can_close_runtime_gate=false`; it is not controller runtime acceptance.

- [2026-08-27-p0110-controller-runtime-current-base-blocked-3b2ba11/controller-runtime-summary.json](evidence/2026-08-27-p0110-controller-runtime-current-base-blocked-3b2ba11/controller-runtime-summary.json)
- [2026-08-27-p0110-controller-runtime-current-base-blocked-3b2ba11/controller-runtime-readiness.json](evidence/2026-08-27-p0110-controller-runtime-current-base-blocked-3b2ba11/controller-runtime-readiness.json)

## 2026-08-27 PR-head refresh

After merging `origin/main` commit `32b05030cf4cff54029d9bffd4c9dd0cb7e1d6e3`
into `codex/p0110-peripheral-runtime-gates`, PR-head commit
`7e06483becdc1b63f0de74dfed56342eed2d0aba` was checked again. Android
commands used `adb -s <redacted-adb-serial>` and the connected device was recorded as
Nubia P0110 / pacific / Android 16 / SDK 36. No physical `SOURCE_GAMEPAD` or
`SOURCE_JOYSTICK` controller was visible. Host readiness remained blocked by the
missing approved virtual HID entitlement and lack of identity-signed runtime
availability evidence. The summary is intentionally `blocked` with
`can_close_runtime_gate=false`; it is not controller runtime acceptance.

- [2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483/controller-runtime-summary.json](evidence/2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483/controller-runtime-summary.json)
- [2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483/controller-runtime-readiness.json](evidence/2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483/controller-runtime-readiness.json)

## 2026-08-29 current-base refresh

The 2026-08-29 current-base readiness run refreshed the controller owner gate
from origin/main commit 1217c585f5a0185402bdc47fc588ac8092066067 after
origin/main advanced and the earlier PR head became behind. Host readiness was
collected into a temporary directory outside the repository first, so
host-readiness.json records current_source_dirty=false for that source commit
before the public evidence bundle was copied into docs/. The run checked the
shared Android device lock state and used adb -s <device-serial>, recorded the
connected device as nubia P0110 / pacific / Android 16 / SDK 36, and found no
physical SOURCE_GAMEPAD or SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/controller-runtime-summary.json](evidence/2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/controller-runtime-summary.json)
- [2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/controller-runtime-readiness.json](evidence/2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/controller-runtime-readiness.json)
- [2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/host-readiness.json](evidence/2026-08-29-p0110-controller-runtime-current-base-blocked-1217c58/host-readiness.json)

## 2026-08-30 current-base refresh

The 2026-08-30 current-base readiness run refreshed the controller owner gate
from origin/main commit 4884d80813a7f674a10d574a96f8dfcf5723c6e7 after
origin/main advanced again. Host readiness was collected from a detached
current-base worktree into a temporary directory first, so host-readiness.json
records current_source_dirty=false for that source commit before the public
evidence bundle was copied into docs/. The run used adb -s <device-serial>,
recorded the connected device as nubia P0110 / pacific / Android 16 / SDK 36,
and found no physical SOURCE_GAMEPAD or SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-4884d80/host-readiness.json)

## 2026-08-30 current-base refresh after clipboard gate merge

The later 2026-08-30 current-base readiness run refreshed the controller owner
gate from origin/main commit 32146152100477660eaf0ddb10befa8af48ea4fd after
origin/main advanced through the clipboard E2E evidence gate. Host readiness was
collected from a detached current-base worktree into a temporary directory
first, so host-readiness.json records current_source_dirty=false for that source
commit before the public evidence bundle was copied into docs/. The controller
readiness command also ran from that detached current-base worktree. The run
used adb -s <device-serial>, recorded the connected device as nubia P0110 /
pacific / Android 16 / SDK 36, and found no physical SOURCE_GAMEPAD or
SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-3214615/host-readiness.json)

## 2026-08-30 current-base refresh after trusted LAN gate merge

The latest 2026-08-30 current-base readiness run refreshed the controller owner
gate from origin/main commit e647b6dcd0ea18907d6812a4d5f692f9eb63dfcd after
origin/main advanced through the trusted LAN blocked gate. Host readiness was
collected from a detached current-base worktree into a temporary directory
first, so host-readiness.json records current_source_dirty=false for that source
commit before the public evidence bundle was copied into docs/. The controller
readiness command also ran from that detached current-base worktree. The run
used adb -s <device-serial>, recorded the connected device as nubia P0110 /
pacific / Android 16 / SDK 36, and found no physical SOURCE_GAMEPAD or
SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-e647b6d/host-readiness.json)

## 2026-08-30 current-base refresh after macOS login/headless gate merge

The latest 2026-08-30 current-base readiness run refreshed the controller owner
gate from origin/main commit 31d0d42558e8a6749e24936e9a8c4b821d94847e after
origin/main advanced through the macOS login/headless readiness evidence. Host
readiness was collected from a detached current-base worktree into a temporary
directory first, so host-readiness.json records current_source_dirty=false for
that source commit before the public evidence bundle was copied into docs/. The
controller readiness command also ran from that detached current-base worktree.
The run used adb -s <device-serial>, recorded the connected device as nubia
P0110 / pacific / Android 16 / SDK 36, and found no physical SOURCE_GAMEPAD or
SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-31d0d42/host-readiness.json)

## 2026-08-30 current-base refresh after hardware keyboard gate merge

The latest 2026-08-30 current-base readiness run refreshed the controller owner
gate from origin/main commit 5d2d25fcaeef6060ee4916bdea02afbc859d02fe after
origin/main advanced through the hardware keyboard current-base blocked
evidence. Host readiness was collected from a detached current-base worktree
into a temporary directory first, so host-readiness.json records
current_source_dirty=false for that source commit before the public evidence
bundle was copied into docs/. The controller readiness command also ran from
that detached current-base worktree. The run used adb -s <device-serial>,
recorded the connected device as nubia P0110 / pacific / Android 16 / SDK 36,
and found no physical SOURCE_GAMEPAD or SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-5d2d25f/host-readiness.json)

## 2026-08-30 current-base refresh after external latency gate merge

The latest 2026-08-30 current-base readiness run refreshed the controller owner
gate from origin/main commit f9c7716785921776021680ab7e5af0c01e55121d after
origin/main advanced through the external latency current-base blocked evidence.
Host readiness was collected from a detached current-base worktree into a
temporary directory first, so host-readiness.json records
current_source_dirty=false for that source commit before the public evidence
bundle was copied into docs/. The controller readiness command also ran from
that detached current-base worktree. The run used adb -s <device-serial>,
recorded the connected device as nubia P0110 / pacific / Android 16 / SDK 36,
and found no physical SOURCE_GAMEPAD or SOURCE_JOYSTICK controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status.

- [2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/controller-runtime-summary.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/controller-runtime-summary.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/controller-runtime-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/controller-runtime-readiness.json)
- [2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/host-readiness.json](evidence/2026-08-30-p0110-controller-runtime-current-base-blocked-f9c7716/host-readiness.json)

## 2026-08-31 retained blocked snapshot

The 2026-08-31 directory label is the Asia/Shanghai local run date; retained
JSON timestamps stay in UTC (`2026-08-30T21:24:57Z` for controller readiness and
`2026-08-30T21:18:32.995143+00:00` for shared Host readiness). The readiness
run was collected at source commit 075dc157c36ba71df9f757e571015905881a7154,
which was the owner branch's current source at collection time. This record is
retained in the current-base owner package after origin/main advanced through
967e05f4266916569f0898d7e2ed53e3a2602da9,
d610553d9c81bf1eae4342abc0dfcf02051696cb, and the refreshed PR base
c79fad2c554db9fbaf912d28aefa5b5d2007fb83; it is a historical blocked snapshot,
not evidence that any later PR base closed controller runtime acceptance. The
Android readiness command ran from a clean detached worktree with the shared
Host readiness snapshot supplied through `--host-readiness`. The run used adb
-s <device-serial>, recorded the connected device as nubia P0110 / pacific /
Android 16 / SDK 36, and found no physical SOURCE_GAMEPAD or SOURCE_JOYSTICK
controller.

The shared Host readiness snapshot remained blocked: the configured development
codesign identity was unavailable, /Applications/Vibe Screen.app failed codesign
inspection because a sealed WebRTC.framework resource is missing or invalid, no
Host listener was observed on TCP 54321, the installed Host did not expose
com.apple.developer.hid.virtual.device, and Host availability had no controller
forwarding line. The readiness command did not opt into login-item diagnostics,
so /usr/bin/sfltool dumpbtm was not requested. pgrep -x sfltool || true was
checked before and after the critical readiness commands and found no residual
process.

The resulting controller-runtime-summary.json is intentionally blocked with
can_close_runtime_gate=false; this record does not close controller runtime
acceptance and does not change the README-facing open gate status. The summary
also records the shared Host readiness blockers from `--host-readiness`, so the
controller-specific bundle and host-readiness.json stay aligned.

- [2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/controller-runtime-summary.json](evidence/2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/controller-runtime-summary.json)
- [2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/controller-runtime-readiness.json](evidence/2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/controller-runtime-readiness.json)
- [2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/host-readiness.json](evidence/2026-08-31-p0110-controller-runtime-current-base-blocked-075dc157/host-readiness.json)
