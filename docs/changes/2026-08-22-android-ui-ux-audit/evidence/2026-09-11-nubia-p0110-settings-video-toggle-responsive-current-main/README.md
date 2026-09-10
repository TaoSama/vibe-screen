# Nubia P0110 Settings video toggle responsive refresh

Date: 2026-09-11

Scope: focused Android Settings dialog layout fix for `videoQualityGroup` and
`videoFrameRateGroup` on narrow portrait windows, large-text configurations,
and short landscape windows. This is no-Host Android UI evidence only.

No Vibe Screen macOS Host, Screen Recording, Accessibility, Microphone, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used.

## Source

    repository=TaoSama/vibe-screen
    worktree=<local-codex-worktree>/settings-video-toggle-responsive
    branch=codex/fix-settings-video-toggle-responsive
    base_head=21fd23df892ba15615bc4a8afe8a6af08f56090d
    origin_main=21fd23df892ba15615bc4a8afe8a6af08f56090d
    base_subject=fix(android): make trusted network dialog responsive (#765)
    date=2026-09-11
    timezone=Asia/Shanghai

## Device

The only Android instrumentation device used was the connected Nubia handset.
The ADB serial is intentionally redacted.

    serial=<redacted-adb-serial>
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0
    fingerprint=nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys

This is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It must not
be reported as Xiaomi 13/fuxi evidence.

## Commands

Commands were run from `baseline/AndroidClient` unless noted otherwise. The
instrumentation command used `ANDROID_SERIAL=<redacted-adb-serial>` and was run
serially against the device above.

    ./gradlew --no-daemon :app:testDebugUnitTest \
      --tests dev.telemachus.display.SettingsDialogLayoutPolicyTest

    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon \
      :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest

    ./gradlew --no-daemon :transport:check :app:testDebugUnitTest

    ./gradlew --no-daemon :app:assembleDebug

## Results

| Check | Result |
| --- | --- |
| Focused JVM policy test | Passed; Gradle reported `BUILD SUCCESSFUL in 8s`. |
| Focused Settings instrumentation on Nubia P0110/pacific | Passed 24/24; Gradle reported `Finished 24 tests on P0110 - 16` and `BUILD SUCCESSFUL in 22s`. |
| Android transport + app JVM regression | Passed; Gradle reported `BUILD SUCCESSFUL in 27s`. |
| Debug APK build | Passed; Gradle reported `BUILD SUCCESSFUL in 5s`. |

The focused instrumentation coverage now verifies the Settings video quality and
frame-rate toggle groups at 320dp and 360dp with fontScale 1.0, 1.5, and 2.0,
plus 640x320 short landscape with fontScale 1.0, 1.5, and 2.0. Assertions cover
no ellipsis, no substantial button overlap, minimum 48dp button touch targets,
scroll reachability, and width transitions preserving selected toggle state and
single-selection semantics.

## Boundaries

This evidence does not prove Host-backed streaming, Protocol v1 negotiation,
clipboard or file-transfer product E2E, LAN, Internet traversal, input
forwarding, reconnect, latency, soak, Host signing/TCC readiness, native
pointer, stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi
13/fuxi behavior.
