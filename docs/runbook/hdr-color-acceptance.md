# HDR/color acceptance

This runbook separates three different claims that are easy to conflate:

1. Color-description negotiation and fail-closed fallback.
2. SDR decode/display on existing clients.
3. True HDR/EDR capture, encode, decode, and visible output.

Only the first item can be closed by offline protocol and encoder tests. HDR
output remains open until retained hardware evidence proves the full path.

## Offline fallback gate

Run these from the repository root before reporting fallback readiness:

```bash
make protocol
swift build --package-path baseline/MacHost
baseline/MacHost/.build/debug/Vibe\ Screen --protocol-v1-self-test
baseline/MacHost/.build/debug/Vibe\ Screen --video-encoder-self-test
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests 'dev.telemachus.display.protocol.VideoColorNegotiationTest' \
  --tests 'dev.telemachus.display.protocol.ProtocolV1SessionTest.hdrVideoConfigWithoutNegotiatedHdrReturnsSdrFallback' \
  --tests 'dev.telemachus.display.protocol.ProtocolV1SessionTest.unsupportedDecodeProfileRejectsWithoutSelectedColorFallback' \
  --tests 'dev.telemachus.display.VideoDecoderSdrColorSettingsTest'
```

A local `swift test` run is useful when full Xcode provides XCTest. If the active
Command Line Tools environment cannot import `XCTest`, record that as a blocked
local XCTest condition and rely on executable self-tests plus CI for XCTest.

The offline gate may claim only:

- clients that do not negotiate `CAPABILITY_HDR_VIDEO` are sent SDR video config;
- HDR color descriptions require `CAPABILITY_COLOR_MANAGEMENT`,
  `CAPABILITY_HDR_VIDEO`, and an explicit matching decode profile;
- an unsupported HDR profile returns or accepts only a validated SDR fallback;
- the current macOS encoder is configured as BT.709, 8-bit, non-HDR output;
- the current Android decoder asks MediaCodec for BT.709 SDR limited-range
  surface decode.

## Real-device HDR output gate

Do not mark HDR output passed without all of the following retained artifacts:

- exact host commit, client commit, and dirty-tree state;
- host display identity and proof that the source content or display is HDR/EDR;
- negotiated Protocol v1 envelopes showing `CAPABILITY_HDR_VIDEO`, codec, color
  description, config epoch, stream ID, and matching video config result;
- explicit 10-bit/PQ or HLG decode capability from the client and output-format
  logs from the hardware decoder;
- client display or platform evidence that HDR/EDR output was actually enabled;
- external observation or platform diagnostic output showing visible HDR output;
- fallback evidence for an SDR-only peer in the same source revision.

Simulator output, loopback transport tests, Android evidence for iOS, Protocol
field presence, and SDR fallback tests are readiness inputs only. They do not
prove visible HDR/EDR output.

## iOS HDR/EDR current-base owner

The iOS HDR output / EDR rendering gate is owned by the dedicated current-base
verifier below. It is separate from the macOS HDR-to-SDR fallback work and from
the broader iOS aggregate gate: the aggregate may reference this summary, but it
must not close HDR output unless this verifier reports `pass`.

```bash
make ios-hdr-edr-gate EVIDENCE_DIR=.build/evidence/ios-hdr-edr
```

By default the target reads
`.build/evidence/ios-hdr-edr/ios-hdr-edr-observations.json` and writes
`ios-hdr-edr-gate.json`. If the observations file is missing, malformed, or
does not contain every required proof point, the verifier writes a blocked
summary and exits nonzero. That blocked output is useful readiness evidence; it
does not close the README Phase 5 HDR gate.

The observations must use `schema_version=vibescreen.evidence/v1` and
`kind=ios_hdr_edr_readiness_observations`, then include all of these retained
proof points:

- clean current-base repository commit;
- physical iPhone or iPad identity and an HDR-capable display;
- measured EDR headroom or equivalent platform HDR display diagnostic;
- `CAPABILITY_HDR_VIDEO` advertisement and accepted HDR video config;
- 10-bit VideoToolbox decode capability with PQ or HLG transfer and BT.2020 or
  Display P3 metadata;
- VideoToolbox/CoreVideo output pixel format and HDR frame attachments;
- renderer-layer evidence that EDR/HDR output is enabled;
- visible HDR/EDR output evidence or a platform diagnostic proving it;
- same-revision SDR-only peer fallback evidence;
- local retained artifact paths for the logs, diagnostics, visible output, and
  gate summary.

Set the invalid-evidence flags when a run includes Simulator output, unsigned
archives, Android evidence, SDR fallback promoted as HDR, protocol fields alone,
or macOS fallback evidence. Any such substitution returns `fail` and keeps
`can_close_ios_hdr_output_gate=false`.

## Android device notes

When a real Android run is scheduled, every ADB command for the current shared
phone must use the explicit serial:

```bash
adb -s EP0110PZ0B9110300B shell getprop ro.product.manufacturer
adb -s EP0110PZ0B9110300B shell getprop ro.product.model
adb -s EP0110PZ0B9110300B shell getprop ro.product.device
adb -s EP0110PZ0B9110300B shell getprop ro.build.version.release
adb -s EP0110PZ0B9110300B shell getprop ro.build.version.sdk
```

Record the current shared device as Nubia P0110 / pacific / Android 16 / SDK
36 when those properties match. Do not relabel it as Xiaomi 13/fuxi evidence.

## Fail-closed reporting

Use these labels consistently:

- `fallback_offline_pass`: protocol/encoder/decoder unit and self-tests pass,
  but no display hardware was exercised;
- `fallback_device_ready`: a real device run has proved SDR fallback negotiation
  and continued SDR rendering for an unsupported HDR input;
- `hdr_output_pass`: real HDR/EDR hardware evidence proves the full HDR path.

Until the last label has retained evidence, README and Phase 5 summaries must keep
HDR output open.
