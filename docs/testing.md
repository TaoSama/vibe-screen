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
- Host PID and a complete post-disconnect connection sequence;
- per-minute Host/Android memory, temperature, and frame samples during soak.

The current Phase 0 evidence is recorded in
`docs/changes/2026-08-04-phase-0-baseline/TEST.md`. The final coordinated
acceptance endpoint is redacted as `$ADB_ENDPOINT` and identified itself as
Nubia P0110, not the Xiaomi 13 (model 2211133C, codename fuxi) primary target;
results must retain that distinction. Later Xiaomi 13 streaming, display-switch,
input, and two-hour-soak evidence is recorded separately under
`docs/changes/2026-08-04-phase-0-baseline/evidence/`.

## Pass criteria

- APK installs and cold-starts without fatal exception.
- A real stream reaches a hardware decoder and produces output frames.
- Touch on two distinct device locations moves the Mac pointer accordingly.
- Client/process or ADB TCP interruption produces a fresh connected session
  while the Host PID survives.
- A sustained stream keeps live PIDs and rising frames throughout, with no fatal
  codec error and controlled thermal behavior. A two-hour soak has run on the
  Xiaomi 13 with a stable stream and stable client memory; the host
  resident-memory no-growth gate is still open (host RSS grew about 18.3 MB), so
  a memory-stable two-hour run remains required before claiming no-growth.

Internal timestamps may measure encoder, decoder, queue, and reconnect
durations only within their own clock domain. Glass-to-glass latency requires
an external high-frame-rate camera or optical measurement; RTT and decoder
latency are not substitutes.
