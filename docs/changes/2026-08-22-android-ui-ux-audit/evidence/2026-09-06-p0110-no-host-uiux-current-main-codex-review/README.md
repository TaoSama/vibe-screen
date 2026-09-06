# Nubia P0110 no-Host UI/UX current-main Codex review

Date: 2026-09-06

Scope: Android no-Host UI/UX review on the connected Nubia P0110. This pass
started from current `origin/main` in an isolated worktree and looked for
remaining UI/UX issues that would affect the best local Android experience. No
Android production source change was required.

No macOS Vibe Screen, MacHost, or Telemachus GUI was launched. No macOS Screen
Recording, Accessibility, TCC, Keychain, or System Settings flow was touched. No
ADB reverse mapping was created, removed, or modified.

## Source

Recorded in `device-and-preconditions.txt`:

```text
source_head=377516f0e53f05bf4d48e869e7e46e75a2130236
source_branch=android-no-host-uiux-p0110-review
origin_main=377516f0e53f05bf4d48e869e7e46e75a2130236
```

The checked source is current `origin/main` at `377516f0e53f05bf4d48e869e7e46e75a2130236`.

## Device

Recorded in `device-and-preconditions.txt` with the ADB serial redacted:

```text
manufacturer=nubia
model=P0110
device=pacific
android_release=16
android_sdk=36
wm_size=Physical size: 1264x2800
wm_density=Physical density: 560
font_scale=1.0
```

This record is Nubia P0110 / pacific / Android 16 / SDK 36 evidence only. It
must not be reported as Xiaomi 13/fuxi, iOS, HarmonyOS, tablet, or Host-backed
evidence.

## Commands

Run from `baseline/AndroidClient` unless noted. The real run used the fixed
P0110 ADB serial requested for this task.

```bash
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew :app:assembleDebug :app:assembleDebugAndroidTest
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew :app:installDebug :app:installDebugAndroidTest
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest
./gradlew :transport:check :app:testDebugUnitTest \
  --tests dev.telemachus.display.ConnectionPanelLayoutPolicyTest \
  --tests dev.telemachus.display.SettingsDialogLayoutPolicyTest \
  --tests dev.telemachus.display.StatusOverlayLayoutPolicyTest \
  --tests dev.telemachus.display.ConnectionSubtitleDisclosurePolicyTest \
  --tests dev.telemachus.display.DesignTokenContrastTest \
  --tests dev.telemachus.display.MainActivitySettingsAccessibilityContractTest \
  --tests dev.telemachus.display.QRScannerAccessibilityContractTest \
  --tests dev.telemachus.display.ConnectionGuidanceTest \
  --tests dev.telemachus.display.ManagedPolicyUiAvailabilityPolicyTest \
  --tests dev.telemachus.display.ClientExperienceTest
adb -s <redacted-adb-serial> shell am instrument -w -r \
  -e class dev.telemachus.display.SettingsDialogLayoutInstrumentedTest#capturesSustainedUseStatusEvidenceImages \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Debug and androidTest APK build | `gradle-assemble-debug-androidtest.txt` | `BUILD SUCCESSFUL in 631ms` after the initial clean build had already completed successfully |
| APK install | `gradle-install-debug-androidtest.txt` | Debug and androidTest APKs installed on `P0110 - 16`; `BUILD SUCCESSFUL in 6s` |
| Focused P0110 no-Host UI/UX instrumentation | `instrumentation-focused-uiux.txt`, `android-test-results/TEST-P0110-16-app.xml` | `Starting 75 tests on P0110 - 16`; `Finished 75 tests on P0110 - 16`; XML records `tests="75" failures="0" errors="0" skipped="0"` |
| Focused UI/UX JVM and transport checks | `unit-focused-uiux.txt`, `unit-test-results/` | `BUILD SUCCESSFUL in 13s`; retained XMLs cover 105 tests with zero failures/errors/skips across the focused policy/contrast/accessibility classes |
| Settings layout screenshot generation | `instrumentation-settings-screenshot-method.txt`, `generated-layout-screenshots/phase2-readiness/` | `OK (1 test)`; retained generated layout PNGs for portrait and landscape sustained-use/readiness surfaces |
| ADB reverse boundary | `device-and-preconditions.txt`, `final-device-state.txt` | Only the pre-existing unrelated `UsbFfs tcp:8908 tcp:8908` mapping was present before and after; no `tcp:54321` mapping was present or changed |

The focused instrumentation set covers these no-Host Android UI/UX surfaces:

- connection guidance layout for USB, LAN, and Internet modes, including P0110
  portrait/landscape and large-text stress cases
- grouped connection-state accessibility, live-region behavior, contrast, and
  touch-target contracts
- control-bar layout, display selector, transfer-progress row, clipboard status
  row, stats overlay, safe inset, and large-font geometry
- Settings dialog layout, transfer-readiness messaging, unavailable feature
  accessibility, small-tablet width policies, and sustained-use status rendering
- Internet route control colors plus pairing/profile-import dialog readability,
  scrolling, IME-constrained input reachability, sensitive-input handling, and
  production dialog button touch targets
- QR scanner chrome, camera error, invalid QR, and permission-blocked states
- gesture shortcut preference round-trip

The generated Settings screenshots were visually inspected. Portrait uses a
single scrollable column and landscape uses the expected two-column layout; the
visible sustained-use, Clipboard & files, Viewport, and Video controls are
readable with no obvious overlap or clipping in the retained PNGs.

## Manual screenshot note

`manual-launch-main.txt`, `manual-launch-main-unlocked.txt`,
`manual-lockscreen-blocked.png`, and `window-lockscreen-blocked.xml` document a
manual screenshot attempt that was blocked by the device pattern lock.
`dumpsys window` retained `mDreamingLockscreen=true`, and the UI dump shows the
system lockscreen prompt. These files are retained only to explain why no manual
full-device app screenshot is claimed from this run. They are not Android app
UI evidence.

## Findings

No new current-main no-Host Android UI/UX regression was found in the safe test
scope. The only actionable issue encountered was operational: the device was
locked for manual screenshot capture, which prevented a live full-device app
screenshot. The app-side instrumentation and generated layout screenshots still
provided deterministic layout and accessibility evidence without unlocking the
device or involving a Host.

No production code change was made.

## Boundaries

This package supports Android no-Host UI/UX readiness only. It does not prove
Host-backed USB/LAN streaming, real Protocol v1 negotiation, Android
ClipboardManager <-> macOS NSPasteboard E2E, file-transfer product E2E, trusted
LAN streaming, public Internet traversal, video decode, input forwarding,
display switching accepted by a Host, reconnect timing, latency, soak, Host
signing/TCC readiness, native pointer, stylus, controller, iOS behavior,
HarmonyOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi behavior.
