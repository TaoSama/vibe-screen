# Nubia P0110 no-Host UI/UX after-782 current-main refresh

Date: 2026-09-14

Scope: Android no-Host UI/UX instrumentation and focused JVM contracts on the connected Nubia P0110 after
current `origin/main` advanced to `9c32bc5da1e24edc511be509ad05aac732570dfb` /
PR #782 (`fix(android): keep dialog actions readable (#782)`). Coverage encompasses
135 UI/UX instrumentation tests across 11 test classes, covering disconnected
connection surfaces, USB/LAN and Internet error guidance, Settings dialog
accessibility and choice wrapping, control bar, file-transfer offer and outgoing
preflight dialogs, clipboard confirmation dialogs, Internet pairing and profile-import
dialogs, trusted network confirmation dialogs, QR scanner layout, connection-state
accessibility, Internet control state colors, gesture preferences, narrow portrait,
landscape, and large-text boundaries. Eight focused JVM classes add 129 tests
for clipboard/file-transfer system boundaries, transfer readiness, Settings
layout/accessibility, contrast, wireless dialog ownership, and terminal
guidance contracts.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used. The only reverse command used was read-only `adb reverse --list` to
prove no reverse mapping was present.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    worktree=<workspace>
    branch=codex/android-nohost-uiux-refresh
    base_head=9c32bc5da1e24edc511be509ad05aac732570dfb
    origin_main=9c32bc5da1e24edc511be509ad05aac732570dfb
    base_subject=fix(android): keep dialog actions readable (#782)
    date=2026-09-14
    timezone=Asia/Shanghai
    local_change=Adds a fail-closed wake/keyguard precondition to the visible notices-dialog instrumentation test, then refreshes Nubia P0110 no-Host Android UI/UX instrumentation evidence and eight focused JVM contract classes after current main advanced through PR #782.

This evidence is captured from a branch created from current `origin/main` at
the source commit above. The accepted APK includes the local instrumentation-only
wake/keyguard precondition described by `local_change`; no production Android
source was changed.

## Device

The online serial was confirmed with `adb devices -l` before running tests and
matched the connected Nubia device. Retained artifacts redact the serial.

Recorded in `metadata/device-identity.txt`:

    serial=<redacted-adb-serial>
    actual_serial_verified_online=yes
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    fingerprint=nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Diagnostic vs Accepted Runs

During the initial execution of the 135-test connected instrumentation suite,
the device screen transitioned into a dozing power state (`mWakefulness=Dozing`),
causing `dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest > openSourceLicensesButtonOpensPackagedNoticesDialog`
to fail (134/135 passed, 1 failure).

- **Diagnostic Run (Not Accepted)**: Retained strictly for transparency and
  diagnostic record in `logs/connected-no-host-uiux-instrumentation.failed-diagnostic.log`.
  It is explicitly **not** an accepted run.
- **Accepted Run**: The instrumentation-only `ensureInteractiveDevice` helper
  synchronously issued `KEYCODE_WAKEUP` and `wm dismiss-keyguard` through
  `UiAutomation` before the visible notices-dialog assertion, then the full
  135-test suite was re-executed. These were in-device test-shell operations,
  not separate host `adb shell` commands. The accepted run completed with **135/135 tests
  passing (0 failures, 0 errors, 0 skipped)**, recorded in the accepted JUnit
  XML (`android-test-results/TEST-P0110-16-app.xml`), UTP log, HTML report, and
  Gradle runner log.

## Commands

Commands were recorded from the repository root unless the command uses an
explicit subshell under `baseline/AndroidClient`. Device commands used the
redacted serial placeholder. The exact command list is retained in `commands.txt`.

    git status --short --branch
    git rev-parse HEAD
    git rev-parse origin/main

    adb devices -l
    adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-adb-serial> shell getprop ro.product.model
    adb -s <redacted-adb-serial> shell getprop ro.product.device
    adb -s <redacted-adb-serial> shell getprop ro.build.version.release
    adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-adb-serial> shell getprop ro.build.fingerprint
    adb -s <redacted-adb-serial> shell wm size
    adb -s <redacted-adb-serial> shell wm density
    adb -s <redacted-adb-serial> shell settings get system font_scale
    adb -s <redacted-adb-serial> shell dumpsys power | grep -E "mWakefulness="
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN

    (cd baseline/AndroidClient && ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon --console=plain :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest,dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest,dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest,dev.telemachus.display.TrustedNetworkDialogLayoutInstrumentedTest')

    (cd baseline/AndroidClient && ./gradlew --no-daemon --console=plain :app:testDebugUnitTest --tests dev.telemachus.display.MainActivityClipboardSystemBoundaryContractTest --tests dev.telemachus.display.MainActivityFileTransferSystemBoundaryContractTest --tests dev.telemachus.display.MainActivityTransferReadinessContractTest --tests dev.telemachus.display.SettingsDialogLayoutPolicyTest --tests dev.telemachus.display.MainActivitySettingsAccessibilityContractTest --tests dev.telemachus.display.DesignTokenContrastTest --tests dev.telemachus.display.WirelessTabControllerContractTest --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest)

    adb -s <redacted-adb-serial> reverse --list
    lsof -nP -iTCP:54321 -sTCP:LISTEN

    (cd "$EVID" && shasum -a 256 -c SHA256SUMS)

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Device identity | `metadata/device-identity.txt`, `logs/device-precheck.txt` | Device matched Nubia P0110 / pacific / Android 16 / API 36 with 1264x2800 at density 560, font scale 1.0. |
| Pre-run no-Host boundary | `logs/adb-reverse-before-tests.txt`, `logs/no-host-boundary-lsof-54321-before.txt`, `logs/no-host-boundary-lsof-54321-before-status.txt` | Read-only `adb reverse --list` was empty; `lsof` was available and returned no local `tcp:54321` listener rows (status=1). |
| Diagnostic instrumentation run | `logs/connected-no-host-uiux-instrumentation.failed-diagnostic.log`, `logs/device-power-before-accepted.txt` | 134/135 passed, 1 failed due to screen dozing (`mWakefulness=Dozing`). Retained as diagnostic evidence only. |
| Accepted no-Host UI/UX instrumentation | `android-test-results/TEST-P0110-16-app.xml`, `android-test-results/test-results.log`, `logs/connected-no-host-uiux-instrumentation.accepted.log`, `android-test-report/index.html` | Passed 135/135 with failures=0, errors=0, skipped=0 across all 11 test classes; Gradle logged `BUILD SUCCESSFUL in 2m 23s`. |
| Focused no-Host JVM contracts | `logs/focused-control-surface-jvm.log`, `unit-test-results/` | Passed 129/129 with failures=0, errors=0, skipped=0 across eight focused classes; Gradle logged `BUILD SUCCESSFUL in 5s`. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-after.txt`, `logs/no-host-boundary-lsof-54321-after-status.txt` | Read-only `adb reverse --list` stayed empty; `lsof` returned no local `tcp:54321` listener rows (status=1). |

The retained instrumentation classes and test counts are:

- `ConnectionGuidanceLayoutInstrumentedTest` (35 tests)
- `SettingsDialogLayoutInstrumentedTest` (30 tests)
- `ConnectionStateAccessibilityInstrumentedTest` (17 tests)
- `ControlBarLayoutInstrumentedTest` (17 tests)
- `QRScannerLayoutInstrumentedTest` (10 tests)
- `InternetPairingDialogLayoutInstrumentedTest` (8 tests)
- `FileTransferOfferDialogLayoutInstrumentedTest` (7 tests)
- `ClipboardConfirmationDialogLayoutInstrumentedTest` (5 tests)
- `TrustedNetworkDialogLayoutInstrumentedTest` (3 tests)
- `InternetControlStateColorsInstrumentedTest` (2 tests)
- `GestureShortcutPreferencesInstrumentedTest` (1 test)

Total: 135 tests.

The retained focused JVM classes and test counts are:

- `MainActivityTerminalGuidanceContractTest` (73 tests)
- `SettingsDialogLayoutPolicyTest` (11 tests)
- `DesignTokenContrastTest` (9 tests)
- `MainActivityClipboardSystemBoundaryContractTest` (9 tests)
- `MainActivityFileTransferSystemBoundaryContractTest` (8 tests)
- `MainActivitySettingsAccessibilityContractTest` (8 tests)
- `WirelessTabControllerContractTest` (7 tests)
- `MainActivityTransferReadinessContractTest` (4 tests)

Total: 129 tests.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol v1
with a product Host. It did not create an `adb reverse tcp:54321 tcp:54321`
mapping. The retained read-only reverse samples are empty. The retained local
`lsof` samples show `lsof` was available and returned no `tcp:54321` listener
rows (exit code 1).

Evidence boundary statement:
This package does not prove or close:
1. macOS Host readiness or macOS hardware compatibility matrix
2. Screen Recording, Accessibility, or Microphone TCC permissions
3. Host resident-memory (RSS) two-hour no-growth gate
4. External-camera or sub-5ms synchronized latency archive gate
5. Native pointer HID confirmation
6. Controller runtime acceptance
7. Physical stylus drawing or injection acceptance
8. Real Android ClipboardManager <-> macOS NSPasteboard USB/LAN product E2E transfer
9. Real Android/macOS bidirectional file transfer product E2E bytes landing
10. Real LAN streaming or Internet traversal
11. iOS signed device or simulator acceptance
12. Xiaomi 13 / fuxi hardware acceptance

## Artifact Notes

Retained artifacts:
- `android-test-results/TEST-P0110-16-app.xml`: Accepted JUnit XML (135/135 passed).
- `android-test-results/test-result.redacted.textproto`: Redacted UTP textproto.
- `android-test-results/test-results.log`: Instrumentation status log.
- `android-test-results/utp.0.redacted.log`: Redacted UTP log.
- `android-test-report/`: Full HTML report assets (HTML, CSS, JS).
- `logs/connected-no-host-uiux-instrumentation.accepted.log`: Redacted accepted Gradle runner log.
- `logs/connected-no-host-uiux-instrumentation.failed-diagnostic.log`: Redacted diagnostic failed run log.
- `logs/focused-control-surface-jvm.log` and `unit-test-results/`: focused JVM runner and JUnit results.
- Boundary and device check logs under `logs/`.
- Metadata files under `metadata/`.

Redactions applied:
- Local adb serials are redacted to `<redacted-adb-serial>`.
- Absolute local workspace paths are redacted to `<workspace>`.
- Manufacturer, model, codename, OS, SDK/API, display, and font scale are preserved.

Omitted artifacts:
- Binary protobuf files (`device-info.pb`, `test-result.pb`).
- CPU, memory info, lock files, and raw per-test logcat traces.

## Verification

Verify checksums from this evidence directory:

    shasum -a 256 -c SHA256SUMS
