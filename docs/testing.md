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
- Host PID and a complete post-disconnect connection sequence;
- per-minute Host/Android memory, temperature, and frame samples during soak.

For performance-gate runs, keep latency evidence in the same evidence directory
as the device identity and soak artifacts:

- USB and LAN glass-to-glass latency require raw high-frame-rate camera footage,
  the sampled `latency_ms` or `start_frame,end_frame,camera_fps` CSV/JSON, the
  `vibescreen_evidence.latency` summary, device info, and an evidence manifest.
- Input latency requires either the same external-camera single timebase or a
  documented synchronized-clock setup with an error budget small enough for the
  sub-50 ms P95 gate. Unsynchronized host/device timestamps are diagnostic only.
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

### Native pointer HID mouse gate

Native pointer move/click is a hardware-gated acceptance item. Use a real USB or
Bluetooth mouse attached to the Android device under test; `adb shell input
mouse ...` can exercise scroll, but it does not reliably deliver hover/move to
the focused Android view and cannot close the native-pointer gate.

Before running the gate, start the matching macOS Host, grant Accessibility,
establish a Protocol v1 USB or trusted-LAN session, and keep the Android client
foregrounded on the streaming view. Then run:

```bash
python3 scripts/native_pointer_hid_acceptance.py \
  --serial EP0110PZ0B9110300B \
  --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
  --evidence-dir docs/changes/2026-08-05-phase-1-android-client/evidence/$(date +%F)-p0110-native-pointer-hid
```

While the script waits, move the physical mouse over the Android stream, then
left-click and release. A pass requires newly appended Host log lines for native
pointer `changed`, `began`, and `ended` injection. If no external Android input
device with a mouse, touchpad, or trackball source is present, the script exits
with code `2` and writes a `blocked` evidence bundle instead of fabricating a
device result. Evidence from a Nubia P0110 must remain labeled P0110/pacific;
it must not be relabeled as Xiaomi 13/fuxi.

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
  Android device, accepted Protocol v1
  `controller` capability, host virtual-gamepad availability, visible
  controller input in a Mac-side test target, and neutral release on
  disconnect. Offline HID report and mapper tests do not prove the OS accepted
  a virtual gamepad.
- Client/process or ADB TCP interruption produces a fresh connected session
  while the Host PID survives.
- A sustained stream keeps live PIDs and rising frames throughout, with no fatal
  codec error and controlled thermal behavior. A two-hour soak has run on the
  Xiaomi 13 with a stable stream and stable client memory; the host
  resident-memory no-growth gate is still open (host RSS grew about 18.3 MB), so
  a host-RSS-stable two-hour run remains required before claiming no-growth.

Internal timestamps may measure encoder, decoder, queue, and reconnect
durations only within their own clock domain. Glass-to-glass latency requires
an external high-frame-rate camera or optical measurement; RTT and decoder
latency are not substitutes.

Use `PYTHONPATH=tools python3 -m vibescreen_evidence.latency --help` for the
supported latency evidence formats and gate semantics.
