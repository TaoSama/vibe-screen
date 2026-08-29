# Audio USB/LAN Protocol v1 wiring verification

Status: offline implementation verified; real-device USB/LAN audio playback blocked
Date: 2026-08-23
Source branch: `codex/audio-usb-lan-e2e-gate`
Base commit: `781992d7dc6e99d62ddd5326853f689c30c53d67` (`origin/main` at
rebase)

## Scope

This change wires the existing macOS `MacHostAudioStream` and Android
`ProtocolPcmAudioPlayer` into the production Protocol v1 USB/LAN session. The
implemented path is Host-to-Android PCM S16LE audio using the current macOS
`AVAudioEngine.inputNode` source, so it is a microphone-capture path rather than
Mac system-output capture. Audio is negotiated with `CAPABILITY_AUDIO`,
`maximum_audio_streams`, `AudioConfig`, `AudioConfigResult`, and TCP logical
channel `3`; legacy peers and sessions that do not negotiate audio retain the
existing no-audio behavior.

## Automated checks

| Check | Result | Evidence |
| --- | --- | --- |
| `make protocol` | PASS | Buf format/lint/build/breaking and 36 Python protocol/security contract tests passed. |
| `cd baseline/MacHost && swift build` | PASS | Source builds with SwiftPM. |
| `cd baseline/MacHost && .build/debug/"Vibe Screen" --transport-self-test && .build/debug/"Vibe Screen" --audio-capture-self-test` | PASS | Production transport self-test and audio capture self-test passed using self-test capture fixtures, independent of local Microphone/TCC state. |
| `cd baseline/MacHost && swift test --filter ProtocolV1SessionTests` | BLOCKED | Local toolchain cannot import `XCTest` from Command Line Tools: `no such module XCTest`. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "*StreamProtocolActionDispatcherTest" --tests "*ProtocolV1SessionTest" --tests "*ProtocolV1FramingTest" --tests "*ProtocolPcmAudioPlaybackTest" --tests "*StreamClientProtocolV1IntegrationTest" --tests "*AndroidSessionPacketCipherTest"` | PASS | Covers audio action dispatch, audio capability/resource negotiation, `AudioConfig` accept/reject, display reconfiguration with active audio, channel 3 framing, Android PCM playback/reconfigure cleanup, StreamClient loopback playback/reject cleanup, and LAN secure-record audio/bulk channel declaration. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug` | PASS | Full Android local gate completed: Debug unit tests, lint, and debug APK assembly passed. |

## Real-device status

No current-source real USB or LAN audio playback run was completed in this
environment. The implementation remains blocked from device acceptance by the
same local prerequisites that affect other current-source device gates: stable
Host signing/TCC setup is unavailable here, and no verified Microphone-permitted
Host plus Android playback capture was collected. LAN also still requires an
associated Android Wi-Fi interface and secure-record admission evidence before
it can close.

The retained blocked/readiness record is
[`evidence/2026-08-21-audio-real-device-blocked/README.md`](evidence/2026-08-21-audio-real-device-blocked/README.md).
The current P0110 owner record is tracked separately under
[`../2026-08-24-p0110-audio-current-base/TEST.md`](../2026-08-24-p0110-audio-current-base/TEST.md).
Use `make android-audio-playback-owner-record EVIDENCE_DIR=<run-dir>` to
preserve blocked or insufficient current-base evidence, and use
`make android-audio-playback-gate EVIDENCE_DIR=<run-dir>` only for a formal
closing attempt because it requires `can_close_android_audio_playback_gate=true`.

## Open gates

- Real USB Protocol v1 audio playback on a named Android device.
- Real trusted-LAN Protocol v1 audio playback with AES-256-GCM secure records
  and no plaintext fallback.
- Product decision and implementation for Mac system-output capture, if that is
  required separately from the current microphone PCM source.
