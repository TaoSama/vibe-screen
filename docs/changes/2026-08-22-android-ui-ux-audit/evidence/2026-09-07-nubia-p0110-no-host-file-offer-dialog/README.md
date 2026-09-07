# Nubia P0110 no-Host file-offer dialog layout refresh

Date: 2026-09-07

Scope: Android no-Host UI/layout validation for the incoming file-transfer
offer dialog on the connected Nubia P0110. This refresh covers long incoming
file names, large text, narrow portrait and landscape dialog constraints,
structured file/size/destination copy, scroll reachability, and retained
Receive/Reject action labels. No macOS Vibe Screen, MacHost, or Telemachus GUI
was launched. No `swift run`, macOS TCC, Screen Recording, Accessibility,
Microphone, Keychain, System Settings, or signing/re-signing was used.

## Source

Recorded in `metadata/source-provenance.txt`:

```text
repository=TaoSama/vibe-screen
evidence_branch=codex/android-file-offer-dialog-readiness
base_commit=dfbd10c9c5d460ec90f2c75c4a43eefda9875c88
origin_main_at_test=2e6e0a773ba04770d36e2d6adfba6068b79fdb52
working_tree_diff_sha256=29ef93abe9c82afb67ed88fb4f34ecbb8ae56f1935558b8fcf674d8b797fd75e
```

The evidence was collected from this feature branch after the Android UI/test
diff was applied. `working_tree_diff_sha256` records the non-evidence source
diff digest at collection time.

## Device

Recorded in `metadata/device-identity.txt` with the ADB serial redacted:

```text
serial=<redacted-adb-serial>
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

Run from `baseline/AndroidClient` unless noted. The focused JVM and debug
build checks were run during branch validation, but only the connected-device
layout runs and the post-run reverse sample are retained in this evidence
package.

```bash
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest
adb -s <redacted-adb-serial> install -r app/build/outputs/apk/debug/app-debug.apk
adb -s <redacted-adb-serial> install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s <redacted-adb-serial> shell am instrument -w -r \
  -e class dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
adb -s <redacted-adb-serial> reverse --list
```

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| P0110 file-offer dialog instrumentation | `logs/connected-file-offer-dialog-instrumentation.log`, `android-test-results/TEST-P0110 - 16-_app-.xml`, `android-test-results/P0110 - 16/test-result.textproto`, `android-test-results/P0110 - 16/testlog/test-results.log` | Gradle/UTP executed both methods and recorded `tests="2"`, `failures="0"`, `errors="0"`, and `skipped="0"`; the same command emitted `Starting 2 tests on P0110 - 16`, `Finished 2 tests on P0110 - 16`, and `BUILD SUCCESSFUL in 16s` |
| Direct runner confirmation | `logs/adb-install-am-instrument-file-offer-dialog.log` | Explicit APK reinstall registered `dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner`; `am instrument` returned `OK (2 tests)` |
| HTML report | `android-test-report/index.html` | Gradle connected-test report copied for review |
| no-Host boundary | `logs/adb-reverse-after-tests.txt` | `adb reverse --list` showed only `UsbFfs tcp:8908 tcp:8908`, with no `tcp:54321` mapping |

The focused instrumentation validates the incoming file-offer dialog in a
measured no-Host Android context. It checks that each content field has a text
layout, no measured line is ellipsized, long file names fit the field width
without horizontal scrolling, labels remain associated with their fields, the
dialog content can scroll to the verification note when needed, and the
Receive/Reject labels remain the decision actions used by the product dialog.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol
v1. It did not create an `adb reverse tcp:54321 tcp:54321` mapping. The retained
post-run reverse sample contains only the unrelated pre-existing
`UsbFfs tcp:8908 tcp:8908` entry.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection, receiver
approval in a real product session, saved remote files, final SHA-256 equality,
cancel cleanup, Android ClipboardManager <-> macOS NSPasteboard E2E, LAN
streaming, Internet traversal, video decode, input forwarding, reconnect
timing, latency, soak, Host signing/TCC readiness, native pointer, stylus,
controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi behavior.

## Diagnostics

Earlier diagnostic reruns exposed unstable device/UTP cleanup and installation
state: after Gradle completed the test methods, later invocations could remove
the target and test packages while still treating install tasks as up-to-date,
producing a runner-not-found or zero-test failure. Failed UTP summaries from
that diagnosis are retained under `diagnostics/` and are not used as pass
evidence. The retained pass evidence comes from the latest Gradle/UTP run above;
the direct `adb install -r` plus `am instrument` confirmation independently
returned `OK (2 tests)`. UTP device-info artifacts referenced inside the
textproto were intentionally omitted from the retained package because they
include the raw ADB serial; `metadata/device-identity.txt` records the same
device identity with the serial redacted.
