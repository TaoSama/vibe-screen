# Nubia P0110 Android UI/UX readiness check

This is a focused Android client UI/UX audit on the connected Nubia device. It
does not close any README acceptance gate and does not claim streaming, latency,
soak, native-pointer, stylus, controller, or Xiaomi 13/fuxi evidence.

## Device

- Manufacturer: nubia
- Model: P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Serial: EP0110PZ0B9110300B
- Physical display: 1264x2800 at 560 dpi

## Commands

```sh
adb -s EP0110PZ0B9110300B shell getprop ro.product.manufacturer
adb -s EP0110PZ0B9110300B shell getprop ro.product.model
adb -s EP0110PZ0B9110300B shell getprop ro.product.device
adb -s EP0110PZ0B9110300B shell getprop ro.build.version.release
adb -s EP0110PZ0B9110300B shell getprop ro.build.version.sdk
adb -s EP0110PZ0B9110300B shell wm size
adb -s EP0110PZ0B9110300B shell wm density
cd baseline/AndroidClient && ./gradlew --no-daemon :app:assembleDebug
adb -s EP0110PZ0B9110300B install -r baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B shell am start -n dev.telemachus.display/.MainActivity
adb -s EP0110PZ0B9110300B exec-out screencap -p > screen-disconnected-portrait.png
adb -s EP0110PZ0B9110300B shell uiautomator dump /sdcard/vibe-screen-ui.xml
adb -s EP0110PZ0B9110300B pull /sdcard/vibe-screen-ui.xml window-disconnected-portrait.xml
adb -s EP0110PZ0B9110300B shell settings put system accelerometer_rotation 0
adb -s EP0110PZ0B9110300B shell settings put system user_rotation 1
adb -s EP0110PZ0B9110300B exec-out screencap -p > screen-disconnected-landscape.png
adb -s EP0110PZ0B9110300B shell uiautomator dump /sdcard/vibe-screen-ui-land.xml
adb -s EP0110PZ0B9110300B pull /sdcard/vibe-screen-ui-land.xml window-disconnected-landscape.xml
adb -s EP0110PZ0B9110300B shell settings put system user_rotation 0
cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest --tests dev.telemachus.display.DisplayCapsulePolicyTest :app:assembleDebug :app:compileDebugAndroidTestKotlin
git diff --check
```

## Observations

- The current worktree debug APK installed successfully and launched
  `dev.telemachus.display/.MainActivity`; see `adb-install.txt`,
  `adb-start.txt`, and `window-focus-after-launch.txt`.
- The disconnected USB screen rendered a centered Vibe Screen connection panel
  with mode choices, `TRY AGAIN`, `Connection details`, and inline
  `DISPLAY SETTINGS`; see `screen-disconnected-portrait.png`.
- `window-disconnected-portrait.xml` reports the inline settings entry as an
  enabled clickable node with content description `Display settings` and bounds
  `[224,2232][1040,2400]`, which is larger than the 48dp accessibility target.
- The final foreground capture (`screen-final-disconnected-portrait.png`, kept
  under its original filename) shows the app in a landscape streaming/control-bar
  state. `window-final-disconnected-portrait.xml` reports the visible chrome as:
  `connectionSecurityGroup` `[875,231][1158,399]`, `displayCapsuleGroup`
  `[1179,231][1463,399]`, `controlHostActionsButton` `[1477,231][1645,399]`,
  `controlSettingsButton` `[1673,231][1841,399]`, and
  `controlDisconnectButton` `[1897,231][2065,399]`. These controls are enabled,
  clickable where expected, and have labels/content descriptions for the visible
  control bar state.
- The earlier explicit rotation command did not produce a landscape-shaped
  disconnected dump on this device session; `screen-disconnected-landscape.png`
  and `window-disconnected-landscape.xml` remained portrait-shaped. The later
  final capture does prove a real landscape control-bar layout, but not a
  disconnected landscape state.
- The display capsule reported `Choose display, currently Built-in Retina
  Display` in the final hierarchy. This run did not perform a host display
  switch and therefore does not prove display-switch acceptance.
- A target-device `ControlBarLayoutInstrumentedTest` run completed on Nubia
  P0110 with `OK (10 tests)`; see `controlbar-instrumentation.txt`. A
  narrower raw `am instrument` retry for
  `ConnectionStateAccessibilityInstrumentedTest#productionConnectionStatesUsePoliteLiveRegions`
  completed successfully on the Nubia device; see
  `accessibility-raw-instrumentation-retry.txt`. A separate retry for the new
  `internetRouteToggleDoesNotAutosizeBelowReadableText` method returned
  `OK (0 tests)` even after reinstalling the current androidTest APK, so that
  method is not claimed as device-executed evidence from this readiness run;
  see `accessibility-route-toggle-raw-instrumentation-final.txt`. A later
  PR272 final rerun on the same Nubia P0110 / pacific / Android 16 / SDK 36
  test APK executed the method as `OK (1 test)` in
  `2026-08-22-nubia-p0110-pr272-final/instrumentation-route-toggle-method-rerun.txt`.
  The instrumented source still compiled with `:app:compileDebugAndroidTestKotlin`;
  no full device instrumentation suite pass is claimed from this readiness run.
- Focused JVM verification and Android test compilation passed for the UI/UX
  changes: `StreamClientProtocolV1IntegrationTest`, `ProtocolV1SessionTest`,
  `MainActivityTerminalGuidanceContractTest`, `DisplayCapsulePolicyTest`,
  `:app:assembleDebug`, and
  `:app:compileDebugAndroidTestKotlin`. `git diff --check` also passed.
- The initial screenshot before launching Vibe Screen was the Android launcher;
  it is kept only to show pre-launch foreground state and is not product UI
  evidence.

## Result

Verdict: readiness evidence only. The device and capture path are usable, the
disconnected portrait UI was directly observed on Nubia P0110/pacific, and a
landscape streaming control bar was captured after the final APK install.
TalkBack traversal, PopupMenu display-dropdown selection, and any README gate
closure remain unproved in this run.
