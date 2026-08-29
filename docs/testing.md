# Testing and real-device acceptance

Compilation is necessary but does not satisfy device acceptance.

## Automated checks

```bash
make protocol
make baseline-macos-build
make baseline-macos-xctest-preflight
make baseline-macos-test
make baseline-macos-self-test

cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug
```

`baseline-macos-xctest-preflight` records the selected Apple developer
directory, Swift toolchain, and `xcodebuild` availability under
`.build/dev-macos-host/xctest-toolchain.txt`. If it reports Command Line Tools
instead of full Xcode, keep MacHost XCTest-dependent evidence blocked until the
machine is switched with:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -version
```

The default macOS readiness and test paths do not inspect Login Items with
`sfltool`. Login-item state remains fail-closed as unverified unless an operator
explicitly runs the manual diagnostic path with `scripts/macos_dev_host.py
readiness --probe-login-item`.

## macOS Host signing preflight

Before any Host-backed Android device gate, install and verify the current-source
Host with a stable signing identity:

```bash
make baseline-macos-dev-install
make baseline-macos-host-preflight
```

If the configured identity is missing, the preflight blocks with
`codesign identity 'Vibe Screen Dev' not found in the keychain`. Create a
self-signed Code Signing certificate named `Vibe Screen Dev` in Keychain Access,
or set `VIBE_SCREEN_SIGN_IDENTITY` to an existing stable codesigning identity,
then reinstall, grant Screen Recording and Accessibility, and rerun the
preflight. Do not use ad-hoc signing for current-source device evidence because
macOS TCC grants are bound to the signing identity.

`make baseline-macos-host-readiness` keeps login-item state fail-closed by
default and does not invoke the macOS login-item diagnostic. For an attended
manual investigation only, run `python3 scripts/macos_dev_host.py readiness
	--include-login-item-diagnostic ...` to include the real login-item probe. Do
not enable that flag in default tests or CI.

## Real-device evidence

For every device run, record:

- ADB endpoint, hardware serial, manufacturer, model, Android version, SDK,
  build fingerprint, display size/density, battery, and boot state;
- Mac Host model identifier, CPU architecture (`apple_silicon` or `intel`),
  CPU/chip name, macOS product version and build, Xcode/Swift versions, Host
  app commit/binary SHA/signing identity, Screen Recording and Accessibility
  state, capture backend, VideoToolbox codec path, display topology, and display
  UUID/logical/physical dimensions;
- For Host-backed LAN, reconnect, Host RSS, native-pointer, stylus, physical
  keyboard, controller, login/headless, and compatibility runs, retain the
  shared source-bound Host readiness artifacts from
  `make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>`:
  `host-readiness.json` and `host-signing-and-permissions.txt`. A blocked
  readiness snapshot is prerequisite evidence only and cannot close the runtime
  gate by itself. The default readiness target must not probe Launch at Login
  because `/usr/bin/sfltool dumpbtm` can trigger macOS administrator
  authorization; use `--include-login-item-diagnostic` or
  `--inspect-login-items` only for a human opt-in diagnostic run;
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
  display identities for 90/180/270 host rotations, original and rotated macOS
  display rotation, client rotation mode, screenshots, structured inverse touch
  matrix for the four corners plus center, and proof that the original macOS
  rotation was restored;
- Host PID and a complete post-disconnect connection sequence;
- per-minute Host/Android memory, temperature, and frame samples during soak.

For the Phase 1 reconnect-within-three-seconds gate, keep a dedicated
`reconnect-timing-observations.json` plus `reconnect-timing-summary.json` beside
the raw Host log, Android logcat, private Android diag log, ADB reverse state,
and device/build metadata. The timing window starts at the recorded disruption
timestamp and ends at the Android decoder's first output frame after a fresh
Protocol v1 recovery. A Host accept line, Android retry loop, Activity
lifecycle callback, or first received encoded frame alone is not sufficient.
The full gate requires all three disruption scenarios: client kill,
ADB reverse removal/restoration, and trusted-LAN network interruption. Evaluate
the record with:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing \
  "$EVIDENCE_DIR/reconnect-timing-observations.json" \
  --output "$EVIDENCE_DIR/reconnect-timing-summary.json"
```

Use `--require-disruption client-kill` or another single scenario only for an
incremental partial run; that cannot close the full README timing gate. If Host
signing, TCC, port `54321`, ADB, or LAN conditions block the run, write a
blocked summary with `--blocked` or `make evidence-reconnect-timing-blocked`
instead of upgrading an older reconnect smoke to a timing pass.
Only a summary with `verdict=pass` and `can_close_timing_gate=true` can close
the README gate. An incremental run may return `verdict=pass` for the requested
scenario and `can_close_requested_scope=true`, but it must still keep
`can_close_timing_gate=false` until all three disruption scenarios pass.

For the Protocol v1 Android audio playback gate, keep a dedicated
`android-audio-playback-observations.json` beside the raw Host log, Android
logcat, private Android diag log, device/build metadata, ADB reverse state, and
Host listener/signing/TCC evidence. Re-check the record with:

```bash
make android-audio-playback-gate \
  EVIDENCE_DIR=docs/changes/<change>/evidence/<run>
```

A pass requires a real USB or trusted-LAN session on a named Android device, a
stable signed macOS Host with Microphone permission, Host listener evidence,
production Protocol v1 negotiation of `CAPABILITY_AUDIO`, accepted PCM S16LE
`AudioConfig`, Host channel `3` packet flow, Android production `AudioTrack`
start and write evidence, audible or instrumentation-backed playback
confirmation, and cleanup on disconnect or reconfiguration. The checker also
requires structured device identity plus non-empty retained artifacts under the
evidence directory for device identity, Host audio, Android audio, and playback
confirmation. Loopback harnesses, synthetic Protocol v1 peers, Android-only
logs, app private diagnostics without current-process playback writes, and old
plaintext fallback sessions cannot close the gate. If signing, Microphone/TCC,
Host listener, Wi-Fi/route, or audio output confirmation is missing, keep the
generated summary as `blocked` or `insufficient` instead of treating offline
tests as a playback pass. Evidence from the local Nubia phone must use
`adb -s <device-serial>` and remain labeled
`nubia P0110 / pacific / Android 16 / SDK 36`.

For performance-gate runs, keep latency evidence in the same evidence directory
as the device identity and soak artifacts:

- USB and LAN glass-to-glass latency require raw high-frame-rate camera footage,
  the sampled `latency_ms` or `start_frame,end_frame,camera_fps` CSV/JSON, the
  `vibescreen_evidence.latency` summary, device info, a profile-specific
  transport artifact, and an evidence manifest. USB packages must retain
  ADB reverse/USB connection and active stream proof; LAN packages must retain
  the trusted-network preflight and active LAN stream proof.
- Input latency requires either the same external-camera single timebase or a
  documented synchronized-clock setup with an error budget small enough for the
  sub-50 ms P95 gate. The formal provenance checker validates both
  external-camera and synchronized-clock input packages; a synchronized-clock
  claim must carry its own synchronization proof (clock sources, sync
  procedure, before/after skew, drift, and a total error budget below 5 ms) in
  the manifest's `synchronization` section. Unsynchronized host/device
  timestamps are diagnostic only. Input packages must also retain a physical
  input actuation record that ties each sample to a real Android input event
  and visible Mac-side result.
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

The equivalent Make target writes the standard report location and preserves the
checker exit code (`0` only for a formal `pass`):

```bash
make evidence-latency-gate \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  LATENCY_GATE_PROFILE="$GATE_PROFILE"
```

See [External-camera latency measurement](runbook/latency-measurement.md). For
external-camera packages, the checker requires the raw camera file, sample
annotations, device/build metadata, matching gate profile, and the matching
`gate_artifacts` entry before it can return `pass`. Synchronized-clock input
packages use direct-latency samples and manifest synchronization metadata
instead of `camera` and `recording` sections.

When the measurement setup is not ready, keep a fail-closed blocked preflight
instead of a partial latency claim:

```bash
make evidence-latency-preflight \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  LATENCY_DEVICE_INFO="$EVIDENCE_DIR/device-info.json" \
  LATENCY_PREFLIGHT_INPUT="$EVIDENCE_DIR/preflight-input.json" \
  LATENCY_REPOSITORY_REVISION="$(git rev-parse origin/main)"
```

That target exits `0` when every declared prerequisite is ready, `2` for
blocked readiness, and `1` for malformed input or evaluation failures. It
writes `latency-preflight.json` plus `latency-preflight-exit.txt`; it cannot
close a latency gate.

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

### USB smoke preflight

Before attempting a short USB end-to-end smoke, collect the fail-closed
readiness state for the exact target device:

```bash
make evidence-usb-smoke-preflight \
  EVIDENCE_SERIAL=<P0110_USB_SERIAL> \
  EVIDENCE_DIR=.build/evidence/usb-smoke-preflight \
  EVIDENCE_EXPECTED_MANUFACTURER=nubia \
  EVIDENCE_EXPECTED_MODEL=P0110 \
  EVIDENCE_EXPECTED_DEVICE=pacific \
  EVIDENCE_EXPECTED_ANDROID_RELEASE=16 \
  EVIDENCE_EXPECTED_SDK=36
```

The preflight exits `0` only when no shared Android device lock exists, the
explicit ADB target matches the expected identity, `adb reverse tcp:54321
tcp:54321` is already configured, the Android app is running in the foreground,
the Mac Host is listening on TCP `54321`, and the stable-signed Host/TCC
preflight passes. It exits `2` and writes `usb-smoke-preflight.json` when a
prerequisite is blocked. A blocked preflight is a readiness record only; it
does not prove USB streaming, reconnect, input, latency, soak, Host RSS, native
pointer, stylus, controller, or Xiaomi/fuxi behavior.

### Read-only USB live-stream smoke

When a Host and Android client are already streaming over USB, capture a
repeatable summary without changing the device or session:

```bash
test ! -e /tmp/vibe-screen-device-android.lock
test ! -e /tmp/vibe-screen-device-soak.lock
make evidence-usb-live-smoke \
  EVIDENCE_SERIAL=<device-serial> \
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

### File-transfer Android product E2E gate

The Protocol v1 Android/macOS single-file transfer gate is fail-closed. Collect
the current evidence bundle with:

```bash
make file-transfer-android-smoke \
  EVIDENCE_DIR=.build/evidence/file-transfer-android-smoke
```

The gate writes `file-transfer-android-smoke-gate.json` and exits `0` for a
machine-readable blocked readiness record unless
`FILE_TRANSFER_ANDROID_SMOKE_REQUIRE_PASS=1` is set. A passing record requires
all of the following from one current run: a stable-signed, TCC-ready Host
readiness pass; either USB or trusted-LAN real transport readiness; an Android
file-transfer instrumentation log with `OK`; and `file-transfer-product-e2e.json`
proving Android -> macOS and macOS -> Android product transfers with
file-offer/request/content packets, explicit sender action, receiver approval,
saved remote file, positive session epoch, final SHA-256 equality, and
cancel/cleanup evidence.

Offline protocol/JVM tests, Android control-bar instrumentation, synthetic JSON,
or a live stream without retained file-transfer product evidence cannot close
this gate. Nubia P0110 evidence may be used for general Android readiness only
when it stays labeled nubia P0110 / pacific / Android 16 / SDK 36 and is not
relabeled as Xiaomi 13/fuxi.

The current 2026-08-29 P0110 current-base readiness record is intentionally
blocked under
`docs/changes/2026-08-21-file-transfer-e2e/evidence/2026-08-29-nubia-p0110-file-transfer-current-base-readiness/`.

### macOS Host compatibility matrix gate

The macOS compatibility matrix is hardware-gated. A row can close only for the
exact Host architecture, Mac model identifier, macOS build, display topology,
transport, Android counterpart, source-bound Host build identity, and artifacts recorded in
that evidence bundle. CI `macos-15` build/test output, a local Apple silicon run,
or a successful row on another display setup cannot be extrapolated to Intel, to
the whole macOS 13+ range, or to a different built-in/external/multi-display,
dummy/headless, or Screen Sharing topology.

Before claiming a row, follow the
[macOS Host compatibility runbook](runbook/macos-host-compatibility.md), retain
the row artifacts, then run:

```bash
make macos-hardware-compatibility-gate EVIDENCE_DIR="$EVIDENCE_DIR"
```

The gate consumes `macos-hardware-compatibility.json` and writes
`macos-hardware-compatibility-gate.json`. A row is accepted only when the summary
contains `verdict=pass` and `can_close_macos_host_compatibility_row=true`.
The underlying Python CLI exits `0` for `pass`, `1` for `blocked` or
`insufficient`, and `2` for `failed` invalid extrapolation claims; Make reports
any non-pass result as a failed target while still writing the summary JSON.
`blocked`, `insufficient`, or `failed` summaries keep the README compatibility
matrix open for that row. The row must include the packaged Host bundle id,
stable non-ad-hoc signing identity, authorized Screen Recording and
Accessibility TCC state, installed Host source commit/tree provenance, Host
self-test commit, and current-base commit; missing or mismatched values are
blocked readiness evidence only. If the connected Android device is the local Nubia
phone, every ADB command must name `adb -s <device-serial>`, and the
counterpart must be recorded as
`nubia P0110 / pacific / Android 16 / SDK 36 / <device-serial>`.

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
make native-pointer-hid-acceptance \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  NATIVE_POINTER_HOST_LOG="$HOME/Library/Logs/Telemachus/telemachus.log" \
  NATIVE_POINTER_VISIBLE_RESULT_NOTE="Mac cursor moved and the primary click focused <target app>" \
  EVIDENCE_DIR=docs/changes/2026-08-05-phase-1-android-client/evidence/$(date -u +%F)-native-pointer-hid
```

While the script waits, move the physical mouse over the Android stream, then
left-click and release. A pass requires all three evidence layers from the same
observation window: Android `MA` logcat lines showing forwarded native pointer
`MOVE`, `BUTTON_PRESS`, and `BUTTON_RELEASE` from a mouse-like source; newly
appended Host log lines for native pointer `changed`, `began`, and `ended`
injection; and an operator-visible Mac result note. The Android forwarding lines
must include a positive `deviceId` for each required event, and those IDs must
match an external mouse-like device in the retained `dumpsys input` inventory.
Synthetic ADB pointer/touch events, including virtual-device events such as
`deviceId=-1`, are diagnostics only and cannot close the gate. If no external
Android input device with a mouse, relative mouse, touchpad, or trackball source
is present, the script exits with code `2` and writes a `blocked` evidence bundle
instead of fabricating a device result. Re-checking that bundle with the
`--require-pass` gate is expected to return non-zero; Make may surface that as
`Error 1`. Evidence from a Nubia P0110 must remain labeled P0110/pacific; it
must not be relabeled as Xiaomi 13/fuxi.

The collection step writes `native-pointer-hid-summary.json` by running the
independent `vibescreen_evidence.native_pointer_hid` gate. The README gate can
close only when that summary reports `verdict=pass` and
`can_close_native_pointer_hid_gate=true`. Re-check an existing evidence bundle
with:

```bash
make native-pointer-hid-gate \
  EVIDENCE_DIR=docs/changes/2026-08-05-phase-1-android-client/evidence/<run-dir>
```

### iOS hardware VideoToolbox gate

Phase 5 hardware VideoToolbox behavior is an iOS-device gate, not a Simulator or
archive gate. Use the fail-closed readiness summary before and after any future
physical run so missing prerequisites are machine-readable instead of implied:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m \
  vibescreen_evidence.ios_videotoolbox_readiness \
  "$EVIDENCE_DIR/ios-videotoolbox-observations.json" \
  --output "$EVIDENCE_DIR/ios-videotoolbox-readiness.json" \
  --evidence-dir "$EVIDENCE_DIR" \
  --require-pass
```

The observations file must set `runtime_class` to `simulator`,
`unsigned_archive`, `physical_iphone`, or `physical_ipad`. Simulator and unsigned
archive records always produce `verdict=blocked` and
`can_close_device_family_videotoolbox_gate=false`; they are useful for readiness
tracking only. The Makefile gate and `--require-pass` mode return nonzero unless
the family gate can close. A physical iPhone or iPad family pass requires a
signed installed app, matching real device identity, H.264 SPS/PPS, HEVC
VPS/SPS/PPS, VideoToolbox session creation for both codecs, output frames for
both codecs, hardware-path evidence, stream/config epoch telemetry,
thermal/power state, and existing non-empty retained iOS VideoToolbox artifacts
under the evidence directory.
retained artifacts. The summary keeps
`can_close_phase5_hardware_videotoolbox_gate=false` because README Phase 5 should
close only after both iPhone and iPad family records are reviewed with the wider
iOS device-acceptance evidence. Android MediaCodec evidence, synthetic media,
Simulator decode, or a decoded still image cannot close this gate.

## Pass criteria

- APK installs and cold-starts without fatal exception.
- A real stream reaches a hardware decoder and produces output frames.
- A Host start where `CGPreflightScreenCaptureAccess()` is granted but
  `SCShareableContent` reports zero displays is blocked until either the
  Current Main Display `CGDisplayStream` fallback starts and `54321` is actually
  listening with rising frames, or ScreenCaptureKit display enumeration recovers.
  Do not count the permission preflight alone as Host readiness.
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
- Generic peripheral-input framework claims are offline-only unless tied to a
  named physical peripheral and a concrete implementation. Treat
  [the peripheral-input framework runbook](runbook/peripheral-input-framework.md)
  as the normative checklist. Capability `peripheral-input-framework` /
  `CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK` only admits bounded `PeripheralEvent`
  messages; the current Host placeholder must fail closed with
  `unsupported_peripheral_kind` and cannot close any physical peripheral gate. A
  future gate needs the exact peripheral name, physical-device identity, Android
  input source, bounded-event evidence, negotiated capability, Host native
  handling logs, visible Mac result, and teardown or session-replacement
  neutralization evidence proving buttons, axes, pointers, and contacts return
  to neutral for that hardware path.
- Client/process or ADB TCP interruption produces a fresh connected session
  while the Host PID survives.
- macOS Host compatibility claims require a passing
  `macos-hardware-compatibility-gate` summary for the exact Host row. A source
  build, XCTest/self-test pass, or CI runner result can support the row but does
  not prove hardware compatibility by itself.
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
controller or entitled Host runtime observations as `blocked`, not `pass`; its
CLI exits `0` only for `pass`, `2` for `blocked`, and `1` for `insufficient`
or malformed evidence.

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

For the Phase 2 hardware-keyboard workflow, use the corresponding readiness
collector before attempting physical key presses:

```bash
make hardware-keyboard-readiness \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/$(date -u +%F)-p0110-hardware-keyboard-readiness
```

The command records P0110/pacific identity, Android input devices, package
metadata, Host listener state, and stable signed/TCC Host preflight. It exits
nonzero for blocked or insufficient readiness; a pass still requires physical
keyboard input through the production Protocol v1 path, Host `Key injected:`
logs, modifier cleanup evidence, and a visible Mac-side result.

For HarmonyOS HAP lifecycle readiness, collect the environment and device
pre-state before claiming build/sign/install progress. Missing DevEco, HDC,
signing material, HAP output, or lifecycle observations intentionally returns a
blocked or insufficient result and writes evidence instead of passing:

```bash
make harmony-hap-readiness \
  HARMONY_HAP_READINESS_DIR=docs/changes/2026-08-04-phase-4-harmony/evidence/$(date -u +%F)-hap-readiness \
  HARMONY_HDC_TARGET="$HDC_TARGET"
python3 scripts/harmony_device_gate.py --allow-blocked \
  docs/changes/2026-08-04-phase-4-harmony/evidence/$(date -u +%F)-hap-readiness/harmony-device-gates.json
```

Android acceptance devices still use explicit ADB serials, for example
`adb -s <device-serial> ...` for the Nubia P0110 / pacific / Android 16 /
SDK 36 device. That Android evidence must not be used as HarmonyOS or MatePad
Mini evidence.
