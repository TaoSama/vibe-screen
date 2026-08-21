# iOS audio playback blocked evidence

Date: 2026-08-26
Repository: `TaoSama/vibe-screen`
Branch: `codex/ios-audio-pcm-verifier`
Current base: `origin/main` at `f46163524`

## Status

The iOS PCM playback-path verifier was added, but the Phase 5 audible playback
gate remains blocked in this environment.

Implemented verifier coverage:

- Protocol v1 PCM S16LE format validation and exact frame-byte checks;
- bounded jitter/session behavior through existing `AudioPlaybackSession`;
- shared playback queue accounting for scheduled buffers, overrun drops,
  queue-empty transitions, late completions, and stop/restart reset;
- app launch-argument verifier that exercises `AVAudioSession`,
  `AVAudioEngine`, and `AVAudioPlayerNode` when full Xcode can run the iOS app
  on a Simulator or signed device.

Blocked audible evidence:

- active developer directory is Command Line Tools, not full Xcode;
- `xcodebuild` cannot run because no full Xcode is selected;
- `xcrun xctrace list devices` cannot enumerate iPhone/iPad devices;
- no signed iPhone/iPad installation or external audible capture was available;
- no audio-capable host path was exercised end to end in this run.

Therefore this evidence does not claim real audible iPhone/iPad playback.

## Current-base command results

```text
$ TMPDIR=$PWD/.build/tmp swift build --package-path apps/ios --configuration release
Build complete!

$ TMPDIR=$PWD/.build/tmp apps/ios/.build/release/vibescreen-ios-selftest
RUN: framing
RUN: protocol/session
RUN: codec/backoff
RUN: multi-display/audio
RUN: clipboard/file/policy
RUN: HDR/gesture/wake/advanced-proto
RUN: trusted-LAN startup codecs
RUN: owner/media/heartbeat generation gates
PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup

$ TMPDIR=$PWD/.build/tmp apps/ios/Scripts/verify-generated-protocol.sh
generated macOS and iOS Protocol v1 bindings are current

$ TMPDIR=$PWD/.build/tmp make protocol
Ran 37 tests in 111.148s
OK

$ plutil -lint apps/ios/VibeScreen.xcodeproj/project.pbxproj
apps/ios/VibeScreen.xcodeproj/project.pbxproj: OK

$ xmllint --noout apps/ios/VibeScreen.xcodeproj/xcshareddata/xcschemes/VibeScreen.xcscheme
exit 0

$ swiftc -frontend -parse apps/ios/VibeScreenApp/*.swift
exit 0

$ git diff --check
exit 0
```

An earlier `make protocol` attempt failed before completing because the system
temporary volume could not create Python/Go temporary directories (`No space
left on device`). Rerunning with the worktree-local `TMPDIR` above passed.

## Local environment commands

```text
$ xcode-select -p
/Library/Developer/CommandLineTools

$ xcodebuild -version
xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance

$ xcodebuild -showsdks
xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance

$ xcrun xctrace list devices
xcrun: error: unable to find utility "xctrace", not a developer tool or in PATH
```

## How to unblock

Follow `docs/changes/2026-08-21-ios-audio-playback-verification/RUNBOOK.md` on a
Mac with full Xcode, an available iPhone/iPad Simulator or signed device, an
audio-capable host path, and external audible confirmation equipment. Store the
verifier result line, app/device logs, audio route, queue counters, audio-stack
underrun/error logs, and audible capture artifact hashes with the acceptance
package.
