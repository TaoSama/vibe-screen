# P0110 Android audio current-base owner

Status: Android local playback-adapter smoke added; real USB/LAN audio playback blocked
Date: 2026-09-06
Previous record: 2026-09-01
Source branch: `android-audio-track-smoke`
Base commit: `origin/main` at `f97ea7d6ad2bba93720332f31609e691cb648088`

## Scope

This record establishes the current-base Android/P0110 owner for the README
Protocol v1 USB/LAN audio playback gate. It does not change the product audio
path from the merged Host-to-Android PCM S16LE microphone-capture wiring. The
gate still requires real-device playback evidence from the production session:
`CAPABILITY_AUDIO`, accepted PCM S16LE `AudioConfig`, Host channel `3` packet
flow, Android `AudioTrack` start/write evidence, audible or
instrumentation-backed playback confirmation, and disconnect cleanup.

The 2026-09-01 follow-up adds an offline USB/LAN PCM S16LE product-flow
contract fixture at
[`../../../contracts/fixtures/audio/v1/usb-lan-pcm-s16le-product-flow.json`](../../../contracts/fixtures/audio/v1/usb-lan-pcm-s16le-product-flow.json).
The fixture is intentionally separate from the Phase 3 Internet AUDIO/BULK
secure-record fixture. It pins Protocol v1 audio format negotiation,
`sample_rate_hz`, `channel_count`, `frames_per_packet`, `stream_id`,
`config_epoch`, `session_epoch`, channel `3`, packet boundaries, serialized
headers, Android `AudioTrack` submission order, and cleanup expectations for
disconnect/error paths. This is offline contract evidence only; it does not
prove Microphone/TCC readiness, macOS Host startup, LAN secure-record delivery,
or real Android speaker playback.

The 2026-09-06 follow-up adds a P0110 no-Host instrumentation smoke at
[`../../../baseline/AndroidClient/app/src/androidTest/java/dev/telemachus/display/audio/ProtocolPcmAudioPlayerInstrumentedTest.kt`](../../../baseline/AndroidClient/app/src/androidTest/java/dev/telemachus/display/audio/ProtocolPcmAudioPlayerInstrumentedTest.kt).
It directly constructs `ProtocolPcmAudioPlayer(AndroidAudioTrackOutputFactory())`,
configures PCM S16LE 48 kHz stereo, submits one silent 480-frame packet at
sequence `0`, verifies one accepted write, and closes the player. This proves
Android local playback-adapter availability on the P0110 only. It does not
launch a Host, negotiate `CAPABILITY_AUDIO`, accept a Host-sent `AudioConfig`,
carry channel `3` packets over USB/LAN, prove audible output, or close the real
audio playback gate.

## PR audit

| PR | Status | Audio-gate effect |
| --- | --- | --- |
| [#305](https://github.com/TaoSama/vibe-screen/pull/305) | Merged | Implements Protocol v1 USB/LAN Host-to-Android microphone PCM wiring and offline Host/Android/LAN secure-record tests. It explicitly leaves real USB and trusted-LAN audio playback evidence open. |
| [#197](https://github.com/TaoSama/vibe-screen/pull/197) | Closed | Earlier audio wiring attempt with the same real-device blockers; not a merged current-base pass. |
| [#209](https://github.com/TaoSama/vibe-screen/pull/209) | Open | iOS AVAudioEngine/PCM verifier work. It is adjacent only and cannot support Android P0110 USB/LAN playback. |

## Current-base P0110 readiness

Latest evidence directory:
[`evidence/2026-08-30-p0110-audio-current-base-refresh`](evidence/2026-08-30-p0110-audio-current-base-refresh/README.md).

The retained device identity is `nubia P0110 / pacific / Android 16 / SDK 36`;
public artifacts use `<ANDROID_SERIAL>` instead of the real device serial. The
2026-08-30 refresh did not install or start the Android app and did not change
ADB reverse state; it only retained the existing device, USB, app, log, and
Host readiness state. That is still not an audio pass: no Host listener was
observed, the installed Host bundle did not prove current-source stable signing
plus Microphone/TCC readiness, and retained logs show no `CAPABILITY_AUDIO`,
accepted `AudioConfig`, Host channel `3` packet flow, Android `AudioTrack`
writes, audible output, Protocol v1 session proof from the current refresh, or
cleanup evidence.
Trusted-LAN audio remains blocked separately because no usable `wlan0` IPv4
route evidence was retained.

The machine-checkable summary is
[`android-audio-playback-summary.json`](evidence/2026-08-30-p0110-audio-current-base-refresh/android-audio-playback-summary.json):
`verdict=blocked` and `can_close_android_audio_playback_gate=false`.

## Android-local no-Host playback-adapter smoke

Latest evidence directory:
[`evidence/2026-09-06-p0110-audio-android-track-no-host-smoke`](evidence/2026-09-06-p0110-audio-android-track-no-host-smoke/README.md).

The retained device identity is `nubia P0110 / pacific / Android 16 / SDK 36`;
public artifacts use `REDACTED_P0110_USB_SERIAL` instead of the real device
serial. The smoke installs/runs only the Android test APK and keeps the macOS
Host out of scope. It does not create or remove `adb reverse tcp:54321`, does
not start Vibe Screen/MacHost/Telemachus GUI, and does not touch macOS TCC,
Keychain, Screen Recording, Accessibility, or System Settings.

## Automated checks

The first rows are the 2026-09-06 Android-local playback-adapter smoke. The
next rows are the 2026-09-01 offline contract refresh. The remaining
2026-08-30, 2026-08-29, and 2026-08-28 rows are retained as historical context
for the earlier blocked owner record.

| Check | Result | Evidence |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.audio.ProtocolPcmAudioPlayerInstrumentedTest` | PASS | Ran on nubia P0110 / pacific / Android 16 / SDK 36 with `Finished 1 tests on P0110 - 16`. The retained logcat marker is `android_audio_track_smoke=start_write_close packets=1 bytes=1920`, proving local `AndroidAudioTrackOutputFactory` plus `ProtocolPcmAudioPlayer` start/write/close with synthetic PCM only. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "dev.telemachus.display.audio.ProtocolPcmAudioPlaybackTest" --tests "dev.telemachus.display.audio.ProtocolPcmAudioStreamTest"` | PASS | Focused JVM audio tests passed as the protocol/fake-output companion to the P0110 no-Host smoke. |
| `make protocol` | PASS | Buf format/lint/build/breaking and 45 Python protocol/security/shared-model tests passed. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "dev.telemachus.display.audio.ProtocolPcmAudioStreamTest" --tests "dev.telemachus.display.audio.ProtocolPcmAudioPlaybackTest" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.usbLanPcmFixtureNegotiatesWritesAndCleansUpOnDisconnect" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.rejectedAudioReconfigurationStopsExistingPlayback" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.malformedAudioPacketAfterAcceptedConfigFailsSessionAndReleasesOutput"` | PASS | Focused Android JVM contract covers the shared USB/LAN PCM fixture, format fields, `AudioConfigResult` bytes, packet parsing, jitter ordering, `AudioTrack` payload submission, disconnect cleanup, config-reject cleanup, and malformed-packet error cleanup. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug` | PASS | Full Android local gate passed on rerun. An earlier run hit one transient non-audio `StreamClientCancellationTest.readySessionRejectsMalformedDisplayWithoutReconnectLoop` `SocketException`; that test passed when rerun directly before the full gate passed. |
| `make baseline-android-check` | PASS | CI-equivalent Android gate passed: transport module checks, unit tests, lint, debug APK assembly, and release dependency audit. Gradle reported existing configuration-cache serialization problems for two custom transport verification tasks and discarded the cache, but the build completed successfully. |
| `cd baseline/MacHost && swift build -c release -Xswiftc -file-prefix-map -Xswiftc "$(pwd)/../..=."` | PASS | Release Host build completed locally. |
| `cd baseline/MacHost && host_bin="$(swift build -c release -Xswiftc -file-prefix-map -Xswiftc "$(pwd)/../..=." --show-bin-path)/Vibe Screen" && "$host_bin" --audio-capture-self-test` | PASS | Release audio self-test consumed the shared USB/LAN PCM fixture and passed config, packetization, decode, lifecycle, error, and stale-generation checks without touching real Microphone/TCC. |
| `make baseline-macos-self-test` | PASS | Release Host build completed and the standard macOS self-test now includes `Audio capture self-test: PASS` alongside Host, transport, reliability, Protocol v1, video encoder, and Phase 3 real-media self-tests. This remains offline coverage, not USB/LAN playback evidence. |
| `cd baseline/MacHost && swift test --filter AudioUsbLanPcmFixtureTests` | BLOCKED | Local Command Line Tools environment cannot import `XCTest`: `no such module XCTest`. CI with full Xcode must prove the XCTest fixture. |
| `python3 -m py_compile scripts/android_audio_current_base_readiness.py scripts/android_audio_readiness_support.py scripts/tests/test_android_audio_current_base_readiness.py` | PASS | Collector and focused test modules compile. |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_android_audio_current_base_readiness -v` | PASS | Collector unit tests verify public redaction, blocked observation semantics, forbidden login-item diagnostic avoidance, and device-lock behavior. |
| `make android-audio-current-base-readiness EVIDENCE_SERIAL=<ANDROID_SERIAL> EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-30-p0110-audio-current-base-refresh` | PASS | Wrote sanitized read-only current-base evidence and a fail-closed owner record without installing/starting the app, changing ADB reverse, clearing logcat, requesting TCC, or running login-item diagnostics. |
| `make android-audio-playback-owner-record EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-30-p0110-audio-current-base-refresh` | PASS | Rebuilt `android-audio-playback-summary.json` while preserving the expected fail-closed `blocked` result for a current-base owner record. |
| `make android-audio-playback-gate EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-30-p0110-audio-current-base-refresh` | NON-PASS | Re-ran the formal closing gate; expected fail-closed `blocked` result because Host listener/current-source stable signing/TCC readiness and Protocol v1 audio playback evidence are missing. |
| `make baseline-macos-self-test` | PASS | Release Host build completed and the standard macOS self-test now includes `Audio capture self-test: PASS` alongside Host, transport, reliability, Protocol v1, video encoder, and Phase 3 real-media self-tests. This remains offline coverage, not USB/LAN playback evidence. |
| `PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial <ANDROID_SERIAL> --package dev.telemachus.display --output evidence/2026-08-28-p0110-audio-current-base-blocked/device-info.json` | PASS | Wrote sanitized `device-info.json` with nubia/P0110/pacific/Android 16/SDK 36 identity and installed APK metadata. |
| `PYTHONPATH=tools python3 -m vibescreen_evidence.usb_live_smoke --allow-existing-device-lock --serial <ANDROID_SERIAL> --package dev.telemachus.display --port 54321 --output evidence/2026-08-28-p0110-audio-current-base-blocked/usb-live-smoke.json` | PASS | Observed current USB video stream, foreground app, ADB reverse, and decoder counters; this does not prove audio playback. |
| `python3 scripts/macos_dev_host.py preflight --source-root . --report evidence/2026-08-28-p0110-audio-current-base-blocked/macos-dev-host-preflight-current-base.txt` | BLOCKED | Failed closed before Host/device audio acceptance because the configured stable local signing identity is unavailable. |
| `python3 scripts/macos_dev_host.py readiness --source-root . --report evidence/2026-08-28-p0110-audio-current-base-blocked/macos-dev-host-readiness-current-base.txt --json-output evidence/2026-08-28-p0110-audio-current-base-blocked/host-readiness.json --port 54321` | BLOCKED | Read-only readiness recorded Host listener presence but could not prove stable signing, current-source Host provenance, or Microphone/TCC readiness. No login-item diagnostic opt-in was used. |
| `make android-audio-playback-owner-record EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-28-p0110-audio-current-base-blocked` | PASS | Wrote `android-audio-playback-summary.json` while preserving the expected fail-closed `blocked` result for a current-base owner record. |
| `make android-audio-playback-gate EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-28-p0110-audio-current-base-blocked` | NON-PASS | Re-ran the formal closing gate; expected fail-closed `blocked` result because Host stable signing/TCC readiness and Protocol v1 audio playback evidence are missing. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools/tests/test_android_audio_playback.py -v` | PASS | Evidence gate unit tests passed, including fail-closed blocked/insufficient behavior. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "*ProtocolPcmAudioPlaybackTest" --tests "*StreamClientProtocolV1IntegrationTest"` | PASS | Focused Android JVM tests for PCM playback and Protocol v1 audio integration passed. |

## Open gates

- Real USB Protocol v1 audio playback on the named P0110 device.
- Real trusted-LAN Protocol v1 audio playback with AES-256-GCM secure records and no plaintext fallback.
- Mac system-output capture, if required as a product behavior beyond the current microphone PCM source.
