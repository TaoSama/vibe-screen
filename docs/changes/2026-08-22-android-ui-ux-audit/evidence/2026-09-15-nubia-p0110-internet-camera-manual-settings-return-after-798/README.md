# Nubia P0110 Internet camera manual-settings return recovery

Date: 2026-09-15

This no-Host Android run verifies the focused Internet Camera permission recovery gap after `origin/main` commit `c1d6717d03d594d792703337eb8af115e41dd978`: when the Internet permission recovery panel is already visible and the user grants Camera outside Vibe Screen without pressing the in-app `Open Settings` action, returning Vibe Screen to the foreground reconciles the real permission state and launches the QR scanner once.

## Result

- Device: Nubia P0110 (`pacific`), Android 16 / API 36, serial `EP0110PZ0B9110152B`. This is Nubia/P0110 evidence and is not Xiaomi/fuxi evidence.
- The focused instrumentation started with Camera denied, showed the Internet first-denial inline recovery panel, backgrounded `MainActivity`, granted Camera through instrumentation `UiAutomation`, returned to foreground, and observed the QR scanner preview.
- The app did not rely on the in-app `Open Settings` pending flag for this recovery path; the visible Internet permission panel was enough to trigger foreground permission reconciliation.
- After the run, adb reverse was empty and no local TCP `54321` listener was present. The app package was not left installed by the Gradle connected test run, so no Camera permission grant remained on the device.

## Verification

The final offline checks passed from the isolated worktree:

    ./gradlew --no-daemon --console=plain :app:testDebugUnitTest \
      --tests dev.telemachus.display.InternetCameraPermissionRecoveryPolicyTest \
      --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest \
      --tests dev.telemachus.display.CameraPermissionResumePolicyTest
    ./gradlew --no-daemon --console=plain :app:compileDebugAndroidTestKotlin :app:lintDebug
    make baseline-android-check
    ANDROID_SERIAL=EP0110PZ0B9110152B ./gradlew --no-daemon --console=plain \
      :app:connectedDebugAndroidTest \
      '-Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.InternetCameraPermissionRecoveryInstrumentedTest#visibleInternetPermissionPanelGrantedOutsideAppLaunchesScannerOnForegroundReturn' \
      -Pandroid.testInstrumentationRunnerArguments.vibeScreenInternetCameraRecovery=true

The retained final device evidence is `focused-runs-final-20260916-005100/run-{1,2,3}`. Each run has `exit-status.txt` equal to `0`; each XML report records `tests="1" failures="0" errors="0" skipped="0"` at `2026-09-15T16:51:18`, `2026-09-15T16:51:36`, and `2026-09-15T16:51:54`; each `test-result.textproto` reports `test_status: PASSED`; and each test log reports `OK (1 test)`. The retained logcat extracts show the required foreground reconciliation path in all three runs: `panelState=FIRST_DENIED settingsPending=false granted=true permanentlyDenied=false action=LAUNCH_SCANNER_ONCE launchResult=true`, followed by `startActivityForResult ... QRScannerActivity` and `Displayed dev.telemachus.display/.QRScannerActivity`.

An intermediate review check is intentionally retained as failure evidence: `verification/focused-jvm-after-review.log` exits `1` with `MainActivityTerminalGuidanceContractTest > internetCameraPermissionBlockedShowsInlineGuidanceWithoutAutomaticSettingsLaunch FAILED` at `MainActivityTerminalGuidanceContractTest.kt:1727` after `91 tests completed, 1 failed`. The failure was a brittle contract assertion that still searched for the pre-refactor inline expression `LAUNCH_SCANNER_ONCE -> return launchInternetScanner()` after `handleInternetCameraSettingsReturn()` was changed to assign `val launched = launchInternetScanner()` so the diagnostic log can include `launchResult`. The final contract update now asserts the foreground-return policy call, the `onResume` recovery hook, the Internet-mode early return in `onStart`, and the refactored scanner-launch assignment. `verification/focused-jvm-final.log` exits `0` and reports `BUILD SUCCESSFUL`.

The evidence directory was reduced to retained source metadata, final offline verification logs, the intermediate JVM failure log, and the three final P0110 focused runs. Generated HTML reports, binary protobuf reports, transient lock files, and redundant non-final verification logs were removed before rebuilding `SHA256SUMS`.

## Boundary

No macOS Host was started, installed, signed, inspected, or modified. No `tccutil`, `codesign`, or security keychain command was run. This evidence does not prove QR decoding, Internet pairing, public Internet transport, or a Host-backed stream; it only proves the Android-local Camera permission recovery behavior.
