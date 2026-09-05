# Nubia P0110 no-Host UI/UX expanded current-main refresh

Date: 2026-09-06

Scope: Android no-Host UI/layout instrumentation on the connected Nubia P0110.
This refresh extends the earlier current-main layout run by adding the Internet
pairing and profile-import dialog layout checks to the focused no-Host set. No
macOS Vibe Screen, MacHost, or Telemachus GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Keychain, System Settings,
`tccutil reset`, or `adb reverse` creation/removal was used.

## Source

Recorded in `metadata/source-provenance.txt`:

```text
repository=TaoSama/vibe-screen
evidence_branch=docs/p0110-no-host-uiux-evidence-20260906
tested_source_commit=aa578cb960408e8113ee5c84fb412c6d23ec0020
origin_main_at_test=aa578cb960408e8113ee5c84fb412c6d23ec0020
tested_source_subject=Improve managed-policy disabled UI explanations
```

This is a docs/evidence refresh from current `origin/main`; no Android source
change was required.

## Device

Recorded in `metadata/device-identity.txt` with the ADB serial redacted:

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

Run from `baseline/AndroidClient` unless noted. The real run used the fixed
P0110 ADB serial requested for this task; retained logs redact the serial as
`<redacted-adb-serial>`.

```bash
./gradlew --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest
```

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Debug and androidTest APK build | `logs/gradle-assemble-debug-androidtest.log` | `BUILD SUCCESSFUL in 16s` |
| P0110 no-Host UI/layout instrumentation | `logs/connected-uiux-layout-instrumentation.log` | `Starting 48 tests on P0110 - 16`; `Finished 48 tests on P0110 - 16`; `BUILD SUCCESSFUL in 1m 51s` |
| JUnit XML report | `android-test-results/TEST-P0110 - 16-_app-.xml` | `tests="48" failures="0" errors="0" skipped="0"` |
| HTML report | `android-test-report/index.html` | Gradle connected-test report copied for review |
| no-Host boundary | `logs/no-host-boundary.txt`, `logs/adb-reverse-after-tests.txt` | No local TCP `54321` listener was retained; `adb reverse --list` showed only `UsbFfs tcp:8908 tcp:8908` |

The retained 48 methods cover these focused no-Host Android UI/layout surfaces:

- `dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest`
- `dev.telemachus.display.ControlBarLayoutInstrumentedTest`
- `dev.telemachus.display.SettingsDialogLayoutInstrumentedTest`
- `dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest`

Notable covered assertions include disconnected USB/LAN/Internet guidance
readability, USB retry diagnostics ordering, large-text and landscape layout
stress, control-bar transfer progress and touch-target geometry, Settings
transfer-readiness live-region behavior, unavailable feature explanatory notes,
and Internet pairing/profile-import dialog input readability, scrolling,
sensitive-input flags, and production dialog button touch targets.

`logs/internet-dialog-device-files.txt` records that the temporary on-device
external-files directory was not available after the connected-test cleanup. No
screenshot claim depends on that directory in this evidence package.

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
