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
`docs/changes/2026-08-04-phase-0-baseline/TEST.md`. The designated endpoint
is redacted as `$ADB_ENDPOINT` and identified itself as Nubia P0110, not Xiaomi 12; results
must retain that distinction.

## Pass criteria

- APK installs and cold-starts without fatal exception.
- A real stream reaches a hardware decoder and produces output frames.
- Touch on two distinct device locations moves the Mac pointer accordingly.
- Client/process or ADB TCP interruption produces a fresh connected session
  while the Host PID survives.
- A 30-minute stream has live PIDs and rising frames throughout, no fatal codec
  error, no unbounded memory/latency growth, and controlled thermal behavior.

Internal timestamps may measure encoder, decoder, queue, and reconnect
durations only within their own clock domain. Glass-to-glass latency requires
an external high-frame-rate camera or optical measurement; RTT and decoder
latency are not substitutes.
