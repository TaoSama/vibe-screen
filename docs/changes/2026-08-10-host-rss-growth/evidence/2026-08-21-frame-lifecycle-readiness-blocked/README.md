# 2026-08-21 Host RSS frame lifecycle readiness: blocked

This record covers the source-readiness state for moving the Phase 0 Host RSS
no-growth gate from a documented blocker toward a rerunnable fix. It was
rebased and revalidated against current `origin/main` on 2026-08-22.

## Verdict

BLOCKED for formal two-hour Host RSS gate closure. This change tightens and
offline-verifies bounded frame ownership in the MacHost capture/encoder path,
but this worktree did not run a complete two-hour ScreenCaptureKit stream with
matching Host telemetry. The README gate remains open until
vibescreen_evidence.host_rss_gate reports pass on a complete soak.

## Source audited

- Repository: /Users/luwentao/Workspaces/vibe-screen/.claude/worktrees/host-rss-no-growth-fix
- Base commit: e8fbed466581c4d20e59801e7d7c0a03af04ad51
- Branch: codex/host-rss-no-growth-fix
- Historical candidates reviewed: PR #195 (frame lifecycle), PR #222
  (diagnostic telemetry), PR #158 (blocked gate tooling/evidence), plus local
  branches codex/host-rss-frame-ownership,
  origin/codex/host-rss-frame-ownership, codex/host-rss-encoder-callback-bound,
  codex/host-rss-diagnostic-encoder-telemetry, codex/host-rss-readiness,
  codex/macos-frame-mailbox, and codex/macos-encoder-backpressure.

The prior frame-mailbox, pixel-buffer ownership, VideoToolbox in-flight, and
encoder callback admission fixes are already present on current origin/main.
This pass does not reapply unrelated historical branch changes. The remaining
source change is deliberately small: every capture teardown path now uses one
frame-pacer cleanup path that cancels the pacing timer, drops the stale encode
queue reference, and clears the latest retained pixel buffer. The CGDisplayStream
fallback handler and frame-pacer encode handler also now run inside explicit
`autoreleasepool` scopes, matching the existing ScreenCaptureKit and
VideoToolbox callback cleanup style for high-frequency frame work. The formal
soak targets now also accept `HOST_PID`, and `soak-2h-host-rss-gate` fails fast
without it so a rerun cannot silently omit Host RSS samples.

## Offline verification

Commands run from this worktree:

    git fetch origin main --prune
    swift build # in baseline/MacHost
    make baseline-macos-self-test
    PYTHONPATH=tools python3 -m unittest tools.tests.test_host_rss_gate tools.tests.test_host_memory_diagnostic
    make evidence-tools-test
    git diff --check
    adb -s EP0110PZ0B9110300B shell getprop ro.product.manufacturer
    adb -s EP0110PZ0B9110300B shell getprop ro.product.model
    adb -s EP0110PZ0B9110300B shell getprop ro.product.device
    adb -s EP0110PZ0B9110300B shell getprop ro.build.version.release
    adb -s EP0110PZ0B9110300B shell getprop ro.build.version.sdk

Observed results:

- swift build passed for the MacHost executable target.
- make baseline-macos-self-test passed the release Host, transport, reliability,
  Protocol v1, and VideoEncoder self-tests.
- The Python host RSS gate and short memory diagnostic tests ran 62 tests with
  zero failures through the standard-library unittest runner.
- make evidence-tools-test ran 219 tests with zero failures.
- git diff --check reported no whitespace errors.
- The attached Android device reports nubia, P0110, pacific, Android 16, SDK
  36. This device may be used as the Android substitute for a future general
  USB/LAN run, but this record does not relabel it as Xiaomi 13/fuxi evidence.
- /tmp/vibe-screen-device-android.lock was absent when checked. A P0110 smoke
  was still not started because the installed Host is not a stable-signed
  current-source build: `scripts/macos_dev_host.py preflight` fails before TCC
  verification because the local keychain has no `Vibe Screen Dev` signing
  identity, and the installed `/Applications/Vibe Screen.app` binary hash does
  not match the worktree release binary.

## Blocked checks

- swift test --filter "VideoEncoderInFlightAdmissionTests|LatestRetainedSlotTests"
  could not execute in this environment because xcode-select points to
  /Library/Developer/CommandLineTools, xcrun --find xctest fails, and the Swift
  test target fails to import XCTest. The test sources were updated, but the
  XCTest run still needs a full Xcode-selected environment.
- No Screen Recording/TCC-controlled Host app session was started from this
  worktree, and no complete two-hour soak was attempted. Therefore there is no
  valid summary.json, samples.jsonl, host-telemetry.jsonl, or host-rss-gate.json
  produced by this record.
- Host signing/TCC preflight is blocked before a safe device smoke can start:
  `python3 scripts/macos_dev_host.py preflight` exits 1 because the configured
  `Vibe Screen Dev` signing identity is missing. Ad-hoc signing would change
  the macOS privacy identity and is not evidence-grade for this gate.

## Required rerun

With full Xcode selected, first run the focused MacHost tests:

    cd /Users/luwentao/Workspaces/vibe-screen/.claude/worktrees/host-rss-no-growth-fix/baseline/MacHost
    swift test --filter "VideoEncoderInFlightAdmissionTests|LatestRetainedSlotTests"

Then, on a Screen Recording/Accessibility-authorized Host build from the same
source revision, run a short diagnostic before spending two hours:

    cd /Users/luwentao/Workspaces/vibe-screen/.claude/worktrees/host-rss-no-growth-fix
    export EVIDENCE_SERIAL=EP0110PZ0B9110300B
    export EVIDENCE_DIR=.build/evidence/host-rss-2026-08-22
    export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/memory-short/host-telemetry.jsonl"
    mkdir -p "$EVIDENCE_DIR/memory-short"
    # Start the matching Host with VIBE_SCREEN_TELEMETRY_PATH, establish USB stream, then:
    PYTHONPATH=tools python3 -m vibescreen_evidence.host_memory_diagnostic \
      --host-pid "$HOST_PID" \
      --duration-seconds 900 \
      --interval-seconds 30 \
      --telemetry-jsonl "$EVIDENCE_DIR/memory-short/host-telemetry.jsonl" \
      --samples "$EVIDENCE_DIR/memory-short/samples.jsonl" \
      --output "$EVIDENCE_DIR/memory-short/diagnostic.json"

If the short diagnostic is pass, run the formal gate:

    export EVIDENCE_SERIAL=EP0110PZ0B9110300B
    export EVIDENCE_DIR=.build/evidence/host-rss-2026-08-22
    export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
    mkdir -p "$EVIDENCE_DIR/soak-2h"
    make soak-2h-host-rss-gate EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
      EVIDENCE_DIR="$EVIDENCE_DIR" HOST_PID="$HOST_PID"

Only a complete run with host-rss-gate.json verdict pass can close the Host RSS
no-growth gate. A short diagnostic pass, a 30-minute soak, a partial summary,
or this blocked readiness record cannot close it.
