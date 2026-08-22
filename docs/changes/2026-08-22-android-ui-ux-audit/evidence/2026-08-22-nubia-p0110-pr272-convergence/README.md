# Nubia P0110 PR272 display-selection convergence evidence

This evidence records the follow-up convergence pass for PR #272 after reviewing
the overlapping Android display-selection pending-state work. The device was
locked with `/tmp/vibe-screen-device-android.lock`, and every Android command
used explicit serial targeting with `adb -s EP0110PZ0B9110300B`.

## Device

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36
- Serial: EP0110PZ0B9110300B
- Physical size: 1264x2800
- Physical density: 560
- Power state during the run: AC powered, 100% battery

Raw identity, install, and instrumentation output is saved in
`control-bar-instrumentation.log`.

## UX Decision

PR #272 is now the recommended merge vehicle. It absorbs the necessary
display-selection UX from the competing pending-state branch while preserving
the existing PR #272 improvements and Nubia evidence:

- The active display label is not committed until the Protocol v1 video
  configuration is accepted by the decoder.
- While the switch is pending, the capsule shows `Switching to <display>...`
  and the display selector remains visible but disabled.
- Host rejection, unsupported video configuration, and decoder rejection keep
  the previous active display and emit a user-visible failure toast.
- New stream id and display geometry from a runtime switch are staged until
  decoder acceptance, so rejection rolls back input/media targets to the last
  confirmed stream.
- Video-preference changes queued while a display switch is pending are dropped
  if that switch is rejected, so a later unrelated video configuration cannot
  apply stale settings from the failed switch window.
- Pending display state is cleared on disconnect and protocol error.

The overlapping pending-state PR should be closed as superseded once this
branch is accepted, because the same UX is integrated here with the broader
Nubia P0110/pacific evidence package.

## Focused Verification

Local Android gates run for this convergence pass:

```sh
cd baseline/AndroidClient
./gradlew --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.DisplayCapsulePolicyTest \
  --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest \
  --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest
cd ../..
make baseline-android-check
git diff --check
git diff --check origin/main...HEAD
cd baseline/AndroidClient
adb -s EP0110PZ0B9110300B install -r app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s EP0110PZ0B9110300B shell am instrument -w -r \
  -e class dev.telemachus.display.ControlBarLayoutInstrumentedTest \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

Observed device result on nubia P0110 / pacific / Android 16 / SDK 36:

```text
ControlBarLayoutInstrumentedTest: OK (11 tests)
```

The 11-test run includes
`productionBinderDisablesDisplaySelectorWhileSwitchIsPending`, which verifies the
pending capsule label, disabled selector state, and accessibility description
after reinstalling the current debug and androidTest APKs.

The JVM protocol tests also cover host rejection, unsupported video config,
decoder rejection, and the rollback invariant that post-rejection touch targets
continue to use the previous display id and stream id.
The 2026-08-22 follow-up run also covers the settings/display-switch
concurrency regression with
`preferenceChangeDuringRejectedDisplaySelectionIsNotFlushedLater`. This was a
local protocol/JVM verification; it does not add a new real-device claim beyond
the Nubia instrumentation evidence above.

## Boundaries

This directory proves the focused display-selection pending UI and control-bar
layout behavior on nubia P0110 / pacific / Android 16 / SDK 36. It does not
claim a complete automated real-Host dropdown acceptance run for every failure
mode, and it does not close README acceptance gates for latency, soak, LAN,
native pointer, stylus, controller, iOS, or Xiaomi/fuxi evidence.
