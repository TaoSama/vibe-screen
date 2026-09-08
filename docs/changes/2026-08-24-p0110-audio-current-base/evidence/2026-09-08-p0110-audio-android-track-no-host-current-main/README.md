# Nubia P0110 Android AudioTrack no-Host Current Main Smoke

Date: 2026-09-08 (local, Asia/Shanghai)

Scope: current-main Android no-Host playback-adapter smoke and focused JVM
audio contract checks on the connected Nubia P0110.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    branch=codex/p0110-audio-nohost-current-main
    head=47d139cba7372e3fa7927129da259c53a7b829cd
    origin_main=47d139cba7372e3fa7927129da259c53a7b829cd
    head_subject=docs: add p0110 no-host uiux rerun evidence (#683)
    date=2026-09-08
    date_time=2026-09-08T09:10:47+0800
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

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from the repository root unless noted. Device commands used the redacted
serial placeholder shown below. The full command list is retained in
`commands.txt`.

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
    cd baseline/AndroidClient
    adb -s <redacted-adb-serial> logcat -c
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.audio.ProtocolPcmAudioPlayerInstrumentedTest
    adb -s <redacted-adb-serial> logcat -d -s AudioTrackSmokeTest
    ./gradlew --no-daemon testDebugUnitTest \
      --tests "dev.telemachus.display.audio.ProtocolPcmAudioPlaybackTest" \
      --tests "dev.telemachus.display.audio.ProtocolPcmAudioStreamTest" \
      --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.usbLanPcmFixtureNegotiatesWritesAndCleansUpOnDisconnect" \
      --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.rejectedAudioReconfigurationStopsExistingPlayback" \
      --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.malformedAudioPacketAfterAcceptedConfigFailsSessionAndReleasesOutput"
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN
    make android-audio-playback-owner-record EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-09-08-p0110-audio-android-track-no-host-current-main
    shasum -a 256 -c SHA256SUMS

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Device identity | `metadata/device-identity.txt` | Device matched Nubia P0110 / pacific / Android 16 / API 36. |
| Pre-run no-Host boundary | `logs/adb-reverse-before-tests.txt`, `logs/no-host-boundary-lsof-54321-before.txt`, `logs/no-host-boundary-lsof-54321-before-status.txt` | `adb reverse --list` was empty; the `lsof` probe returned status `1` with no local `tcp:54321` listener rows before the run. |
| Android AudioTrack no-Host smoke | `android-test-results/TEST-P0110 - 16-_app-.xml`, `logs/android-audio-track-instrumentation.txt` | `ProtocolPcmAudioPlayerInstrumentedTest` passed with `tests=1`, `failures=0`, `errors=0`, `skipped=0`. |
| AudioTrack smoke marker | `logs/android-audio-track-logcat.txt`, `logs/android-audio-track-utp-logcat.txt` | Logcat retained `android_audio_track_smoke=start_write_close packets=1 bytes=1920`. |
| Focused JVM audio contracts | `unit-test-results/`, `logs/android-audio-focused-jvm-tests.txt` | Passed 38/38 across `ProtocolPcmAudioPlaybackTest`, `ProtocolPcmAudioStreamTest`, and three focused `StreamClientProtocolV1IntegrationTest` methods; Gradle completed with `BUILD SUCCESSFUL`. |
| Audio playback owner summary | `android-audio-playback-summary.json` | Expected fail-closed owner result: `verdict=blocked`, `can_close_android_audio_playback_gate=false`. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-after.txt`, `logs/no-host-boundary-lsof-54321-after-status.txt` | ADB reverse listing stayed empty; `lsof` returned no local `tcp:54321` listener rows after the run. |

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol v1
with a product Host. It did not create an ADB reverse mapping. The retained
reverse samples are empty. The retained local `lsof` samples and status records
show the listener probe returned status `1` and no `tcp:54321` listener rows.

This package proves only Android-local playback-adapter availability on the
Nubia P0110: `ProtocolPcmAudioPlayer(AndroidAudioTrackOutputFactory())` can
create a real `AudioTrack`, configure PCM S16LE 48 kHz stereo, accept one
synthetic 480-frame packet at sequence `0`, write 1920 bytes, and close cleanly.

It does not prove macOS microphone capture, `CAPABILITY_AUDIO` negotiation,
accepted Host-sent `AudioConfig`, Host channel `3` transport packets, Android
production-session AudioTrack writes, audible output, USB/LAN product E2E,
trusted-LAN secure records, public-Internet audio playback, disconnect cleanup,
Host signing/TCC readiness, or Xiaomi 13/fuxi behavior.

## Artifact Notes

UTP binary `device-info.pb`, `test-result.pb`, `cpuinfo`, `meminfo`, and lock
files were omitted because text XML/HTML/log artifacts are sufficient for this
no-Host refresh and avoid retaining extra device identifiers.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
