# Testing and real-device acceptance

Compilation is necessary but does not satisfy device acceptance.

## Automated checks

```bash
make protocol
make baseline-macos-build
make baseline-macos-test
make baseline-macos-self-test

cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug
```

## Real-device evidence

For every device run, record:

- ADB endpoint, hardware serial, manufacturer, model, Android version, SDK,
  build fingerprint, display size/density, battery, and boot state;
- APK version/signing identity and install timestamp;
- ADB reverse mapping and host listener;
- decoder name, first output frame, continuing frame counters, and drops;
- Mac pointer positions before/after Android touches;
- For native pointer, HID mouse/controller, stylus, and physical keyboard runs,
  the exact attached peripheral name, Android input source observed in logs, the
  Protocol v1 negotiated capabilities, host-side injection logs, and visible Mac
  result. ADB `input` commands may exercise Android dispatch but do not prove a
  physical HID peripheral;
- when closing rotated host-display acceptance, the physical and virtual
  display identities, original and rotated macOS display rotation, client
  rotation mode, screenshots, touch matrix, and proof that the original macOS
  rotation was restored;
- Host PID and a complete post-disconnect connection sequence;
- per-minute Host/Android memory, temperature, and frame samples during soak.

For performance-gate runs, keep latency evidence in the same evidence directory
as the device identity and soak artifacts:

- USB and LAN glass-to-glass latency require raw high-frame-rate camera footage,
  the sampled `latency_ms` or `start_frame,end_frame,camera_fps` CSV/JSON, the
  `vibescreen_evidence.latency` summary, device info, and an evidence manifest.
- Input latency requires either the same external-camera single timebase or a
  documented synchronized-clock setup with an error budget small enough for the
  sub-50 ms P95 gate. The formal provenance checker validates both
  external-camera and synchronized-clock input packages; a synchronized-clock
  claim must carry its own synchronization proof (clock sources, sync
  procedure, before/after skew, drift, and a total error budget below 5 ms) in
  the manifest's `synchronization` section. Unsynchronized host/device
  timestamps are diagnostic only.
- Host/client telemetry-stage summaries may be recorded from pipeline, decoder,
  queue, or RTT logs with `--kind telemetry-stage`. They explain where latency
  is spent, but their summary must retain
  `gate.can_close_performance_gate=false` and cannot replace the camera/input
  evidence above.

The formal latency summaries should use the matching gate profile:
`usb-glass-to-glass-sub50`, `lan-glass-to-glass-sub80`, or `input-p95-sub50`.
A `pass` verdict closes only that specific profile for the recorded device,
transport, build, and measurement setup; `fail` and `insufficient` keep the
gate open. The CLI exits `0` only for a profile `pass` and exits nonzero for
`fail` or `insufficient`. The synthetic examples under
`tools/fixtures/latency/` are only CLI fixtures for exercising these verdicts;
they are not real-device evidence.
For formal external-camera or synchronized-clock input runs, validate the full
evidence directory with the stricter provenance checker:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile "$GATE_PROFILE"
```

See [External-camera latency measurement](runbook/latency-measurement.md). For
external-camera packages, the checker requires the raw camera file, sample
annotations, device/build metadata, and matching gate profile before it can
return `pass`. Synchronized-clock input packages use direct-latency samples and
manifest synchronization metadata instead of `camera` and `recording` sections.

The current Phase 0 evidence is recorded in
`docs/changes/2026-08-04-phase-0-baseline/TEST.md`. Any connected Android
device that meets the runtime requirements may be used for general Android
acceptance work, including Nubia P0110 as a substitute for Xiaomi 13/fuxi. Each
run must still retain the real device identity in its evidence: a P0110 result
must be labeled P0110/pacific, and a Xiaomi 13 result must be labeled
2211133C/fuxi. Hardware-specific claims remain scoped to the exact device that
produced them. Later Xiaomi 13 streaming, display-switch, input, and
two-hour-soak evidence is recorded separately under
`docs/changes/2026-08-04-phase-0-baseline/evidence/`.

### Read-only USB live-stream smoke

When a Host and Android client are already streaming over USB, capture a
repeatable summary without changing the device or session:

```bash
test ! -e /tmp/vibe-screen-device-android.lock
test ! -e /tmp/vibe-screen-device-soak.lock
make evidence-usb-live-smoke \
  EVIDENCE_SERIAL=EP0110PZ0B9110300B \
  EVIDENCE_DIR=.build/evidence/usb-live-smoke
```

The helper uses only explicit `adb -s <serial>` read commands. It reads the
device identity, `adb reverse --list`, package metadata, foreground Activity,
PID, focused `logcat` lines, and the app private diagnostic log. It does not
install or start the app, clear logcat, create or remove reverse mappings,
probe the Host socket, or inject input. If another run owns the Android device
lock, rerun the module with `--write-blocked-on-lock` to write a structured
`blocked` summary and exit non-zero without touching ADB.

The JSON result can be used to show that an already-running USB stream exposed
current-process positive `stream_stats` and active MediaCodec decoder output. A
fresh session may include decoder setup and first-output lines; a long-running
session may instead prove decoder activity from current-process retained frame
counters. The private diagnostic log is context only and cannot independently
support a `pass`. The summary cannot close soak, Host RSS, latency,
native-pointer, stylus, or controller gates. Nubia P0110/pacific output includes
a label guard that keeps `recorded_as_fuxi=false` and scopes the result to a
general Android substitute.

### Native pointer HID mouse gate

Native pointer move/click is a hardware-gated acceptance item. Use a real USB or
Bluetooth mouse attached to the Android device under test; `adb shell input
mouse ...` can exercise scroll, but it does not reliably deliver hover/move to
the focused Android view and cannot close the native-pointer gate.

Before running the gate, start the matching macOS Host, grant Accessibility,
establish a Protocol v1 USB or trusted-LAN session, and keep the Android client
foregrounded on the streaming view. Replace `<target app>` with the observed
Mac application name before running the command:

```bash
python3 scripts/native_pointer_hid_acceptance.py \
  --serial "$ADB_SERIAL" \
  --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
  --visible-result-note "Mac cursor moved and the primary click focused <target app>" \
  --evidence-dir docs/changes/2026-08-05-phase-1-android-client/evidence/$(date -u +%F)-p0110-native-pointer-hid
```

While the script waits, move the physical mouse over the Android stream, then
left-click and release. A pass requires all three evidence layers from the same
observation window: Android `MA` logcat lines showing forwarded native pointer
`MOVE`, `BUTTON_PRESS`, and `BUTTON_RELEASE` from a mouse-like source; newly
appended Host log lines for native pointer `changed`, `began`, and `ended`
injection; and an operator-visible Mac result note. If no external Android input
device with a mouse, relative mouse, touchpad, or trackball source is present,
the script exits with code `2` and writes a `blocked` evidence bundle instead of
fabricating a device result. Evidence from a Nubia P0110 must remain labeled
P0110/pacific; it must not be relabeled as Xiaomi 13/fuxi.

## Pass criteria

- APK installs and cold-starts without fatal exception.
- A real stream reaches a hardware decoder and produces output frames.
- Touch on two distinct device locations moves the Mac pointer accordingly.
- Protocol v1 native pointer claims require a physical mouse or equivalent HID
  pointer attached to the Android device. Record hover/move, primary click,
  release, and scroll through the negotiated pointer channel, plus the visible
  Mac pointer/button result. Synthetic ADB pointer or touchscreen events may
  support mapper coverage only.
- Controller runtime claims require a physical controller attached to the
  Android device, Android `SOURCE_GAMEPAD` or `SOURCE_JOYSTICK` production
  forwarding through the active Protocol v1 session, accepted Protocol v1
  `controller` capability, host virtual-gamepad availability from an
  identity-signed build with the approved virtual HID entitlement, visible
  controller input in a Mac-side test target, and neutral release on
  disconnect. Offline HID report, Android mapper, session, and protocol tests
  do not prove the OS accepted a virtual gamepad.
- Client/process or ADB TCP interruption produces a fresh connected session
  while the Host PID survives.
- A sustained stream keeps live PIDs and rising frames throughout, with no fatal
  codec error and controlled thermal behavior. A two-hour soak has run on the
  Xiaomi 13 with a stable stream and stable client memory; the host
  resident-memory no-growth gate is still open (host RSS grew about 18.3 MB), so
  a host-RSS-stable two-hour run remains required before claiming no-growth.
- Physical stylus drawing-app confirmation requires a Protocol v1 session, a
  real stylus contacting the named Android device, host-side stylus injection
  logs preserving pressure/tilt/barrel/proximity fields as applicable, and a
  visible macOS drawing-app result. ADB-only input-device snapshots, synthetic
  MotionEvents, or offline protocol tests may support the investigation but do
  not close the README stylus gate.

Internal timestamps may measure encoder, decoder, queue, and reconnect
durations only within their own clock domain. Glass-to-glass latency requires
an external high-frame-rate camera or optical measurement; RTT and decoder
latency are not substitutes.

Use `PYTHONPATH=tools python3 -m vibescreen_evidence.latency --help` for the
supported latency evidence formats and gate semantics.

Use `PYTHONPATH=tools python3 -m vibescreen_evidence.controller_runtime --help`
for the controller runtime gate summary. The tool treats missing physical
controller or entitled Host runtime observations as `blocked`, not `pass`.

Use the read-only readiness collector before attempting the interactive gate so
missing hardware, APK identity, Host signing, entitlement, or Host availability
is recorded as structured evidence instead of a handwritten note:

```bash
python3 scripts/controller_runtime_readiness.py \
  --serial "$ADB_SERIAL" \
  --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
  --host-app "/path/to/Vibe Screen.app" \
  --write-blocked-on-lock \
  --evidence-dir docs/changes/2026-08-19-controller-runtime-acceptance/evidence/$(date -u +%F)-controller-runtime-readiness
```

Without `--allow-existing-device-lock`, the collector refuses to run ADB when a
shared Android device lock is present. With `--write-blocked-on-lock`, that
preflight writes a blocked bundle that records the lock state instead of using
the device.
