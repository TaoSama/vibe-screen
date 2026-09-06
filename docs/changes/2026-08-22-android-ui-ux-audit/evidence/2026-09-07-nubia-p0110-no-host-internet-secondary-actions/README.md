# Nubia P0110 no-Host Internet secondary-actions layout refresh

Date: 2026-09-07

Scope: Android no-Host UI/layout validation for the Internet secondary action
row on the connected Nubia P0110. This refresh covers large-text stacking,
default-font horizontal layout, hidden Settings/Disconnect visibility mixes,
and the surrounding no-Host UI/UX regression set. No macOS Vibe Screen,
MacHost, or Telemachus GUI was launched. No `swift run`, macOS TCC, Screen
Recording, Accessibility, Keychain, System Settings, signing/re-signing, or
`adb reverse tcp:54321` creation/removal was used.

## Source

Recorded in `metadata/source-provenance.txt`:

```text
repository=TaoSama/vibe-screen
evidence_branch=codex/android-no-host-uiux-p0110-20260907
base_commit=ac804cb98adbb061cd01e8f6a9db93adb78ca9c5
origin_main_at_test=ac804cb98adbb061cd01e8f6a9db93adb78ca9c5
base_subject=Add peripheral input diagnostics and pointer guards (#651)
```

The evidence was collected from the feature worktree after the Android UI/test
diff in this branch was applied. `working_tree_diff_sha256` in the source
provenance file records the non-evidence source diff digest at collection time.

## Device

Recorded in `metadata/device-identity.txt` with the ADB serial retained in the
raw command output:

```text
manufacturer=nubia
model=P0110
device=pacific
release=16
sdk=36
wm_size=Physical size: 1264x2800
wm_density=Physical density: 560
```

This record is Nubia P0110 / pacific / Android 16 / SDK 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from `baseline/AndroidClient` unless noted.

```bash
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests dev.telemachus.display.ConnectionPanelLayoutPolicyTest \
  --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest
./gradlew --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
ANDROID_SERIAL=EP0110PZ0B9110300B ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest
ANDROID_SERIAL=EP0110PZ0B9110300B ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest
```

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Focused JVM layout/source contracts | `logs/gradle-jvm-focused.log`, `unit-test-results/` | `ConnectionPanelLayoutPolicyTest`: 19 tests, 0 failures; `MainActivityTerminalGuidanceContractTest`: 66 tests, 0 failures; `BUILD SUCCESSFUL in 4s` |
| Debug and androidTest APK build | `logs/gradle-assemble-debug-androidtest.log` | `BUILD SUCCESSFUL in 8s` |
| P0110 focused connection-guidance instrumentation | `logs/connected-guidance-instrumentation.log` | `Starting 17 tests on P0110 - 16`; `Finished 17 tests on P0110 - 16`; `BUILD SUCCESSFUL in 17s` |
| P0110 wider no-Host UI/UX instrumentation | `logs/connected-uiux-instrumentation.log` | `Starting 80 tests on P0110 - 16`; `Finished 80 tests on P0110 - 16`; `BUILD SUCCESSFUL in 4m 53s` |
| JUnit XML report | `android-test-results/TEST-P0110 - 16-_app-.xml` | `tests="80" failures="0" errors="0" skipped="0"` |
| HTML report | `android-test-report/index.html` | Gradle connected-test report copied for review |
| no-Host boundary | `logs/no-host-boundary.txt`, `logs/adb-reverse-after-tests.txt` | No local TCP `54321` listener was retained; `adb reverse --list` showed only `UsbFfs tcp:8908 tcp:8908` |

The focused layout additions cover:

- default-font Internet secondary actions staying side-by-side;
- large-font, single-column Internet secondary actions stacking to full width;
- connected-state `[Disconnect, Revoke]` visibility without a leading gap in
  both horizontal and vertical layouts;
- disconnected-state `[Settings, Revoke]` visibility without a leading gap at
  large text scale.

The wider retained run also covers connection guidance, connection-state
accessibility, control-bar geometry, Settings dialog layout, Internet action
colors, Internet pairing/import dialogs, QR scanner layout, and gesture shortcut
preferences in no-Host instrumentation.

## No-Host Boundaries

This run did not start or require a macOS Host, did not negotiate Protocol v1,
and did not create or remove any ADB reverse mapping. The only retained
`adb reverse --list` entry after the run is the pre-existing unrelated
`UsbFfs tcp:8908 tcp:8908`; no `tcp:54321` mapping was present.

This package does not prove Host-backed bytes landing, Android ClipboardManager
<-> macOS NSPasteboard E2E, real file-transfer E2E, LAN streaming, real Internet
pairing or traversal, QR/profile transfer between devices, video decode, input
forwarding, reconnect timing, latency, soak, Host signing/TCC readiness, native
pointer, stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi
13/fuxi behavior.

## Verification

Run the checksum verification from this evidence directory:

```bash
shasum -a 256 -c SHA256SUMS
```
