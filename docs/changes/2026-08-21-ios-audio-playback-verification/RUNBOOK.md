# iOS PCM playback verification runbook

This runbook verifies the Phase 5 iOS PCM playback path without weakening the
audible-device gate. The verifier uses Protocol v1 `AudioConfig` and
`AudioPacketHeader`, synthetic PCM S16LE payloads, the shared bounded playback
queue policy, and the app's AVFoundation adapter.

## Offline gates

Run these from the repository root after resolving the pinned package:

```bash
swift build --package-path apps/ios --configuration release
swift test --package-path apps/ios --configuration release
apps/ios/.build/release/vibescreen-ios-selftest
```

These commands cover PCM format validation, exact packet byte counts,
session/config epoch rejection, bounded jitter reordering, stale/duplicate media
drops, playback queue overrun/drop accounting, queue-empty accounting,
late-completion accounting, and stop/restart state reset. They do not
instantiate `AVAudioSession` or prove audible output.

## App playback verifier

With full Xcode and an available iOS Simulator or signed device, run:

```bash
xcodebuild -project apps/ios/VibeScreen.xcodeproj \
  -scheme VibeScreen \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  test \
  -only-testing:VibeScreenAppTests/VibeScreenAppUITests/testAudioPlaybackSelfTestSchedulesPCMAndRestarts
```

The test launches `VibeScreen` with `--audio-playback-self-test`. The app
then configures playback-only `AVAudioSession`, starts `AVAudioEngine`,
schedules synthetic PCM S16LE buffers through `AVAudioPlayerNode`, fills the
bounded queue until an overrun/drop is observed, stops, restarts with a newer
config epoch, and displays a single result line:

```text
AUDIO_PLAYBACK_SELF_TEST=PASS scheduled=<n> played=<n> queued=<n> queue_empty=<n> late_completions=<n> overruns=<n> stops=<n>
```

A failing result, launch timeout, missing counter, or queue-limit miss keeps the
playback-path verifier open.

## Audible iPhone/iPad gate

The README Phase 5 audible audio gate closes only after the app verifier above
passes on the same signed build and an iPhone/iPad acceptance run records:

- device model, OS build, app commit, host commit, signing identity status, and
  output route;
- negotiated `AudioConfig`, audio-channel packet epochs, queue depth,
  queue-empty/late-completion/overrun/error counters, any underrun logs from
  the runtime audio stack, and managed audio policy;
- audible confirmation from a listener or external recorder with retained,
  privacy-reviewed artifacts or hashes;
- no Android evidence substituted for the iOS audio gate.

If no iPhone/iPad, signed app, audio-capable host path, or audible capture setup
is available, publish blocked evidence instead of marking the gate passed.
