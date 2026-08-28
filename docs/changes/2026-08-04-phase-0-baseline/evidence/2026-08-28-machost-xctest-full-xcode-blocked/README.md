# 2026-08-28 MacHost XCTest full-Xcode readiness: blocked

This record covers README gate owner machost-xctest-full-xcode on a clean
origin/main worktree at commit 27d2b0e493e807ae439fbd43b06b4c2f0ce9c503.

## Verdict

BLOCKED for MacHost XCTest execution. The active Apple developer directory is
Command Line Tools, not full Xcode:

    xcode-select -p: /Library/Developer/CommandLineTools
    xcodebuild -version: xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance

Per docs/testing.md, MacHost XCTest-dependent evidence stays blocked while
Command Line Tools is selected. This record is an environment readiness result,
not a MacHost XCTest assertion failure and not a passing self-test record.

`baseline-macos-build` and `baseline-macos-self-test` do not depend on the
XCTest preflight in the Makefile and were run successfully under Command Line
Tools. Only `baseline-macos-test` (which depends on
`baseline-macos-xctest-preflight`) remains blocked.

## What was checked

- pgrep -x sfltool || true returned no process IDs before toolchain probing.
- xcode-select -p returned /Library/Developer/CommandLineTools.
- xcodebuild -version exited nonzero because the active developer directory is
  Command Line Tools.
- make baseline-macos-xctest-preflight ran the repository preflight and exited
  2, writing xctest-toolchain.txt with Status: FAIL.
- make baseline-macos-build succeeded (exit 0) with Command Line Tools.
  baseline-macos-build has no Makefile dependency on the XCTest preflight.
- make baseline-macos-self-test succeeded (exit 0) with Command Line Tools.
  baseline-macos-self-test depends on baseline-macos-build, not on the XCTest
  preflight.

## What was not run

- make baseline-macos-test

`baseline-macos-test` depends on `baseline-macos-xctest-preflight` in the
Makefile and remains pending for a machine where xcode-select -p resolves to a
full Xcode developer directory and xcodebuild -version succeeds.

## Safety boundary

This run did not change xcode-select, install the Host, modify TCC, touch
Android devices, or run login-item diagnostics. It did not invoke
--include-login-item-diagnostic, --inspect-login-items, or --probe-login-items.

## Artifacts

- commands.txt: commands used and observed outcomes.
- environment.txt: repository, OS, architecture, and toolchain context.
- xctest-toolchain.txt: repository-generated fail-closed XCTest preflight
  report.
- readiness.json: machine-readable blocked readiness summary.
- SHA256SUMS: artifact checksums.
