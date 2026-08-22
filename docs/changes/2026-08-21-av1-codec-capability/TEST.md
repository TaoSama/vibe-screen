# AV1 codec capability gate

Date: 2026-08-21
Status: offline contract added; real AV1 stream blocked

## Scope

This change covers the engineering contract for the planned AV1 codec path
without claiming current Host or device stream support. Protocol v1 already
contains CODEC_AV1; this slice makes AV1 admission explicit across Host,
Android, and iOS policy surfaces.

## Offline coverage

Expected checks for this slice:

```text
cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests
cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest
cd apps/ios && swift run vibescreen-ios-selftest
```

The covered contract is:

- Host VideoToolbox capability probing distinguishes H.264, HEVC, and AV1
  hardware encoder availability, but Protocol v1 Host advertisement still
  filters out AV1 until a real AV1 encoder and frame packaging implementation
  exists.
- Protocol v1 Host session selection ignores AV1 when the local Host has no
  stream encoder mapping and falls back to HEVC/H.264 when the client also
  supports them.
- Protocol v1 Host session fails closed with an actionable unsupported-capability
  error when the only mutually offered client codec is AV1.
- Android MediaCodec capability probing can observe AV1 decoder availability as
  diagnostic state, but default USB/LAN/Internet offers remain HEVC/H.264 only;
  a received AV1 Internet VideoConfig is rejected as av1_decoder_unavailable.
- iOS validates CODEC_AV1 as a known protocol enum but rejects AV1 unless an
  explicit local decode capability is present, and the current VideoToolbox
  decoder implementation still throws unsupportedCodec(.av1).

## Real-device status

No AV1-capable macOS Host stream, Android MediaCodec stream, or iOS
VideoToolbox stream was run. The README AV1 gate remains open.

The retained blocked evidence record is
[`evidence/2026-08-21-av1-offline-blocked/README.md`](evidence/2026-08-21-av1-offline-blocked/README.md).

## 2026-08-21 verification

- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest`
  - Result: passed.
- `cd baseline/MacHost && swift build`
  - Result: passed.
- `cd apps/ios && swift run vibescreen-ios-selftest`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests`
  - Result: blocked in this local Command Line Tools environment before test
    execution with `no such module 'XCTest'`; the MacHost product target
    compiled successfully with `swift build`.
