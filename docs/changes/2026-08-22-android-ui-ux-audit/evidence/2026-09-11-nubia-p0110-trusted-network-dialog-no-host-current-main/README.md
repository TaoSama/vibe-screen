# 2026-09-11 Nubia P0110 Trusted Network Dialog no-Host Refresh

## Scope

This evidence covers the Android trusted-network confirmation dialog Material rewrite on current main-derived source. The change replaces the platform message dialog path with a Material dialog using a scrollable custom message layout, keeps the dialog title in the Material chrome, and verifies large-font/narrow-viewport behavior on a Nubia P0110 no-Host run.

## No-Host boundary

No macOS Host was started or installed. No signing, TCC, Screen Recording, Accessibility, Microphone, Keychain, System Settings, or Host listener setup was performed. The only adb reverse command used was the read-only adb -s <target-nubia-serial> reverse --list.

Boundary evidence:

| Check | Expected | Status file | Result |
| --- | --- | --- | --- |
| lsof -nP -iTCP:54321 -sTCP:LISTEN before | exit 1 | logs/no-host-boundary-lsof-54321-before.status | pass |
| adb -s <target-nubia-serial> reverse --list before | empty/newline only | logs/no-host-boundary-adb-reverse-before.status | pass |
| lsof -nP -iTCP:54321 -sTCP:LISTEN after | exit 1 | logs/no-host-boundary-lsof-54321-after.status | pass |
| adb -s <target-nubia-serial> reverse --list after | empty/newline only | logs/no-host-boundary-adb-reverse-after.status | pass |

## Source

See metadata/source-provenance.txt.

## Device

See metadata/device-identity.txt. This is Nubia P0110 / pacific / Android 16 / API 36 evidence only and must not be reported as Xiaomi 13/fuxi evidence. The forbidden serial <forbidden-nubia-serial> was not used.

## Results

| Gate | Artifact | Result |
| --- | --- | --- |
| Source guard | logs/source-guard.txt | pass: 3 target tests, no forbidden test patterns, builder title/view path present |
| Diff hygiene | logs/git-diff-check.txt | pass |
| Focused JVM contracts | logs/gradle-focused-unit-tests.log | pass |
| androidTest compile | logs/gradle-compile-debug-androidtest-kotlin.log | pass |
| P0110 instrumentation | logs/gradle-connected-trusted-network-dialog.log | pass: Starting 3 tests on P0110 - 16 and Finished 3 tests on P0110 - 16 |
| No-Host boundary | logs/no-host-boundary-*.txt, logs/no-host-boundary-*.status | pass |
| Checksums | SHA256SUMS, logs/sha256-check.txt | pass |

## Artifact notes

The first local target instrumentation attempt exposed a large-font line-width failure and an overly strict constrained-height threshold. The retained passing log in this directory is from the fixed layout/copy and final 3-test class.
