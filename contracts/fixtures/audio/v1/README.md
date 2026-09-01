# Protocol v1 USB/LAN PCM audio fixture

This fixture pins the offline USB/LAN Protocol v1 PCM S16LE product flow. It is
kept separate from the Internet AUDIO/BULK channel-security fixtures because it
describes the inner product-session audio contract before any transport-security
wrapping: capability admission, logical channel selection, `AudioConfig` bytes,
accepted `AudioConfigResult` bytes, packet boundaries, packet header bytes,
payload bytes, and Android output cleanup expectations.

`usb-lan-pcm-s16le-product-flow.json` contains:

- `transport_modes`: the product transports covered by this offline fixture.
- `capability`: the negotiated Protocol v1 capability required before audio is
  accepted.
- `protocol_channel`: the logical Protocol v1 channel used for audio packets.
- `session_epoch`: the fixed session epoch stamped into packet headers.
- `config`: the fixed PCM S16LE stream format and serialized `AudioConfig`.
- `accepted_config_result`: the Android acceptance response and serialized
  `AudioConfigResult`.
- `capture`: the fixed Host PCM capture buffer that is packetized.
- `packets`: the expected packet sequence, payload, header, and serialized frame
  bytes.
- `cleanup_expectations`: Android output lifecycle events for normal disconnect,
  config rejection, and malformed packet cleanup. `host_stop_reason` is pinned
  to the production macOS Host reconfiguration path, where `StreamingServer`
  stops an already-running Protocol v1 audio stream before applying a new
  `AudioConfig` by recording `MacHostAudioStopReason.reconfigure`
  (`audio_reconfigure`).

This fixture is maintained by hand. Do not overwrite it with a generator to hide
an incompatible wire-format change; update the Swift and Kotlin consumers
together when the contract intentionally changes.

Cross-platform tests that consume this fixture:

- Swift XCTest: `baseline/MacHost/Tests/TelemachusTests/AudioUsbLanPcmFixtureTests.swift`
- Swift release self-test: `baseline/MacHost/Sources/AudioCaptureSelfTest.swift`
- Android JVM: `baseline/AndroidClient/app/src/test/java/dev/telemachus/display/audio/ProtocolPcmAudioStreamTest.kt`
- Android JVM: `baseline/AndroidClient/app/src/test/java/dev/telemachus/display/audio/ProtocolPcmAudioPlaybackTest.kt`
- Android JVM: `baseline/AndroidClient/app/src/test/java/dev/telemachus/display/StreamClientProtocolV1IntegrationTest.kt`

The fixture is offline contract evidence only. It does not prove macOS
Microphone/TCC readiness, Host startup, LAN secure-record delivery, real Android
speaker playback, or audible output.
