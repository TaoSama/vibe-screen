# P0110 Android Clipboard Device Attempt

Date: 2026-08-20 UTC / 2026-08-21 Asia/Shanghai
Branch: codex/android-clipboard-e2e-evidence
Baseline: origin/main at 8e630ad3
Scope: Android ClipboardManager <-> macOS NSPasteboard Protocol v1 device E2E
Verdict: blocked for cross-device E2E; Android local ClipboardManager smoke passed

## Device and Lock

The stale /tmp/vibe-screen-device-android.lock file from the earlier attempt was
rechecked before use: pid 88456 no longer existed and lsof reported no lock-file
holder. The stale file was removed, and this task reacquired the device with an
exclusive flock lease before running ADB.

Final lock metadata:

    task=android-clipboard-e2e
    branch=codex/android-clipboard-e2e-evidence
    pid=60011
    serial=EP0110PZ0B9110300B
    lock_method=perl_flock_exclusive_background_holder

The target device identity was recorded with explicit adb -s commands:

- serial: EP0110PZ0B9110300B
- manufacturer: nubia
- model: P0110
- codename/device: pacific
- Android release: 16
- SDK: 36
- fingerprint: nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys

An emulator was also connected, so every retained ADB command used
adb -s EP0110PZ0B9110300B.

## Passed Android Checks

Android unit clipboard coverage passed after rebasing to origin/main 8e630ad3:

    cd baseline/AndroidClient
    ./gradlew --no-daemon testDebugUnitTest \
      --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
      --tests dev.telemachus.display.ClipboardApprovalStateTest

Result: BUILD SUCCESSFUL in 4s.

The debug app and androidTest APK built and installed on the P0110 device:

    ./gradlew --no-daemon assembleDebug assembleDebugAndroidTest
    adb -s EP0110PZ0B9110300B install -r -t app/build/outputs/apk/debug/app-debug.apk
    adb -s EP0110PZ0B9110300B install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk

Results: Gradle BUILD SUCCESSFUL in 4s; both installs reported Success.

The focused Android system clipboard instrumentation test passed on the P0110:

    adb -s EP0110PZ0B9110300B shell am instrument -w \
      -e class dev.telemachus.display.ClipboardManagerInstrumentedTest \
      dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner

Result: OK (1 test). The focused logcat recorded:

    ClipboardDeviceTest: clipboard_manager_roundtrip marker=vs-clipboard-device-1787249745010

This proves only that the foreground Android app can write and read back a
non-sensitive marker through the Android system ClipboardManager on this
device. It does not exercise Protocol v1, the MacHost, or macOS NSPasteboard.

## Host Blocker

The current-branch MacHost could not be installed and preflighted as the stable
device-test host because this keychain does not contain the configured
Vibe Screen Dev signing identity:

    codesign identity 'Vibe Screen Dev' not found in the keychain...

Using ad-hoc signing would change the code-signing hash and invalidate the
macOS Screen Recording / Accessibility grants, so it was not used as replacement
evidence for the current branch.

An earlier probe using the already installed /Applications/Vibe Screen.app did
not establish a valid Protocol v1 clipboard session. The Android log showed
Protocol upgrade probe closed before a response, and there was no retained
same-session evidence of clipboardAvailable=true, Offer/Request/Content,
pbcopy/pbpaste, or a human-visible two-direction marker readback.

The local Mac clipboard XCTest command was also rerun after rebasing, but the
machine still has Command Line Tools selected instead of a full Xcode test SDK:

    cd baseline/MacHost
    swift test --scratch-path /tmp/vibe-screen-mac-host-swift-clipboard-3c7e \
      --filter Clipboard

Result: blocked before test execution with error: no such module 'XCTest'. This
is an environment blocker, not a clipboard assertion failure.

## Gate Status

The Android ClipboardManager <-> macOS NSPasteboard E2E gate remains open.
Closing it still requires the RUNBOOK.md pass criteria: a current-branch,
stable-signed Host with macOS permissions, a live Protocol v1 session with
clipboard capability negotiated by both peers, and verified Android -> Mac plus
Mac -> Android marker transfer through the real system clipboards.

## Retained Files

- device-info-final.txt: lock metadata and P0110 device identity.
- host-preflight-after-rebase.txt: stable-signing preflight blocker.
- android-unit-clipboard-final.txt: focused JVM clipboard tests.
- android-assemble-debug-final.txt: debug app and androidTest build.
- android-install-debug-final.txt: app install result.
- android-install-debug-android-test-final.txt: androidTest install result.
- android-instrumentation-clipboard-manager-final.txt: focused Android
  ClipboardManager instrumentation result.
- android-logcat-clipboard-manager-final.txt: focused ClipboardManager marker
  logcat.
- mac-swift-test-clipboard-after-rebase.txt: local Swift XCTest environment
  blocker.
- commands.txt: command transcript.
- observations.md: human-readable observations and non-observations.
- clipboard-evidence.json: structured verdict summary.
