# HDR/color negotiation and SDR fallback blocked evidence

Date: 2026-08-21
Source branch: `codex/hdr-color-sdr-fallback`
Scope: macOS Host Protocol v1 color/HDR negotiation, SDR fallback, and encoder
SDR metadata defaults.

## Result

Blocked for real-device HDR/EDR output evidence. This run proves only offline
protocol behavior, Host executable self-tests, source compilation, Android
fallback unit behavior, and iOS Core self-test behavior. It does not claim HDR
output on macOS, iOS, or Android.

## Implemented fail-closed behavior

- `ProtocolV1SessionConfiguration.productionHostCapabilities` defaults
  `hdrVideoAvailable` to `false`, so production Host capability advertisement
  remains SDR unless a future Host availability check explicitly enables HDR.
- `ProtocolV1SessionConfiguration.preferredColorDescription` defaults to
  BT.709 8-bit SDR.
- `ProtocolV1SessionCoordinator` selects `VideoConfig.color_description`
  through `HostVideoColorNegotiator` using negotiated capabilities and the
  client's `video_decode_capabilities`. Unsupported HDR falls back to legacy
  BT.709 SDR before advertising the config.
- `HostVideoColorNegotiator` accepts HDR only when color-management and HDR
  capabilities are both negotiated and an explicit matching 10-bit/PQ decode
  profile is present; an empty decode-profile list is SDR-only.
- Client rejection with `unsupported_color_or_decode_profile` still sends the
  validated SDR fallback on `config_epoch + 1`, preventing stale media from
  resuming under the rejected config.
- `VideoEncoder` sets explicit BT.709 primaries, BT.709 transfer, BT.709
  YCbCr matrix, 8-bit output depth, and `kVTHDRMetadataInsertionMode_None` for
  the current SDR VideoToolbox path.

## Local verification

```bash
git fetch origin main
make protocol
swift build --package-path baseline/MacHost
baseline/MacHost/.build/debug/Vibe\ Screen --protocol-v1-self-test
baseline/MacHost/.build/debug/Vibe\ Screen --video-encoder-self-test
swiftc -parse \\
  baseline/MacHost/Tests/TelemachusTests/ProtocolV1SessionTests.swift \\
  baseline/MacHost/Tests/TelemachusTests/VideoColorNegotiationTests.swift \\
  baseline/MacHost/Tests/TelemachusTests/VideoEncoderInFlightAdmissionTests.swift
cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest \\
  --tests 'dev.telemachus.display.protocol.VideoColorNegotiationTest' \\
  --tests 'dev.telemachus.display.protocol.ProtocolV1SessionTest.hdrVideoConfigWithoutNegotiatedHdrReturnsSdrFallback' \\
  --tests 'dev.telemachus.display.protocol.ProtocolV1SessionTest.unsupportedDecodeProfileRejectsWithoutSelectedColorFallback'
swift run --package-path apps/ios vibescreen-ios-selftest
git diff --check
```

Observed results:

```text
make protocol: buf format/lint/build/breaking and protocol-tests passed
swift build --package-path baseline/MacHost: Build complete!
baseline/MacHost/.build/debug/Vibe\ Screen --protocol-v1-self-test: Protocol v1 self-test: PASS
baseline/MacHost/.build/debug/Vibe\ Screen --video-encoder-self-test: video encoder self-test passed
swiftc -parse ...: exit 0
Android targeted unit tests: BUILD SUCCESSFUL
swift run --package-path apps/ios vibescreen-ios-selftest: PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup
git diff --check: exit 0
```

## Blocked gates

- Local MacHost XCTest execution is blocked because the selected developer
  directory is `/Library/Developer/CommandLineTools`; `xcrun --find xctest`
  cannot find `xctest`, and `xcodebuild -version` reports that full Xcode is
  not selected.
- No HDR-capable Mac display, EDR output capture, iOS HDR real device, or
  signed iOS installation run was available in this evidence pass.
- The Host does not enable a 10-bit Main10/PQ/BT.2020 VideoToolbox output path
  in production. The new availability flag remains off by default.
- No Android HDR real-device run was performed. The only Android command here
  is JVM unit coverage of existing SDR fallback behavior.

## Required follow-up evidence

- Run the MacHost XCTest filters under full Xcode:
  `VideoColorNegotiationTests`, the new `ProtocolV1SessionTests/testHDR...`
  filters, and `VideoEncoderInFlightAdmissionTests/testSDRColorMetadataPropertiesDescribeBT709EightBitOutput`.
- Add an explicit Host HDR availability probe and only then enable
  `hdrVideoAvailable` for production when a matching HDR capture/encode/output
  path is proved.
- Record real HDR/EDR output on qualified Mac and iOS hardware before closing
  the Phase 5 HDR/EDR output gate.
