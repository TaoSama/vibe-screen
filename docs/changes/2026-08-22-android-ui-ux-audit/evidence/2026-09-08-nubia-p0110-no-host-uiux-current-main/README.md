# Nubia P0110 no-Host UI/UX current-main refresh

Date: 2026-09-08

Scope: Android no-Host UI/UX instrumentation and focused JVM layout/contract
checks on the connected Nubia P0110. Coverage includes the Android client
connection surfaces, USB/LAN/Internet error guidance, Settings, control bar,
file-transfer offer and outgoing preflight dialogs, clipboard confirmation
dialogs, Internet pairing/profile-import dialogs, QR scanner layout, connection
state accessibility, Internet control state colors, gesture preference
round-trip, narrow portrait, landscape, large text, and compact window
boundaries.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    branch=codex/android-nohost-uiux-p0110
    commit=f35e37550d6c091f34cba58684fc2eab05ee685f
    origin_main=f35e37550d6c091f34cba58684fc2eab05ee685f
    date=2026-09-08
    date_timezone=Asia/Shanghai
    xml_report_timestamps=Gradle/UTP local timestamps without timezone offset; 2026-09-07T16:45:43 and 2026-09-07T16:51:34 correspond to 2026-09-08T00:45:43+08:00 and 2026-09-08T00:51:34+08:00 capture time.

This is a docs/evidence refresh from current `origin/main`; no Android source
change was required.

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

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from `baseline/AndroidClient` unless noted.

    adb -s <redacted-adb-serial> devices -l
    adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-adb-serial> shell getprop ro.product.model
    adb -s <redacted-adb-serial> shell getprop ro.product.device
    adb -s <redacted-adb-serial> shell getprop ro.build.version.release
    adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-adb-serial> shell wm size
    adb -s <redacted-adb-serial> shell wm density
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest,dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest,dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest
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
| Pre-run no-Host boundary | `logs/adb-reverse-before-tests.txt` | `adb reverse --list` was empty; no `tcp:54321` mapping was present. |
| P0110 no-Host UI/UX instrumentation | `android-test-results/TEST-P0110 - 16-_app-.xml` | `tests=86`, `failures=0`, `errors=0`, `skipped=0`. |
| Instrumentation text/proto result | `android-test-results/test-result.textproto` | UTP retained the completed P0110 run metadata. |
| Instrumentation HTML report | `android-test-report/index.html` | Gradle connected-test report copied for review. |
| Focused JVM layout/contract checks | `unit-test-results/` | 11 JUnit XML reports retained; the Gradle run completed with `BUILD SUCCESSFUL`. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321.txt`, `logs/no-host-boundary-lsof-54321-status.txt` | `adb reverse --list` stayed empty; `lsof` was available and returned no local `tcp:54321` listener rows. |

The retained instrumentation classes are:

- `ConnectionGuidanceLayoutInstrumentedTest`
- `ConnectionStateAccessibilityInstrumentedTest`
- `ControlBarLayoutInstrumentedTest`
- `SettingsDialogLayoutInstrumentedTest`
- `InternetControlStateColorsInstrumentedTest`
- `InternetPairingDialogLayoutInstrumentedTest`
- `QRScannerLayoutInstrumentedTest`
- `GestureShortcutPreferencesInstrumentedTest`
- `FileTransferOfferDialogLayoutInstrumentedTest`
- `ClipboardConfirmationDialogLayoutInstrumentedTest`

The retained JVM reports cover connection guidance, connection-panel layout,
connection subtitle disclosure, terminal guidance, Settings layout and
accessibility, client experience copy, design-token contrast, managed-policy UI
availability, QR scanner accessibility, and status-overlay layout contracts.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol
v1 with a product Host. It did not create an `adb reverse tcp:54321 tcp:54321`
mapping. The retained pre-run and post-run reverse samples are empty. The
retained local `lsof` sample and status record show `lsof` was available and
returned no `tcp:54321` listener rows.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection in a real
product session, receiver approval in a real product session, saved remote
files, final SHA-256 equality, Android ClipboardManager <-> macOS NSPasteboard
E2E, LAN streaming, Internet traversal, video decode, input forwarding,
reconnect timing, latency, soak, Host signing/TCC readiness, native pointer,
stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi
behavior.

## Artifact Notes

UTP binary `device-info.pb`, `test-result.pb`, `cpuinfo`, and `meminfo` were
omitted because text XML/HTML/log artifacts are sufficient for this no-Host
refresh and avoid retaining extra device identifiers. Instrumentation screenshot
files were not present in the app external or package-private files directories
after this run, so the retained evidence uses XML, HTML, and text logs.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
