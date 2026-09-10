# Nubia P0110 Trusted-Network Dialog No-Host Evidence

Date: 2026-09-11, Asia/Shanghai.

Scope: Android trusted-network confirmation dialog refresh on current main. This run covers the Material title plus custom body layout, MainActivity immersive dialog presentation path, narrow and large-font readability, restricted landscape scrollability, button touch/readability checks, TalkBack semantics, visible text/action overlap checks, and positive-only confirmation callback behavior.

This evidence uses a manual raw am instrument invocation for the focused instrumentation class. It does not use Gradle connectedDebugAndroidTest, and therefore no Gradle connected-test XML or HTML report is represented here.

## Source

| Field | Value |
| --- | --- |
| Repository | git@github.com:TaoSama/vibe-screen.git |
| Branch | codex/trusted-network-material-dialog |
| Base commit | 035fca2fe61cb1a3879ffcaf6fd811b6df635967 |
| origin/main | 035fca2fe61cb1a3879ffcaf6fd811b6df635967 |
| Base subject | Fix settings video option group layout (#766) |
| Validated tree | Local worktree changes on top of base commit |

## Device

| Field | Value |
| --- | --- |
| Serial | <redacted-adb-serial> |
| Manufacturer | nubia |
| Model | P0110 |
| Device | pacific |
| Android release | 16 |
| SDK | 36 |
| Display size | Physical size: 1264x2800 |
| Density | Physical density: 560 |
| Font scale | 1.0 |

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Source sanity | logs/static-sanity-after-final-source.txt | Passed: builder setTitle present, layout has no title id, contract has two setTitle assertions, instrumentation has 4 tests and performClick/visibleBounds/Rect.intersects coverage. |
| Focused JVM contracts | logs/focused-contract-jvm.log; unit-test-results/*.xml | Passed: BUILD SUCCESSFUL in 44s; WirelessTabControllerContractTest 7/7, MainActivityTerminalGuidanceContractTest 72/72. |
| APK build | logs/assemble-debug-and-android-test.log | Passed: assembleDebug and assembleDebugAndroidTest BUILD SUCCESSFUL in 16s. |
| Device identity | metadata/device-identity.txt; logs/adb-devices.txt | Passed: target Nubia P0110 / pacific / Android 16 / API 36 device online. |
| No-Host boundary before tests | logs/adb-reverse-before-tests.txt; logs/adb-reverse-before-tests-status.txt; logs/no-host-boundary-lsof-54321-before.txt; logs/no-host-boundary-lsof-54321-before-status.txt | Passed: adb reverse list empty with status 0; tcp:54321 listener absent with lsof status 1. |
| Manual raw instrumentation | logs/am-instrument-trusted-network-dialog.log; android-test-results/trusted-network-dialog-am-instrument.txt | Passed: TrustedNetworkDialogLayoutInstrumentedTest OK (4 tests), INSTRUMENTATION_CODE: -1. |
| No-Host boundary after tests | logs/adb-reverse-after-tests.txt; logs/adb-reverse-after-tests-status.txt; logs/no-host-boundary-lsof-54321-after.txt; logs/no-host-boundary-lsof-54321-after-status.txt | Passed: adb reverse list still empty with status 0; tcp:54321 listener still absent with lsof status 1. |

## No-Host Boundaries

- The macOS Host was not started, installed, replaced, re-signed, or launched.
- TCC, Screen Recording, Accessibility, Microphone, Keychain, signing, and Host provenance state were not touched.
- No adb reverse tcp:54321 tcp:54321 mapping was created.
- The retained device result is raw am instrument output, not a Gradle connectedDebugAndroidTest run.

This evidence does not prove Host-backed LAN streaming, USB streaming, Internet traversal, video decode, input forwarding, clipboard transfer, or file transfer.

## Artifacts

- logs/focused-contract-jvm.log: focused JVM contract command output.
- unit-test-results/*.xml: focused JVM JUnit XML outputs.
- logs/assemble-debug-and-android-test.log: APK build output for debug and androidTest APKs.
- logs/am-instrument-trusted-network-dialog.log and android-test-results/trusted-network-dialog-am-instrument.txt: raw manual instrumentation output.
- metadata/no-host-boundary.txt: explicit no-Host boundary statement.
- metadata/artifact-redaction.txt: redaction policy.

## Integrity

Verify retained artifacts from this directory with:

shasum -a 256 -c SHA256SUMS
