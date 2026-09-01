# USB/LAN PCM product-flow offline contract

Status: offline contract verified; real USB/LAN playback remains blocked
Date: 2026-09-01
Source branch: `codex/audio-pcm-product-flow`
Base commit: `origin/main` at branch creation

## Scope

This change adds a shared USB/LAN Protocol v1 PCM S16LE product-flow fixture at
[`../../../contracts/fixtures/audio/v1/usb-lan-pcm-s16le-product-flow.json`](../../../contracts/fixtures/audio/v1/usb-lan-pcm-s16le-product-flow.json).
It pins the offline Host-to-Android audio contract for `CAPABILITY_AUDIO`,
logical channel `3`, `stream_id`, `config_epoch`, `session_epoch`,
`sample_rate_hz`, `channel_count`, `frames_per_packet`, accepted
`AudioConfigResult` bytes, packet header bytes, payload boundaries, Android
output write order, and cleanup events.

The fixture is intentionally orthogonal to the Phase 3 Internet AUDIO/BULK
channel-security fixture. It covers the USB/LAN product-session PCM bytes and
does not claim AES-GCM secure-record behavior, Microphone/TCC readiness, Host
launch readiness, real Android speaker playback, or audible output.

## Automated checks

| Check | Result | Evidence |
| --- | --- | --- |
| `make protocol` | PASS | Buf format/lint/build/breaking and 45 Python protocol/security/shared-model tests passed. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "dev.telemachus.display.audio.ProtocolPcmAudioStreamTest" --tests "dev.telemachus.display.audio.ProtocolPcmAudioPlaybackTest" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.usbLanPcmFixtureNegotiatesWritesAndCleansUpOnDisconnect" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.rejectedAudioReconfigurationStopsExistingPlayback" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.malformedAudioPacketAfterAcceptedConfigFailsSessionAndReleasesOutput"` | PASS | Focused Android JVM coverage consumes the fixture for format fields, config/result bytes, packet parsing, jitter ordering, output write order, disconnect cleanup, config-reject cleanup, and malformed-packet cleanup. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug` | PASS | Full Android local gate passed with unit tests, lint, and debug APK assembly. |
| `make baseline-android-check` | PASS | CI-equivalent Android gate passed: transport module checks, unit tests, lint, debug APK assembly, and release dependency audit. Gradle reported existing configuration-cache serialization problems for two custom transport verification tasks and discarded the cache, but the build completed successfully. |
| `cd baseline/MacHost && swift build -c release -Xswiftc -file-prefix-map -Xswiftc "$(pwd)/../..=."` | PASS | Release Host build completed locally. |
| `python3 -m unittest scripts.tests.test_release_tools.MacOSSigningIdentityTests` | PASS | 54 release-tool tests passed, including the new packaging guard that verifies `scripts/package_macos.py` copies the USB/LAN PCM fixture into `.app/Contents/Resources/contracts/fixtures/audio/v1/` so installed Host self-tests do not depend on a source checkout. |
| Local MacHost product runtime self-test (`--audio-capture-self-test`) | NOT RUN | Local Host product execution is intentionally frozen for this PR closeout. The earlier local attempt only completed `swift build`; the product binary path did not resolve and no MacHost/Vibe Screen process was left running. Runtime self-test coverage is delegated to GitHub CI. |
| `make baseline-macos-self-test` | NOT RUN LOCALLY | This target executes the Host product binary, so it is not run locally under the permission freeze. GitHub CI must prove `baseline-macos-self-test`, including `--audio-capture-self-test` fixture coverage. |
| `cd baseline/MacHost && swift test --filter AudioUsbLanPcmFixtureTests` | BLOCKED | Local Command Line Tools environment cannot import `XCTest`: `no such module XCTest`. CI with full Xcode must prove this XCTest target. |
| `pgrep -x "Vibe Screen"`, `pgrep -x VibeScreen`, `pgrep -x MacHost`, `pgrep -x Telemachus` | PASS | No matching Host product process was running after the local build/path-resolution attempt. |

## Relationship to audio playback gate

This fixture supports the offline side of
[`../2026-08-21-audio-usb-lan-end-to-end/TEST.md`](../2026-08-21-audio-usb-lan-end-to-end/TEST.md)
and the P0110 current-base owner record in
[`../2026-08-24-p0110-audio-current-base/TEST.md`](../2026-08-24-p0110-audio-current-base/TEST.md).
It does not close `android-audio-playback-gate`. Closing that gate still
requires real-device evidence to be retained for `CAPABILITY_AUDIO`, accepted PCM
S16LE `AudioConfig`, Host channel `3` packet flow, Android `AudioTrack`
start/write evidence, playback confirmation, and disconnect cleanup.
