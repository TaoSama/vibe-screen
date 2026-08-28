# Nubia P0110 PR272 final Android UI/UX evidence

This evidence records a final focused Android UI/UX pass for PR #272 on the connected Nubia device. Every device command used explicit serial targeting with `adb -s <redacted-adb-serial>`.

## Device

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36
- Serial: <redacted-adb-serial>
- Physical size: 1264x2800
- Physical density: 560
- Power state: AC powered, 100% battery during the run
- Installed packages: `dev.telemachus.display` and `dev.telemachus.display.test`
- USB precondition: `UsbFfs tcp:54321 tcp:54321` present in `adb reverse --list`

See `device-and-preconditions.txt` and `commands.txt` for the raw identity and setup output.

## Build, Install, And Test Commands

```sh
cd baseline/AndroidClient
./gradlew --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
adb -s <redacted-adb-serial> install -r app/build/outputs/apk/debug/app-debug.apk
adb -s <redacted-adb-serial> install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s <redacted-adb-serial> shell am instrument -w -r -e class dev.telemachus.display.ControlBarLayoutInstrumentedTest dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s <redacted-adb-serial> shell am instrument -w -r -e class dev.telemachus.display.SettingsDialogLayoutInstrumentedTest dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s <redacted-adb-serial> shell am instrument -w -r -e class dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
./gradlew --no-daemon :app:testDebugUnitTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest --tests dev.telemachus.display.DisplayCapsulePolicyTest :app:compileDebugAndroidTestKotlin
```

Raw outputs are saved as `assemble-debug-and-androidtest.txt`, `adb-install-debug.txt`, `adb-install-androidtest.txt`, `instrumentation-controlbar-rerun.txt`, `instrumentation-settings-rerun.txt`, `instrumentation-connection-accessibility-rerun.txt`, `instrumentation-route-toggle-method-rerun.txt`, and `gradle-focused-final.txt`.

## Passing Evidence

The reinstalled device test APK passed the focused Android UI/UX instrumentation suites on nubia P0110 / pacific / Android 16 / SDK 36:

```text
ControlBarLayoutInstrumentedTest: OK (10 tests)
SettingsDialogLayoutInstrumentedTest: OK (7 tests)
ConnectionStateAccessibilityInstrumentedTest: OK (12 tests)
ConnectionStateAccessibilityInstrumentedTest#internetRouteToggleDoesNotAutosizeBelowReadableText: OK (1 test)
```

These runs cover the control capsule layout and reveal action, hidden display-selector boundaries, control hit targets, settings dialog responsive option groups, sustained-use/settings controls, connection-state live region behavior, mode toggle readable text, Internet route-toggle readable text, connection checklist state, and connected status announcement behavior.

The targeted route-toggle rerun supersedes the earlier `2026-08-22-nubia-p0110-ui-ux-readiness/accessibility-route-toggle-raw-instrumentation-final.txt` selector attempt, which returned `OK (0 tests)` and remains intentionally not claimed as passing evidence in that older readiness directory.

## Manual Screenshots And UI Dumps

- `manual-disconnected-portrait.png` / `window-disconnected-portrait.xml`: portrait disconnected USB page with Vibe Screen branding, mode toggles, retry, connection details, and Display Settings.
- `manual-connection-details-portrait.png` / `window-connection-details-portrait.xml`: expanded connection details and actionable USB error guidance. The visible error is `Mac app unavailable` with recovery text to open the Mac app, keep USB attached, authorize debugging, and run `adb reverse tcp:54321 tcp:54321`.
- `manual-settings-dialog-portrait.png` / `window-settings-dialog-portrait.xml`: portrait Display settings dialog with Show Stats, Sustained use, Viewport, scale, and rotation controls.
- `manual-settings-dialog-portrait-scrolled.png` / `window-settings-dialog-portrait-scrolled.xml`: scrolled settings dialog showing lower video controls.
- `manual-disconnected-w632dp-density-only-v2.png` / `window-disconnected-w632dp-density-only-v2.xml`: density-only 632dp-wide disconnected layout. This used `wm density 320` and was restored afterward.
- `manual-settings-dialog-w632dp-density-only-v3.png` / `window-settings-dialog-w632dp-density-only-v3.xml`: density-only 632dp-wide settings dialog with four-across rotation options and visible video controls.
- `manual-disconnected-landscape-cmd-window.png` / `window-disconnected-landscape-cmd-window.xml`: attempted system rotation capture. UIAutomator still reported `hierarchy rotation="0"`, so it is retained only as a rotation-attempt record.
- `permission-controller-before.png` / `window-permission-controller-before.xml`: external Nubia permission-controller prompt that blocked an earlier instrumentation attempt. It is system UI evidence, not Vibe Screen product UI evidence.

`wm-after-restore-manual.txt`, `wm-after-density-only-restore.txt`, `wm-after-w632dp-v2-restore.txt`, and `wm-after-landscape-restore.txt` confirm the device returned to physical 1264x2800 at 560 dpi after temporary overrides.

## Touch Target Summary

`touch-target-summary-final.txt` computes UIAutomator bounds in dp. The visible core controls all met or exceeded the 48dp target in the proved states:

```text
portrait disconnected:
modeUSB/modeWireless/modeInternet: >= 78.3x48.0dp
connectButton: 233.1x56.0dp
showAdvanced: 233.1x48.0dp
connectionSettingsButton: 233.1x48.0dp

portrait settings dialog:
showStatsSwitch: 48.0x48.0dp
scaleFitButton/scaleFillButton: 117.1x48.0dp
rotationFollow/90/180 visible buttons: >= 233.1x48.0dp

w632dp density-only disconnected:
mode toggles: >= 168.5x48.0dp
connectButton: 504.0x56.0dp
showAdvanced: 504.0x48.0dp
connectionSettingsButton: 504.0x48.0dp

w632dp density-only settings:
showStatsSwitch: 48.0x48.0dp
scaleFitButton/scaleFillButton: 244.5x48.0dp
rotation buttons: >= 122.5x48.0dp
visible video quality/FPS buttons: >= 122.5x48.0dp
```

The first portrait settings screenshot shows the lower `270°` row partially clipped by the initial viewport; the scrolled capture demonstrates the dialog remains scrollable and lower video controls are reachable. The 632dp density-only settings capture shows the full rotation row meeting 48dp.

## Boundaries

This final evidence was collected only on nubia P0110 / pacific / Android 16 / SDK 36.

This directory does not close any README acceptance gate. It supports passing instrumentation for control capsule, settings, connection-state accessibility, and touch-target/accessibility behavior only.

Display dropdown and display selection are not claimed as passing final evidence from this directory. The sibling `2026-08-22-nubia-p0110-pr272-e2e` directory contains scoped real-Host display-selection event-order evidence and visual dropdown/open-state artifacts, but not a passing automated dropdown device test.

Disconnect completion is not claimed here. Prior evidence covers the disconnect confirmation dialog, not the final post-confirm disconnected-state completion.

600dp behavior here is a reversible density-only layout check on the same Nubia P0110, not physical tablet acceptance. The earlier size-plus-density override produced external launcher/system UI artifacts, so those files are retained only as failed-attempt evidence.

Physical orientation rotation is not proven here. Both `settings put system user_rotation 1` and `cmd window set-user-rotation lock 1` attempts left the captured hierarchy at `rotation="0"`; `cmd window set-user-rotation` returned `Unknown command` on this Android 16 build.

Error handling is partially covered through the visible USB recovery surface plus accessibility/live-region/failure-highlight tests. This is not a complete error-state walkthrough for every transport.

This evidence does not claim latency, soak, LAN, native-pointer, stylus, controller, TalkBack traversal, iOS, or broader product acceptance.

## PR Readiness Recommendation

For the narrow PR #272 code change, the branch has stronger Nubia P0110 device evidence for the core UI/accessibility surfaces and the local focused Android gates pass. After the follow-up convergence pass, PR #272 is the recommended merge vehicle and the overlapping pending-state PR should be closed as superseded once this branch is accepted. This recommendation remains scoped to the evidence boundary above and does not close any README acceptance gate.
