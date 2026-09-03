# Internet audio DataChannel verification

Status: offline implementation verified; real public-Internet audio playback blocked
Owner: Vibe Screen core team
Branch: `codex/internet-audio-datachannel`
Date: 2026-09-01

## Scope

This record covers the Internet product-session audio slice only:
Host-to-Android PCM S16LE microphone packets over the protected
`vibescreen.audio.v1` DataChannel. The product contract uses stream ID `2`,
config epoch `1`, PCM S16LE, 48 kHz, 2 channels, and 480 frames per packet.

This is not bidirectional audio, not macOS system-output capture, and not a
real public-Internet product run. It does not install or launch the macOS Host,
request TCC/Microphone permissions, use ADB, or verify audible Android output.

## Verified behavior

- macOS advertises Internet audio only when managed policy allows capture, the
  configuration marks capture available, and the capture adapter can advertise.
- macOS sends `AudioConfig` only after the first accepted video configuration,
  so video startup is not blocked by optional audio.
- macOS starts microphone capture only after `AudioConfigResult(accepted=true)`
  and sends PCM frames through the audio DataChannel binding.
- macOS disables audio without closing the video session when peer audio config
  rejection, capture start failure, or capture runtime error occurs.
- macOS transport recovery restarts already streaming audio capture, and resends
  a pending `AudioConfig` when recovery happens while awaiting the audio result.
- Android advertises audio only when a playback adapter is available, configures
  playback only after negotiated `.audio`, and returns `AudioConfigResult` for
  accepted and rejected configurations.
- Android treats a repeated already accepted identical `AudioConfig` as
  idempotent, while stale or conflicting audio epochs are rejected without
  failing the session.
- Android routes configured PCM audio records into the playback adapter, keeps
  the raw callback path only for unconfigured records, and stops playback on
  close, failure, fresh-session recovery, revocation, and transport closure.

## Automated checks

Run from cleanly reviewed source in this branch after the implementation patch:

| Command | Result | Evidence |
| --- | --- | --- |
| `cd baseline/MacHost && swift build` | PASS | Final post-rebase rerun: `Build complete! (2.91s)` |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "dev.telemachus.display.internet.ProtocolV1ProductCodecTest" --tests "dev.telemachus.display.internet.InternetProductSessionTest" --tests "dev.telemachus.display.audio.ProtocolPcmAudioPlaybackTest" --tests "dev.telemachus.display.audio.ProtocolPcmAudioStreamTest"` | PASS | Final post-rebase rerun: `BUILD SUCCESSFUL in 7s` |
| `cd baseline/MacHost && swift test --filter InternetProductSessionTests` | BLOCKED | Local SwiftPM test environment cannot import `XCTest`: `ADBDeviceSelectionPolicyTests.swift:1:8: error: no such module 'XCTest'` |
| `git diff --check` | PASS | No whitespace errors reported |

Earlier in the same turn, the same focused Android JVM command also passed after
the first audio implementation pass with `BUILD SUCCESSFUL in 15s`, and
`swift build` passed with `Build complete! (7.31s)`.

## Open gates

- Runtime freeze remains active until PR #502 (`codex/host-install-provenance-gate`)
  merges; do not install or launch Host builds for this audio slice while that
  gate is open.
- A stable-signed current-source macOS Host must run with explicit Microphone/TCC
  authorization and prove capture startup, denial handling, and runtime error
  behavior.
- A real Android device must prove `CAPABILITY_AUDIO`, accepted `AudioConfig`,
  protected audio DataChannel packets, `AudioTrack` writes, and audible or
  otherwise observable playback.
- A public Internet route must be retained with packet-capture confidentiality,
  route identity, handoff/recovery, latency, and soak evidence.
- Phase 3 release manifests must keep `audio_capture_playback: not_claimed`
  until the real public-Internet product-flow evidence above exists.
