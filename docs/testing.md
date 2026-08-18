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

## Pass criteria

- APK installs and cold-starts without fatal exception.
- A real stream reaches a hardware decoder and produces output frames.
- Touch on two distinct device locations moves the Mac pointer accordingly.
- Protocol v1 native pointer claims require a physical mouse or equivalent HID
  pointer attached to the Android device. Record hover/move, primary click,
  release, and scroll through the negotiated pointer channel, plus the visible
  Mac pointer/button result. Synthetic ADB pointer or touchscreen events may
  support mapper coverage only.
- Controller claims first require Android production forwarding for
  gamepad/joystick events. After that wiring exists, acceptance also requires a
  physical controller attached to the Android device, accepted Protocol v1
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
