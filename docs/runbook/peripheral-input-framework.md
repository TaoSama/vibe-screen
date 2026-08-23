# Peripheral Input Framework Readiness

This runbook verifies the generic Protocol v1 peripheral-input admission
framework. It is an offline/readiness gate only. Passing it does not prove any
specific Android peripheral, macOS native injection path, HID device, stylus,
controller, or drawing application behavior.

## What This Gate Covers

- `CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK` is allocated at capability value `30`.
- `PeripheralEvent` is an additive input payload at envelope field `67`.
- Android can construct a bounded `PeripheralEvent` only after the capability is
  explicitly advertised and negotiated.
- macOS Host only advertises the framework when explicitly configured, validates
  the input id, kind length, payload size, and active target, then fails closed
  with `InputAck(accepted=false, rejection_reason="unsupported_peripheral_kind")`.

## Offline Readiness

Run the focused offline checks from the repository root:

```bash
make protocol
(cd baseline/AndroidClient && ./gradlew testDebugUnitTest \
  --tests dev.telemachus.display.ClientInputDispatchTest \
  --tests dev.telemachus.display.StreamInputDispatcherTest \
  --tests dev.telemachus.display.SessionStateTest \
  --tests dev.telemachus.display.StreamInputBoundaryContractTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest)
(cd baseline/MacHost && swift test --filter ProtocolV1SessionTests)
(cd apps/harmony && pnpm test)
```

The readiness result is `pass` only when the checks prove bounded encoding,
negotiated gating, and fail-closed Host acknowledgement. Record any skipped
command with the missing local prerequisite.

## Concrete Peripheral Acceptance

A future concrete peripheral gate requires separate evidence for each named
peripheral kind:

- physical device identity and Android input source, including manufacturer,
  model, codename, Android version, SDK level, and input-device descriptor;
- explicit capability negotiation that includes the generic framework plus the
  concrete product-level implementation gate for that peripheral kind;
- Android logs showing the input source entered the intended mapper and emitted
  bounded protocol events;
- Host logs showing the concrete native handler accepted the event instead of
  returning `unsupported_peripheral_kind`;
- visible macOS output or app-side evidence proving the intended action occurred;
- teardown evidence showing pressed buttons, axes, pointers, or active contacts
  return to neutral on disconnect or session replacement.

Until those artifacts exist, keep native HID mouse move/click, physical stylus
drawing, controller runtime acceptance, and other peripheral claims open.
