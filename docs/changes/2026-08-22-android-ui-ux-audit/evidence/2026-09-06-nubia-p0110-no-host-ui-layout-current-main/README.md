# Nubia P0110 no-Host UI layout current-main refresh

Date: 2026-09-06

Scope: Android no-Host UI/layout instrumentation on the connected Nubia P0110.
No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Keychain, System Settings,
`tccutil reset`, or `adb reverse` creation was used.

## Source

Recorded in `source-provenance.txt`:

```text
repository=TaoSama/vibe-screen
branch=codex/p0110-no-host-layout-evidence-20260906
commit=4c8403def698ae33658af65e2db09e00bae0534d
origin_main=4c8403def698ae33658af65e2db09e00bae0534d
```

This is a docs/evidence refresh from current `origin/main`; no Android source
change was required.

## Device

Recorded in `device-identity.txt`:

```text
manufacturer=nubia
model=P0110
device=pacific
release=16
sdk=36
wm_size=Physical size: 1264x2800
wm_density=Physical density: 560
```

`adb-devices-after-tests.txt` records the selected device with the serial
redacted as `<redacted-adb-serial>` and product/model/device values
`pacific` / `P0110` / `pacific`.

## Commands

Run from `baseline/AndroidClient` unless noted.

```bash
./gradlew --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Debug and androidTest APK build | `gradle-assemble-debug-androidtest.log` | `BUILD SUCCESSFUL in 6s` |
| P0110 connected layout instrumentation | `connected-layout-instrumentation.log` | `Starting 43 tests on P0110 - 16`; `P0110 - 16 Tests 43/43 completed. (0 skipped) (0 failed)`; `BUILD SUCCESSFUL in 1m 7s` |
| JUnit XML report | `android-test-results/TEST-P0110 - 16-_app-.xml` | `tests="43" failures="0" errors="0" skipped="0"` |
| HTML report | `android-test-report/index.html` | Gradle connected-test report copied for review |

The retained 43 methods cover the focused no-Host layout surfaces in:

- `dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest`
- `dev.telemachus.display.ControlBarLayoutInstrumentedTest`
- `dev.telemachus.display.SettingsDialogLayoutInstrumentedTest`

Notable covered assertions include file-transfer control touch-target geometry,
transfer readiness live-region behavior, unavailable control explanatory notes,
large-text/landscape connection guidance, small-tablet width settings layout,
and sustained-use status image generation inside instrumentation.

## No-Host Boundaries

`adb-reverse-list-after-tests.txt` shows only the pre-existing unrelated mapping:

```text
UsbFfs tcp:8908 tcp:8908
```

No `tcp:54321` mapping was present, and this run did not create one. This
record therefore supports Android no-Host UI/layout readiness only. It does not
prove Host-backed bytes landing, Android ClipboardManager <-> macOS NSPasteboard
E2E, real file transfer E2E, LAN streaming, Internet transport, latency, soak,
native pointer, stylus, controller, iOS, or macOS hardware acceptance.
