# AV1 codec capability gate

Date: 2026-08-21
Status: current-base closure owner added; real AV1 stream blocked

## Scope

This change covers the engineering contract for the planned AV1 codec path
without claiming current Host or device stream support. Protocol v1 already
contains CODEC_AV1; this slice makes AV1 admission explicit across Host,
Android, and iOS policy surfaces.

`tools/tests/test_av1_current_base_gate.py` is the current-base closure owner.
It must stay green until AV1 is intentionally promoted from later-phase/backlog
work into a real Host/device stream codec. The gate checks both product wording
and source admission points so a future change cannot accidentally claim AV1 as
shipped, advertise AV1 from the Host, map AV1 into Android product offers, or
remove the blocked-evidence record without updating the implementation and
evidence contract together.

## Offline coverage

Expected checks for this slice:

```text
cd baseline/MacHost && swift test --filter CodecLimitsTests --filter ProtocolV1SessionTests --filter InternetProductProtocolCodecTests
cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DecoderSelectionTest --tests dev.telemachus.display.ReliabilityPrimitivesTest --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest --tests dev.telemachus.display.internet.InternetProductSessionTest
cd apps/ios && swift run vibescreen-ios-selftest
PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v
```

The covered contract is:

- Host VideoToolbox capability probing distinguishes H.264, HEVC, and AV1
  hardware encoder availability, but Protocol v1 Host advertisement still
  filters out AV1 until a real AV1 encoder and frame packaging implementation
  exists; the current Host does not advertise AV1.
- Protocol v1 Host session selection ignores AV1 when the local Host has no
  stream encoder mapping and falls back to HEVC/H.264 when the client also
  supports them.
- Protocol v1 Host session fails closed with an actionable unsupported-capability
  error when the only mutually offered client codec is AV1.
- Android MediaCodec capability probing can observe AV1 decoder availability as
  diagnostic state, but Android does not offer AV1 in product sessions and
  default USB/LAN/Internet offers remain HEVC/H.264 only; a received AV1
  Internet VideoConfig is rejected as av1_decoder_unavailable.
- iOS validates CODEC_AV1 as a known protocol enum but rejects AV1 unless an
  explicit local decode capability is present, and the current VideoToolbox
  decoder implementation still throws unsupportedCodec(.av1).
- The current-base closure owner also checks that iOS recognizes CODEC_AV1 but
  rejects it without local decoder support, so all three product surfaces stay
  aligned until a real AV1 implementation and evidence gate are added.

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

## 2026-08-23 current-base refresh

The current-base closure owner was replayed on `origin/main`
`3d23de133adc4414b4c70430c619fadbe7d90207`. This refresh only keeps the AV1
gate fail-closed and reviewable; it does not add Host/device AV1 streaming
evidence.

- `make protocol`
  - Result: passed.
- `PYTHONPATH=tools python3 -m unittest tools.tests.test_av1_current_base_gate -v`
  - Result: passed, 5 tests.
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
