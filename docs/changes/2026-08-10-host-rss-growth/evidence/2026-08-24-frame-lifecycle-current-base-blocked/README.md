# 2026-08-24 Host RSS frame lifecycle current-base readiness: blocked

This record refreshes the open draft PR #195 work against the current visible
origin/main baseline. It keeps the Host RSS no-growth gate open.

## Verdict

BLOCKED for formal two-hour Host RSS gate closure. Current main already contains
the VideoToolbox in-flight admission and callback registry, HOST_PID fail-closed
soak targets, and closed-socket FD cleanup/readiness from later merged work. The
remaining source value from #195 is a small MacHost frame lifecycle tightening:
all frame-pacer teardown paths now cancel the timer, drop the stale encode queue,
and clear the latest retained pixel buffer through one path; frame-pacer timer
and encode-queue state now use a narrow lock so async stop/switch paths cannot
race live frame-rate reconfiguration; CGDisplayStream fallback and frame-pacer
encode callbacks use explicit autoreleasepool scopes.

This is source-readiness evidence only. It is not a short-window diagnostic pass
and not a two-hour no-growth pass.

## PR audit

- #195 Tighten Host RSS frame lifecycle readiness: open draft, previous base main
  at e8fbed466581c4d20e59801e7d7c0a03af04ad51, previous head
  codex/host-rss-no-growth-fix at fd602c2469d07f0aa8ef6c4cdecc13f0197a1285,
  8 files changed. Still has frame-pacer cleanup/autoreleasepool and
  release-focused test value, but its Makefile HOST_PID part is already covered
  on current main. This current-base successor starts from
  fb4ba4a4801c3ab228855a2e374791558e80401e and keeps only the still-relevant
  lifecycle/test/docs slice.
- #158 test: record Host RSS readiness blocker: merged at
  4d7e90dcce5b033ec366591816cec571382e3249; covers HOST_PID passthrough,
  host RSS gate docs, and P0110 blocked readiness evidence.
- #260 Fix Host closed socket cleanup readiness: merged at
  1db736bf0e53e63e5843acc8c9bbf6b6f11fb49e; covers the NWConnection
  closed-socket retention candidate, host_socket_fd diagnostic, and formal Host
  RSS Makefile entry points.

PR facts were refreshed with local gh plus remote refs.

## Source changes

- baseline/MacHost/Sources/ScreenCapture.swift: unifies frame-pacer cleanup via
  clearFramePacer(), including encodeQueue = nil and latestPixelBuffer.clear();
  applies the cleanup to display switch, codec switch, stop, terminal fallback,
  and final stop state; locks frame-pacer timer/queue state across async teardown
  and live frame-rate reconfiguration; wraps CGDisplayStream fallback and
  frame-pacer encode callbacks in autoreleasepool.
- baseline/MacHost/Tests/TelemachusTests/LatestRetainedSlotTests.swift: adds
  release assertions for replacing and clearing the latest retained value, plus
  a reentrant deinit check proving replaced values are released outside the slot
  lock.
- baseline/MacHost/Tests/TelemachusTests/VideoEncoderInFlightAdmissionTests.swift:
  asserts callback registry drain releases the retained FrameContext.
- docs/changes/2026-08-10-host-rss-growth/TECH.md: records the current-base
  split between already-merged gate/tooling work and this remaining lifecycle
  tightening.

## Blocked checks

- xcode-select -p reports /Library/Developer/CommandLineTools; xcrun --find
  xctest fails with unable to find utility "xctest", so focused Swift XCTest
  cannot run in this environment.
- adb -s <redacted-adb-serial> confirms a connected nubia P0110 / pacific /
  Android 16 / SDK 36 device for general Android substitution, but this Host RSS
  source-readiness slice did not run a fresh Android stream.
- A fresh local Swift build was attempted from the current-base successor; the
  build result is recorded in commands.txt for this run. Focused XCTest still
  requires full Xcode.
- No stable-signed current-source Host was installed or launched with
  VIBE_SCREEN_TELEMETRY_PATH, and no 10-17 minute short diagnostic or formal
  two-hour soak was started.

## Verification completed

- python3 -m json.tool docs/changes/2026-08-10-host-rss-growth/evidence/2026-08-24-frame-lifecycle-current-base-blocked/readiness-report.json
- git diff --check
- adb -s <redacted-adb-serial> get-state and device getprop identity checks

## Required rerun

With full Xcode selected, first run:

    cd baseline/MacHost
    swift test --filter "VideoEncoderInFlightAdmissionTests|LatestRetainedSlotTests"

Then, from a Screen Recording/Accessibility-authorized Host build that matches
this source revision, use the formal Host RSS gate path:

    export EVIDENCE_SERIAL=<redacted-adb-serial>
    export EVIDENCE_DIR=.build/evidence/host-rss-2026-08-24
    export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
    mkdir -p "$EVIDENCE_DIR/soak-2h"
    # Start the matching Host and establish the USB stream, then record its PID.
    export HOST_PID="running-host-pid"
    make soak-2h-host-rss-gate EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
      EVIDENCE_DIR="$EVIDENCE_DIR" HOST_PID="$HOST_PID"

Only a complete host-rss-gate.json with verdict pass can close the README Host
RSS no-growth gate.
