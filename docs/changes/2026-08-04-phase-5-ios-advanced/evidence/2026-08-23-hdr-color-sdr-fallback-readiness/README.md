# HDR/color SDR fallback readiness

Date: 2026-08-23
Scope: current-base HDR/color negotiation and SDR fallback readiness
Verdict: `fallback_offline_pass`; `hdr_output` remains `open`.

## Source boundary

This record covers the current-base slice that keeps production clients fail-safe
when HDR is unsupported. It is not a real HDR/EDR display run and it does not
close the Phase 5 HDR output gate.

The intended behavior is:

- production MacHost capabilities keep `CAPABILITY_HDR_VIDEO` disabled unless a
  caller explicitly marks HDR video available;
- Android Protocol v1 startup advertises color management and SDR decode
  capabilities, not HDR video;
- a host-preferred 10-bit BT.2020/PQ color description falls back to BT.709 SDR
  before `VideoConfig` is advertised to an SDR-only client;
- if a client rejects an HDR `VideoConfig` with a selected SDR color description,
  the host validates that SDR fallback and issues a bumped-epoch `VideoConfig`;
- the macOS encoder and Android decoder are explicitly configured for SDR color
  handling on the current production path.

## Offline checks

Run from the repository root unless a command says otherwise:

```bash
git diff --check
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

MacHost XCTest filters are also relevant when full Xcode provides `XCTest`:

```bash
cd baseline/MacHost
swift test --filter VideoColorNegotiationTests
swift test --filter ProtocolV1SessionTests
swift test --filter VideoEncoderInFlightAdmissionTests
```

If local `swift test` fails before running tests with `no such module 'XCTest'`,
record it as an environment blocker rather than a feature failure; the executable
self-tests and GitHub CI remain the usable local/remote gates for that case.

## 2026-08-23 local result

These checks passed on the current worktree before opening the PR:

```text
git diff --check
make protocol
swift build --package-path baseline/MacHost
baseline/MacHost/.build/debug/Vibe\ Screen --protocol-v1-self-test
baseline/MacHost/.build/debug/Vibe\ Screen --video-encoder-self-test
cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.VideoDecoderSdrColorSettingsTest \
  --tests dev.telemachus.display.protocol.VideoColorNegotiationTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest.clientHelloPinsVersionAndExactProductionCapabilities \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest.hdrVideoConfigWithoutNegotiatedHdrReturnsSdrFallback \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest.unsupportedDecodeProfileRejectsWithoutSelectedColorFallback
```

The Android focused JVM run executed 39 tasks with `BUILD SUCCESSFUL`. The
MacHost executable self-tests reported `Protocol v1 self-test: PASS` and `video
encoder self-test passed`.

This local XCTest command did not run tests because the active local Swift toolchain
cannot import XCTest:

```text
cd baseline/MacHost && swift test --filter VideoColorNegotiationTests \
  --filter ProtocolV1SessionTests \
  --filter VideoEncoderInFlightAdmissionTests
error: no such module 'XCTest'
```

That is recorded as a local environment blocker only; it does not close any
hardware HDR gate.

## Open hardware gates

The following stay open after this readiness pass:

- `hdr_output`: no retained iPhone/iPad or Android HDR/EDR visible-output run;
- `macos_hdr_edr_capture`: no retained ScreenCaptureKit HDR/EDR source capture
  evidence;
- `client_hdr_decode_display`: no retained hardware decoder output and display
  proof for an HDR color description;
- `hdr_to_sdr_device_fallback`: no real-device run that starts from an HDR input
  and visibly confirms SDR fallback output.

A future real-device pass must follow `docs/runbook/hdr-color-acceptance.md` and
must record exact hardware identity, negotiated envelopes, decoder output format,
and display/HDR evidence. The shared Android device, when used, must be recorded
as Nubia P0110 / pacific / Android 16 / SDK 36 and every ADB command must use
`adb -s <redacted-adb-serial> ...`.
