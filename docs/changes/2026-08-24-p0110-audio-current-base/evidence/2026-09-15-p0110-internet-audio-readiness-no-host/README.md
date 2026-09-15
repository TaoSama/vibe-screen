# Nubia P0110 Internet Audio Readiness no-Host Smoke

Date: 2026-09-15 (local, Asia/Shanghai)

Scope: Android-local Settings readiness rendering for the Internet audio
playback path, plus focused JVM lifecycle contracts.

No Vibe Screen macOS Host was launched. No macOS Screen Recording,
Accessibility, or Microphone permission was requested. No
`adb reverse tcp:54321 tcp:54321` mapping was created.

## Source

Recorded before the change was committed:

    repository=TaoSama/vibe-screen
    branch=codex/android-internet-audio-readiness
    base=1da2d25770afc7a0e1b31582f0621b634faadeb1
    origin_main=1da2d25770afc7a0e1b31582f0621b634faadeb1
    base_subject=fix(android): hide unavailable Internet revoke action (#792)
    date=2026-09-15
    timezone=Asia/Shanghai

## Device

    serial=<redacted-adb-serial>
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560

This is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It must not
be reported as Xiaomi 13/fuxi evidence. The requested
`EP0110PZ0B9110300B` device was unavailable; the connected P0110 substitute
was used.

## Results

| Check | Result |
| --- | --- |
| Focused JVM audio/readiness contracts | Passed `ProtocolInternetAudioPlaybackTest`, `InternetProductSessionTest`, `MainActivityTransferReadinessContractTest`, and `ClientExperienceTest`; Gradle reported `BUILD SUCCESSFUL`. |
| Android test compilation | `:app:compileDebugAndroidTestKotlin` passed. |
| P0110 focused instrumentation | `InternetAudioReadinessSettingsInstrumentedTest` passed 1/1 with zero failures, errors, or skips; retained in `android-test-results/`. |
| Active Internet presentation | The Settings Audio section rendered the active PCM format and `3` accepted / `2` written packet counters from the Internet snapshot. |
| Disconnect presentation | Reopening Settings with the Internet session inactive rendered the waiting state and hid stale counters. |
| no-Host boundary | ADB reverse was empty and no local TCP `54321` listener existed before or after the run. |
| Device cleanup | Test preferences and hooks were restored; animation values were restored to `1.0`, `1.0`, and unset (`null`). |

## Commands

    cd baseline/AndroidClient
    ./gradlew --no-daemon --console=plain \
      :app:testDebugUnitTest \
      --tests dev.telemachus.display.MainActivityTransferReadinessContractTest \
      --tests 'dev.telemachus.display.internet.*Audio*' \
      --tests dev.telemachus.display.internet.InternetProductSessionTest \
      :app:compileDebugAndroidTestKotlin
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon --console=plain \
      :app:connectedDebugAndroidTest \
      '-Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.InternetAudioReadinessSettingsInstrumentedTest'

Espresso requires disabled device animations. The three animation settings
were recorded, temporarily disabled for the focused run, and restored in a
shell trap. No permission-grant command was used.

## Boundaries

This record proves only the Android Settings presentation and local state
lifecycle for an injected Internet audio readiness snapshot on P0110. It also
proves the focused JVM contracts for configuration, accepted/written counters,
rejection, playback failure, and cleanup.

It does not prove a real Internet session, Host microphone capture, macOS
Microphone TCC, `CAPABILITY_AUDIO` negotiation with a Host, audio DataChannel
delivery, production-session `AudioTrack` writes, audible output, public
Internet behavior, or Android/macOS audio E2E. Those gates remain open.
