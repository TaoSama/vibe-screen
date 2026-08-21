# PR #157 Rescue Rebase

Date: 2026-08-21 Asia/Shanghai
Branch: codex/android-clipboard-e2e-evidence
Source head at verification: local detached HEAD after rebasing onto origin/main
Baseline: origin/main at c5add121d4ebebaa0083db64551a81ec7899696e
Scope: rescue PR #157 after main advanced beyond the draft clipboard runbook PR
Verdict: source/docs rebased and focused offline checks passed; clipboard device E2E gate remains open

## Rebase

The PR branch rebased cleanly onto origin/main
c5add121d4ebebaa0083db64551a81ec7899696e (Handle empty ScreenCaptureKit
display catalog (#170)). This removed the BEHIND state locally before push and
did not require conflict edits.

## Passed Checks

- Android focused clipboard JVM tests:
  ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest --tests dev.telemachus.display.ClipboardApprovalStateTest
  reported BUILD SUCCESSFUL in 1m 36s.
- Protocol fixture tests:
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest contracts.tests.test_protocol_fixtures -v
  reported Ran 16 tests in 98.654s OK.
- Evidence tool tests:
  make evidence-tools-test reported Ran 198 tests in 20.886s OK.
- git diff --check origin/main...HEAD passed.
- Both retained clipboard evidence JSON files parsed with python3 -m json.tool.
- The Mac release Host built and --host-self-test, --reliability-self-test,
  --protocol-v1-self-test, and --video-encoder-self-test passed.

## Blockers

- Host preflight failed before any device E2E action because the local keychain
  still lacks the stable Vibe Screen Dev signing identity. Ad-hoc signing was
  not used because it changes the code-signing hash and invalidates macOS Screen
  Recording/Accessibility permission continuity.
- make baseline-macos-self-test did not fully pass locally: --transport-self-test
  failed with POSIXErrorCode(rawValue: 48): Address already in use. The other
  individual self-tests listed above passed when run separately.
- Local swift test --filter Clipboard did not produce a reportable pass in this
  Command Line Tools environment during the rescue pass; prior retained evidence
  records the local XCTest blocker as error: no such module 'XCTest'.

## Device Evidence Boundary

No ADB command or device E2E was run during this rescue pass. Another local
process was observed collecting P0110 network state for a separate LAN smoke
task, so this task did not acquire the device. The existing P0110 evidence in
this PR remains Android-local ClipboardManager smoke only and must not be
reported as Android <-> macOS clipboard E2E evidence or as Xiaomi/fuxi evidence.

## Gate Status

The Android ClipboardManager <-> macOS NSPasteboard device gate remains open.
Closing it still requires a current-branch stable-signed Host with macOS
permissions, same-session Protocol v1 clipboard capability negotiation, and
verified Android -> Mac plus Mac -> Android marker transfer through real system
clipboards.
