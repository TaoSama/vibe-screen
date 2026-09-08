# Nubia P0110 no-Host UI/UX current-main rerun

Date: 2026-09-08

Scope: Android no-Host UI/UX instrumentation and focused JVM layout/contract
checks on the connected Nubia P0110 after the PR #676 / PR #681 current-main
refresh. Coverage includes the Android client connection surfaces, USB/LAN and
Internet error guidance, Settings, control bar, file-transfer offer dialogs,
clipboard confirmation dialogs, Internet pairing/profile-import dialogs, QR
scanner layout, connection-state accessibility, Internet control state colors,
gesture preferences, narrow portrait, landscape, and large-text boundaries.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or ADB reverse mapping was created.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    worktree=/Users/luwentao/.codex/worktrees/f7b1/vibe-screen
    head=6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa
    origin_main=6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa
    head_subject=docs: refresh phase0 aggregate after PR 681 (#676)
    date=2026-09-08
    date_time=2026-09-08T07:58:35+0800
    timezone=Asia/Shanghai

This is a docs/evidence refresh from current `origin/main` at capture time; no
Android source change was required.

## Device

Recorded in `metadata/device-identity.txt`:

    serial=<redacted-adb-serial>
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from `baseline/AndroidClient` unless noted. Device commands used the
redacted serial placeholder shown below.

    adb -s <redacted-adb-serial> devices -l
    adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-adb-serial> shell getprop ro.product.model
    adb -s <redacted-adb-serial> shell getprop ro.product.device
    adb -s <redacted-adb-serial> shell getprop ro.build.version.release
    adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-adb-serial> shell wm size
    adb -s <redacted-adb-serial> shell wm density
    adb -s <redacted-adb-serial> shell settings get system font_scale
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest,dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest,dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest
    adb -s <redacted-adb-serial> shell am instrument -w -r -e class <instrumentation-class> dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
    ./gradlew :app:testDebugUnitTest \
      --tests dev.telemachus.display.ConnectionGuidanceTest \
      --tests dev.telemachus.display.ConnectionPanelLayoutPolicyTest \
      --tests dev.telemachus.display.ConnectionSubtitleDisclosurePolicyTest \
      --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest \
      --tests dev.telemachus.display.SettingsDialogLayoutPolicyTest \
      --tests dev.telemachus.display.MainActivitySettingsAccessibilityContractTest \
      --tests dev.telemachus.display.ClientExperienceTest \
      --tests dev.telemachus.display.DesignTokenContrastTest \
      --tests dev.telemachus.display.ManagedPolicyUiAvailabilityPolicyTest \
      --tests dev.telemachus.display.QRScannerAccessibilityContractTest \
      --tests dev.telemachus.display.StatusOverlayLayoutPolicyTest
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Device identity | `metadata/device-identity.txt` | Device matched Nubia P0110 / pacific / Android 16 / API 36. |
| Pre-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-before.txt`, `logs/no-host-boundary-lsof-54321-before-status.txt` | No retained ADB reverse mapping was present; `lsof` was available and returned no local `tcp:54321` listener rows before the retained direct class rerun. |
| Gradle/UTP wrapper instrumentation | `logs/connected-uiux-instrumentation.log`, `retry-single-android-test-results/TEST-P0110 - 16-_app-.xml`, `retry-single-android-test-report/index.html` | Failed closed: Gradle/UTP started the 86-test class list but the instrumentation process crashed after 2 tests. This wrapper result is diagnostic only and is not counted as a passing instrumentation run. |
| Direct same-method diagnostic | `logs/manual-am-instrument-single-narrow.txt` | The method reported by the Gradle wrapper passed when run directly with `am instrument`. |
| Direct per-class UI/UX instrumentation | `logs/manual-class-runs-v4/summary.txt`, `logs/manual-class-runs-v4/*.txt` | Passed 86/86 across 10 retained instrumentation classes. |
| Focused JVM layout/contract checks | `logs/focused-jvm-layout-contracts.log`, `unit-test-results/` | Passed 188/188 across 11 retained JUnit XML reports; Gradle completed with `BUILD SUCCESSFUL`. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-after.txt`, `logs/no-host-boundary-lsof-54321-after-status.txt` | ADB reverse listing stayed empty; `lsof` returned no local `tcp:54321` listener rows after the run. |

The retained direct instrumentation classes are:

- `ConnectionGuidanceLayoutInstrumentedTest` — 17 tests
- `ConnectionStateAccessibilityInstrumentedTest` — 18 tests
- `ControlBarLayoutInstrumentedTest` — 17 tests
- `SettingsDialogLayoutInstrumentedTest` — 16 tests
- `InternetControlStateColorsInstrumentedTest` — 2 tests
- `InternetPairingDialogLayoutInstrumentedTest` — 4 tests
- `QRScannerLayoutInstrumentedTest` — 6 tests
- `GestureShortcutPreferencesInstrumentedTest` — 1 test
- `FileTransferOfferDialogLayoutInstrumentedTest` — 3 tests
- `ClipboardConfirmationDialogLayoutInstrumentedTest` — 2 tests

The retained JVM reports cover connection guidance, connection-panel layout,
connection subtitle disclosure, terminal guidance, Settings layout and
accessibility, client experience copy, design-token contrast, managed-policy UI
availability, QR scanner accessibility, and status-overlay layout contracts.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol
v1 with a product Host. It did not create an ADB reverse mapping. The retained
reverse samples are empty. The retained local `lsof` samples and status records
show `lsof` was available and returned no `tcp:54321` listener rows.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection in a real
product session, receiver approval in a real product session, saved remote
files, final SHA-256 equality, Android ClipboardManager <-> macOS NSPasteboard
E2E, LAN streaming, Internet traversal, video decode, input forwarding,
reconnect timing, latency, soak, Host signing/TCC readiness, native pointer,
stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi
behavior.

## Artifact Notes

UTP binary `device-info.pb`, `test-result.pb`, `cpuinfo`, `meminfo`, and lock
files were omitted because text XML/HTML/log artifacts are sufficient for this
no-Host refresh and avoid retaining extra device identifiers. Instrumentation
screenshots were not retained, so this evidence package uses XML, HTML, and text
logs.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
