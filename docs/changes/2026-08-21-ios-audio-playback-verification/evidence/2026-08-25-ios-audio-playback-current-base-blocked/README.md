# iOS audio playback blocked evidence

<<<<<<< HEAD
Date: 2026-08-26
Repository: `TaoSama/vibe-screen`
Branch: `codex/ios-audio-pcm-verifier`
Current base: `origin/main` at `f46163524`
=======
Date: 2026-08-27
Repository: `TaoSama/vibe-screen`
Local validation branch: `codex/pr209-current-base-20260827`
PR branch: `codex/ios-audio-pcm-verifier`
Current base: `origin/main` at `e94d3a051e683d2a7d6f34fd03badd1b4ef264d0`
Verified source commit: `839f1fc9520c8ea6ca18e6782aa3fa0f6458e838`
>>>>>>> e2eb8857197382ad70c0cf4c8d4656b0f8ab1c05

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
<<<<<<< HEAD
Build complete!
=======
Build complete! (260.77s)
>>>>>>> e2eb8857197382ad70c0cf4c8d4656b0f8ab1c05

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
<<<<<<< HEAD
Ran 37 tests in 111.148s
=======
Ran 37 tests in 114.188s
>>>>>>> e2eb8857197382ad70c0cf4c8d4656b0f8ab1c05
OK

$ plutil -lint apps/ios/VibeScreen.xcodeproj/project.pbxproj
apps/ios/VibeScreen.xcodeproj/project.pbxproj: OK

$ xmllint --noout apps/ios/VibeScreen.xcodeproj/xcshareddata/xcschemes/VibeScreen.xcscheme
exit 0

$ swiftc -frontend -parse apps/ios/VibeScreenApp/*.swift
exit 0

$ git diff --check
exit 0
<<<<<<< HEAD
```

An earlier `make protocol` attempt failed before completing because the system
temporary volume could not create Python/Go temporary directories (`No space
left on device`). Rerunning with the worktree-local `TMPDIR` above passed.
=======

$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_ios_device_acceptance_gate tools.tests.test_ios_app_signing_readiness tools.tests.test_ios_current_base_manifest tools.tests.test_ios_current_base_gate tools.tests.test_ios_hdr_edr_gate -v
Ran 83 tests in 1.109s
OK

$ PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/evidence_privacy.py --evidence-dir docs/changes/2026-08-21-ios-audio-playback-verification/evidence/2026-08-25-ios-audio-playback-current-base-blocked --output .build/pr209-ios-audio-privacy-scan.json
exit 0
```

The 2026-08-27 current-base rerun used the worktree-local `TMPDIR` above for
SwiftPM, SwiftProtobuf, Go, and Python temporary files.
>>>>>>> e2eb8857197382ad70c0cf4c8d4656b0f8ab1c05

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
