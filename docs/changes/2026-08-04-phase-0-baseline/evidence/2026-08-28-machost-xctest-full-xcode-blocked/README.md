# 2026-08-28 MacHost XCTest full-Xcode readiness: blocked

This record covers README gate owner machost-xctest-full-xcode on a clean
origin/main worktree at commit 27d2b0e493e807ae439fbd43b06b4c2f0ce9c503.

## Verdict

BLOCKED before MacHost XCTest execution. The active Apple developer directory is
Command Line Tools, not full Xcode:

    xcode-select -p: /Library/Developer/CommandLineTools
    xcodebuild -version: xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance

Per docs/testing.md, MacHost XCTest-dependent evidence stays blocked while
Command Line Tools is selected. This record is an environment readiness result,
not a MacHost XCTest assertion failure and not a passing self-test record.

## What was checked

- pgrep -x sfltool || true returned no process IDs before toolchain probing.
- xcode-select -p returned /Library/Developer/CommandLineTools.
- xcodebuild -version exited nonzero because the active developer directory is
  Command Line Tools.
- make baseline-macos-xctest-preflight ran the repository preflight and exited
  2, writing xctest-toolchain.txt with Status: FAIL.

## What was not run

- make baseline-macos-build
- make baseline-macos-self-test
- make baseline-macos-test

Those commands remain pending for a machine where xcode-select -p resolves to a
full Xcode developer directory and xcodebuild -version succeeds.

## Safety boundary

This run did not change xcode-select, build or install the Host, modify TCC,
touch Android devices, or run login-item diagnostics. It did not invoke
--include-login-item-diagnostic, --inspect-login-items, or --probe-login-items.

## Artifacts

- commands.txt: commands used and observed outcomes.
- environment.txt: repository, OS, architecture, and toolchain context.
- xctest-toolchain.txt: repository-generated fail-closed XCTest preflight
  report.
- readiness.json: machine-readable blocked readiness summary.
- SHA256SUMS: artifact checksums.
