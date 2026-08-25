# Android client operation and acceptance

This runbook covers the runnable Android client. It distinguishes the legacy
touch-compatible fallback from Protocol v1 native-input behavior, and keeps
synthetic ADB input separate from physical HID evidence.

## Device ownership gate

Before any ADB command, check whether a coordinated device run owns the target:

```bash
test ! -e /tmp/vibe-screen-device-soak.lock
test ! -e /tmp/vibe-screen-device-android.lock
```

If either file exists, do not connect, install, launch, force-stop, change ADB
reverse mappings, probe the media port, or start a competing Mac host. Wait for
the owner to remove the lock. A concurrent install or port probe invalidates a
soak window even if the stream later recovers.

After coordination grants a short Android lease, atomically create
`/tmp/vibe-screen-device-android.lock` before the first ADB command. Remove it
immediately after stopping the test client/server and report the release so
other tasks can proceed.

## Offline gate

Run this without a device or Mac host:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
```

The JVM suite covers Fit/Fill corners through all four rotations, viewport and
decoder-surface dimensions, common physical keyboard-to-HID sequences, native
pointer capability gating and release ordering, controller mapping/state,
session-generation/capability gating, Camera settings-return policy, bounded
outbound ordering, typed connection guidance, reconnect backoff, framing, and
reliability. This proves code paths and packaging only; it is not device
acceptance.
For color behavior, the offline suite may prove SDR decode configuration and
HDR-to-SDR fallback negotiation only. Do not report Android HDR decode/display
support until the [HDR/color acceptance runbook](hdr-color-acceptance.md) has a
retained real-device HDR run.

The Phase 1 actionable-error state owner matrix is tracked in
docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json.
Run the gate from the repository root to verify that each Android
SessionFailureKind has documented user-visible guidance and that Host-side
permission/startup/capture states have an owner:

```bash
cd /path/to/vibe-screen
make actionable-error-states-gate
```

This is an offline drift gate; it does not replace the device checks below.

## Install after acquiring the device

Resolve and record the exact device identity before changing it. Always pass
the explicit serial:

```bash
adb connect DEVICE_HOST:5555
adb -s DEVICE_HOST:5555 devices -l
adb -s DEVICE_HOST:5555 shell getprop ro.serialno
adb -s DEVICE_HOST:5555 shell getprop ro.product.manufacturer
adb -s DEVICE_HOST:5555 shell getprop ro.product.model
adb -s DEVICE_HOST:5555 shell getprop ro.build.fingerprint
adb -s DEVICE_HOST:5555 shell getprop ro.build.version.sdk
adb -s DEVICE_HOST:5555 install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
```

The lease-controlled endpoint has previously identified as a
Nubia P0110, not Xiaomi 13 (2211133C). Recheck rather than assuming its identity.

## Read-only USB live-stream smoke

Use this helper after the Host and Android app are already connected and
streaming. It is safe for an observation-only pass because it does not install,
launch, stop, clear logs, change ADB reverse mappings, probe the Host port, or
inject input:

```bash
test ! -e /tmp/vibe-screen-device-android.lock
test ! -e /tmp/vibe-screen-device-soak.lock
make evidence-usb-live-smoke \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_DIR=.build/evidence/usb-live-smoke
```

If you own an existing coordinated lock, invoke the module directly with
`--allow-existing-device-lock`. If another task owns the lock, use
`--write-blocked-on-lock` to preserve a blocked JSON record and exit non-zero
without running ADB. A `pass` result requires the device identity, `tcp:54321`
reverse mapping, foreground MainActivity, running package PID, positive
current-process `VibeScreenTelemetry` `stream_stats`, and active MediaCodec
decoder output from current-process `logcat` lines. Fresh sessions may include
decoder setup and first-output lines; long-running sessions may instead prove
decoder activity through continuing frame counters. The private diagnostic log
is context only and cannot independently support a `pass`. It is a
reproducibility smoke only: keep all README soak, Host RSS, latency,
native-pointer, stylus, and controller gates open unless their dedicated
evidence is present. Nubia P0110/pacific summaries are general Android
substitute evidence and must not be relabeled as Xiaomi 13/fuxi.

## Viewport checks

Open the in-stream settings button:

1. Confirm **Fit** preserves the entire frame and letterboxes as needed.
2. Confirm **Fill** crops evenly and touches at the visible edges map inside
   the cropped video, not to the hidden frame edge.
3. Cycle rotation through Follow Mac, 90°, 180°, and 270°; tap all four corners
   after each change and correlate the Android event with the Mac pointer.
4. Disconnect and reconnect; confirm scale and rotation preferences persist.
5. Confirm from the UI and diagnostic logs whether the session is legacy
   fallback or Protocol v1. Report Android display enumeration or selection
   only when Protocol v1 multi-display negotiation and the display selector
   were actually exercised in that run.

Connected windows use `FLAG_SECURE`, so ADB screenshots of the stream may be
black. Use diagnostic logs plus direct observation or an external camera.

## Reconnect timing gate

Use this gate only for a Protocol v1 USB or trusted-LAN session. It is stricter
than the reconnect smoke checks: the timing window starts at the operator
recorded disruption timestamp and ends only when Android records the decoder's
first output frame after recovery. A Host accept, Android retry line, Activity
callback, or first encoded frame is diagnostic only.

Before starting, acquire the Android device lease and record device identity,
Host PID, Host build/signing identity, ADB reverse state, and the private
Android diag log path. Every ADB command for the current shared phone must use
the explicit serial `adb -s <device-serial> ...`, and evidence from that
phone must remain labeled Nubia P0110/pacific/Android 16.

Collect one `reconnect-timing-observations.json` with separate attempts for all
three disruption kinds:

- `client-kill`: force-stop or kill only the Android app process, then wait for
  Protocol v1 recovery and first decoder output frame with the same Host PID.
- `adb-reverse-disconnect`: remove `tcp:54321`, restore it, then prove the
  restored mapping and first decoder output frame in the recovered session.
- `lan-network-interrupt`: interrupt the trusted-LAN path, then prove AES-GCM
  record negotiation, no legacy plaintext fallback, Protocol v1 recovery, and
  first decoder output frame.

Evaluate the record with the fail-closed summary tool:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.reconnect_timing \
  "$EVIDENCE_DIR/reconnect-timing-observations.json" \
  --output "$EVIDENCE_DIR/reconnect-timing-summary.json"
```

Use `--require-disruption` only for an incremental single-scenario readiness
run. If Host signing, TCC, port `54321`, ADB, or LAN conditions block the run,
write a blocked summary instead of reclassifying ordinary reconnect logs:
The README gate closes only when the generated summary has both `verdict=pass`
and `can_close_timing_gate=true`. Single-scenario or otherwise scoped runs can
use `can_close_requested_scope=true` for local progress, but that field is not a
release claim.

```bash
make evidence-reconnect-timing-blocked \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  RECONNECT_TIMING_BLOCKER_ARGS='--blocker "Vibe Screen Dev signing identity is unavailable in the current keychain" --blocker "Host is not listening on 127.0.0.1:54321 in this worktree"' \
  RECONNECT_TIMING_ARTIFACT_ARGS='--artifact "docs/changes/<change>/evidence/<run>/host-54321-listener.txt" --artifact "docs/changes/<change>/evidence/<run>/macos-dev-host-preflight.txt"' \
  RECONNECT_TIMING_NOTES_ARG='--notes "Blocked readiness record only; no real Protocol v1 reconnect timing attempt was run."'
```

### Rotated host-display acceptance

Client-local rotation is the Android Surface/input transform selected in the
Viewport settings. Host display rotation is macOS display state advertised by
the Host. Do not combine them when judging touch mapping: the current client
keeps the Surface/input transform client-local and uses host rotation only for
device orientation.

To close the rotated host-display gate, run a fresh Protocol v1 real-device
pass for both an existing physical Mac display and a virtual display after the
host display itself is rotated to 90°, 180°, or 270°. For each display kind,
record the explicit device identity, Host signing/TCC preflight for the exact
installed Host bundle, original and rotated host-display snapshots, Android
visual result, corner/center touch matrix, Host log, Android logcat, stable
stream/no-teardown result, and proof that the original macOS rotation was
restored. The existing client-local Follow Mac/90°/180°/270° matrix with
`hostRotation=0` is not host display rotation evidence. The detailed operator
checklist is in `docs/runbook/host-display-rotation-acceptance.md`.

After collecting those artifacts, summarize them in `host-display-rotation.json`
and run the offline evidence-summary gate. The gate only validates the retained
record; it does not rotate displays, start the Host, or touch ADB:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_gate \
  docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation.json \
  --check-artifacts \
  --output docs/changes/2026-08-05-phase-1-android-client/evidence/<run>/host-display-rotation-gate.json
```

## Input matrix

Use a non-sensitive Mac test window and grant Accessibility to the exact host
binary. Record Android diagnostic logs and the visible Mac result for each.
Before running the opt-in touch-gesture acceptance driver, collect the
read-only fixed-binary preflight and keep it with the evidence directory:

```bash
make evidence-touch-rerun-preflight \
  EVIDENCE_SERIAL=<adb-serial> \
  EVIDENCE_DIR=<evidence-dir> \
  TOUCH_RERUN_EXPECTED_HOST_SHA256=<fixed-host-binary-sha256>
```

Do not run the gesture driver if the preflight result is `blocked`. Record the
actual device identity from the preflight output; the Nubia P0110/pacific is a
valid Android substitute for general client dispatch, but it is not Xiaomi
13/fuxi evidence.

### Legacy compatibility path

Use this table only when the session falls back to the legacy touch-compatible
path or the peer has not negotiated Protocol v1 native-input capabilities.

| Input | Expected behavior |
| --- | --- |
| tap / double tap | left click / double click |
| long press | right click |
| long press then move | left-button drag |
| two-finger parallel move | scroll |
| two-finger distance change | command-scroll zoom |
| external mouse wheel | two-finger scroll adapter |
| external secondary button | long-press right-click adapter |
| physical keyboard / shortcut | compatibility message; no bytes sent |

ADB event injection can exercise Android dispatch but does not prove a physical
mouse or keyboard. Physical-peripheral acceptance requires the named hardware
and a visible Mac-side result.

### Protocol v1 native input

Use this table only after the Host and client have negotiated the matching
Protocol v1 capability. Record the client diagnostic log line for the capability
negotiation and the host log line for the received event.

| Input | Required evidence |
| --- | --- |
| physical keyboard key / shortcut | Android `KeyEvent` source and key code, mapped USB HID usage, host key injection, visible Mac text/shortcut result, and key-up release |
| physical mouse hover or move | Android `MotionEvent` from `SOURCE_MOUSE`, `SOURCE_MOUSE_RELATIVE`, `SOURCE_TOUCHPAD`, or `SOURCE_TRACKBALL`, host `PointerEvent` with `INPUT_PHASE_CHANGED`, visible Mac pointer movement, and no fallback touch gesture claim |
| physical mouse primary click | button press and release with `BUTTON_PRIMARY`, host pointer begin/end events, visible Mac click result, and button-up release before disconnect |
| physical mouse wheel | Android `ACTION_SCROLL` with `AXIS_VSCROLL` or `AXIS_HSCROLL`, host scroll injection, and visible Mac scroll result |
| physical stylus | Android stylus source/tool kind plus pressure/tilt/barrel/hover fields as applicable, negotiated stylus capability, host tablet event construction, and drawing-app result |
| physical controller | Android controller mapping/state, production forwarding through `MainActivity` and `StreamClient`, and Protocol v1 envelope encoding are offline-tested. Runtime acceptance still requires a named physical controller, Android `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` logs, negotiated controller capability, a stable controller ID, connected/state/disconnected samples, host virtual-gamepad availability from an entitled Host, visible Mac-side controller response, and neutral release on disconnect |

Native pointer move/click cannot be closed with `adb shell input tap/swipe`:
those commands synthesize touchscreen contact, not HID hover or mouse-button
events. They may support touch and mapper regression notes, but the native
pointer gate remains open without a physical mouse or equivalent Android HID
pointer. Controller production forwarding is wired and covered offline, but
runtime acceptance still needs a physical controller and an entitled Host; JVM
mapper tests and constructed Protocol v1 envelopes prove serialization only.
Before any native-pointer, stylus, hardware-keyboard, or controller runtime
attempt, run `make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>`
and retain `host-readiness.json` plus `host-signing-and-permissions.txt`. The
matching per-gate `can_start_*` field is only a prerequisite to begin runtime
collection; it does not close the gate.

For the native pointer HID mouse gate, require
`can_start_native_hid_gate=true`, connect a real USB or Bluetooth mouse before
starting the observation window, and run:

```bash
make native-pointer-hid-acceptance \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  NATIVE_POINTER_HOST_LOG="$HOME/Library/Logs/Telemachus/telemachus.log" \
  NATIVE_POINTER_HOST_READY_ARG="--host-stable-signed-tcc-ready" \
  NATIVE_POINTER_VISIBLE_RESULT_NOTE="Mac cursor moved and the primary click focused <target app>" \
  EVIDENCE_DIR=docs/changes/2026-08-05-phase-1-android-client/evidence/$(date -u +%F)-native-pointer-hid
```

The script records `dumpsys input`, Android `MA` logcat for the observation
window, and the newly appended Host log segment. First run
`python3 scripts/macos_dev_host.py preflight`; add
`NATIVE_POINTER_HOST_READY_ARG="--host-stable-signed-tcc-ready"` only after a
stable signed Host with Screen Recording and Accessibility permission passes
that preflight. A pass requires Android
`native pointer forwarded` lines for `MOVE`, `BUTTON_PRESS`, and
`BUTTON_RELEASE` from `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL`,
plus Host `Pointer injected` lines for `changed`, `began`, and `ended`. Missing
hardware or missing Host stable signing/TCC evidence is `blocked`; missing
Android logs, Host logs, or the visible-result note is `failed`, not a pass.

The collection target writes `native-pointer-hid-summary.json`. That summary is
the gate owner for README updates: only `verdict=pass` and
`can_close_native_pointer_hid_gate=true` can close native pointer move/click.
Blocked or insufficient summaries must keep the README pending wording intact.
Re-check an existing evidence bundle with:

```bash
make native-pointer-hid-gate \
  EVIDENCE_DIR=docs/changes/2026-08-05-phase-1-android-client/evidence/<run-dir>
```

For physical stylus drawing-app evidence, the collector writes both
`stylus-evidence.json` and the independent `stylus-summary.json` gate owner.
Only `stylus-summary.json` with `verdict=pass` and
`can_close_physical_stylus_gate=true` can close the README physical-stylus
drawing-app gate. Capability-only, synthetic ADB stylus, lock-blocked, missing
Host-log, or missing Android diagnostic records must remain blocked or
insufficient. Re-check a bundle with:

```bash
make physical-stylus-gate \
  EVIDENCE_DIR=docs/changes/2026-08-19-physical-stylus-acceptance/evidence/<run-dir>
```

Summarize controller runs, including blocked controller runs, with:

```bash
set +e
PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime \
  controller-runtime-observations.json \
  --output controller-runtime-summary.json
status=$?
set -e
test "$status" -eq 0 -o "$status" -eq 2
```

The summarizer exits `0` only for `pass`, `2` for `blocked`, and `1` for
`insufficient` or malformed evidence; read `can_close_runtime_gate` before
claiming acceptance.

## Physical stylus acceptance

Use this gate only with a Protocol v1 USB/LAN/Internet session and a real stylus
on the named Android device. First retain shared Host readiness with
`can_start_stylus_gate=true`. Do not clear app data, reset permissions, change
ADB reverse mappings, or run a long soak for this check; the stylus pass is a
short interactive input confirmation.

First collect the read-only device capability snapshot:

```bash
python3 scripts/android_stylus_acceptance.py \
  --serial DEVICE_SERIAL \
  --output-dir docs/changes/2026-08-19-physical-stylus-acceptance/evidence/YYYY-MM-DD-device-stylus
```

This records device identity, `dumpsys input`, stylus input-device candidates,
the app private diagnostic log when `run-as` can read it, and
`stylus-summary.json`. A result of
`blocked_physical_stylus_not_observed` is expected when no human has drawn with
the pen; pressure/tilt/barrel capability in `dumpsys input` is necessary
evidence, not acceptance. For a later pass, at least one candidate must expose
the Android `STYLUS` source and both pressure and tilt axes; stylus-named
devices or touch-only pressure axes are readiness clues only.

If a shared device lock exists before the first ADB command, write a blocked
readiness record instead of probing the device:

    python3 scripts/android_stylus_acceptance.py \
      --serial DEVICE_SERIAL \
      --output-dir docs/changes/2026-08-19-physical-stylus-acceptance/evidence/YYYY-MM-DD-device-stylus-lock-blocked \
      --write-blocked-on-lock

That lock-blocked record proves the gate could not start; it does not include
device capability evidence and cannot close physical-stylus acceptance.

For a passing run, open a non-sensitive macOS drawing app in the streamed display
and record all of the following in the evidence directory:

- a short raw Android event capture from the physical stylus device, for
  example `adb -s DEVICE_SERIAL shell getevent -lt /dev/input/event7`, started
  only after the device lease is acquired and stopped immediately after the
  drawing stroke. On Nubia P0110/pacific the stylus device has appeared as
  `goodix_stylus_input`; re-resolve the event path from `getevent -lp` for each
  run rather than assuming it is still `/dev/input/event7`;
- the same script output with `--observed-physical-drawing`,
  `--drawing-observation`, `--host-log HOST_STYLUS_LOG`, and
  `--host-stable-signed-tcc-ready` only after
  `python3 scripts/macos_dev_host.py preflight` passes; in this mode the
  tool records the Host log cursor before the observation window and validates
  only the new Host log bytes appended while the operator draws;
- Android diag log entries from the same connected session with
  `Stylus forwarded:` plus sample count, extended-stylus negotiation state,
  raw Android `MotionEvent` source, raw action, raw tool type, phase, contact
  state, tool kind, buttons, pressure, and signed `tiltX` / `tiltY`;
- host log excerpts showing stylus injection with pressure and signed two-axis
  tilt, plus barrel/proximity fields when exercised;
- a written observation or external-camera note that the drawing app received a
  visible stylus stroke. If pressure or barrel behavior is claimed, the visible
  result must exercise that claim.

If the device exposes a stylus input device but no real pen action is available,
commit or attach the script output as blocked evidence and keep the README
physical-stylus drawing-app gate open.

Do not use `adb shell cmd input stylus ...` or touchscreen `input tap/swipe` as
physical stylus acceptance. Those commands are useful for dispatcher plumbing
regressions only; they do not prove physical pen contact, barrel-button state,
eraser behavior, proximity, or pressure/tilt reaching the macOS drawing app. If
the device lease is held by another task, use `--write-blocked-on-lock` and
record the lock owner instead of clearing the lock or starting a competing
Host/client session.

## Permissions and lifecycle

- USB mode must work without Camera permission.
- For LAN QR pairing, exercise allow, first denial, permanent denial, the
  **Open Settings** recovery action, and a successful retry.
- Background the app while connected. New retry attempts and input must pause;
  keep-screen-on clears but screenshot protection remains. Return to the app
  and confirm the live session requests a keyframe or a disconnected session
  resumes bounded retry.
- Record Host PID, disconnect/admission epochs, first output frame, and elapsed
  recovery time. A build or lifecycle callback log alone is not a reconnect
  pass.

## Actionable failure checks

The cross-surface owner matrix for these checks lives in
docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json.
Keep that matrix and make actionable-error-states-gate current whenever Android
session failure kinds, Host permission/startup/capture states, or user-visible
recovery actions change. If the previous step changed into baseline/AndroidClient,
return to the repository root before invoking the gate:

```bash
cd /path/to/vibe-screen
make actionable-error-states-gate
```

For README-facing real-device ownership, also run the current-base gate against
the retained manifest from the evidence directory:

```bash
make actionable-error-current-base-gate EVIDENCE_DIR=<evidence-dir>
```

This second gate is still read-only, but it checks retained artifacts and exact
device identity. It exits non-zero for `blocked` or `insufficient` reports. To
refresh a blocked current-base owner record without treating it as acceptance,
run `make actionable-error-current-base-owner-record EVIDENCE_DIR=<evidence-dir>`
instead. Only `verdict=pass` with
`can_close_readme_phase1_actionable_errors_gate=true` can close the README
actionable-errors item.

Exercise a missing Mac app, missing ADB reverse, unreachable route, timeout,
camera denial, incompatible message/display configuration, outbound
backpressure, and decoder failure. Each state must identify the failed layer
and tell the user what to do next. Retryable transport failures use bounded
automatic recovery; non-retryable protocol/input failures must stop the loop
and show a concrete recovery action.

For trusted-LAN device evidence, classify Wi-Fi disconnected, wlan0 with no
IPv4 address, no route to the Mac LAN address, missing LAN Host listener, Host
stable-signing failure, and Host TCC failure as pre-session blockers. A
pre-session connection retry or TRANSPORT_CLOSED log is not reconnect evidence:
reconnect acceptance starts only after a real encrypted LAN stream has produced
decoder output and then recovers with the same Host PID. Run the shared Host
readiness snapshot and read-only trusted-LAN preflight first, and retain both
JSON files when either reports blocked. `host-readiness.json` must show
`can_start_trusted_lan_gate=true` before a LAN runtime attempt begins:

```sh
make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>
make evidence-trusted-lan-preflight EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=<evidence-dir>
```

Collect the private log with:

```bash
adb -s DEVICE_SERIAL exec-out run-as dev.telemachus.display sh -c \
  'cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null'
```

Never include pairing tokens, personal screen content, Wi-Fi credentials, or
public addresses in committed evidence.
