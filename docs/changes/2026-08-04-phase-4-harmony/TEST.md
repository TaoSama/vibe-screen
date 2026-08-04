# Phase 4 verification record

Date: 2026-08-04

## Passed locally

```text
cd apps/harmony && pnpm run verify
8 tests, 0 failures
```

Covered behavior: exact shared Protocol v1 ClientHello bytes,
SessionAccepted/unknown-field
decoding, distinct touch/pointer/scroll/key envelopes, split/coalesced control
framing, strict session epochs, capacity-one frame queue, rotated coordinate
mapping, and capped deterministic reconnect backoff.

The hosted `HarmonyOS portable checks` workflow runs the same frozen install,
type-check, and test commands. Its job name explicitly states that it supplies
no DevEco or HAP evidence.

## Environment evidence

```text
node v26.5.0
pnpm 11.15.1
TypeScript 5.9.3
hvigorw: not installed
ohpm: not installed
hdc: not installed
DevEco Studio: not installed
```

The requested ADB endpoint connected successfully but identifies as:

```text
[controlled endpoint, redacted] device product:pacific model:P0110
manufacturer=nubia, model=P0110, Android=16, API=36
```

It is neither Xiaomi 12 nor HarmonyOS and therefore supplies no Phase 4 device
evidence. The imported macOS host implements Telemachus's legacy message types,
not Protocol v1, so Android cannot currently validate v1 server compatibility.

## Required before Phase 4 completion

- DevEco sync and debug/release HAP build from a clean checkout;
- static ArkTS/API checker and signing verification;
- MatePad Mini install, pairing, H.264/HEVC render, touch, keyboard, mouse,
  stylus pressure, foreground/background, network loss, reconnect, and revoke;
- rotation/safe-area checks in portrait and landscape;
- 8-hour thermal/power/RSS/frame-drop soak and external-camera latency samples;
- host Protocol v1 integration and golden byte parity with generated bindings.
