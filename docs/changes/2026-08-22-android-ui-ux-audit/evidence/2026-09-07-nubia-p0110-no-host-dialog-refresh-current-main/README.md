# Nubia P0110 no-Host dialog layout current-main refresh

Date: 2026-09-07

Scope: Android no-Host UI/layout instrumentation on the connected Nubia P0110
for the file-transfer offer dialogs and clipboard confirmation dialogs. No
Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No swift run,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or adb reverse tcp:54321 tcp:54321 command
was used.

## Source

Recorded in metadata/source-provenance.txt:

    repository=TaoSama/vibe-screen
    branch=codex/p0110-no-host-dialog-evidence
    commit=92ca2ab59cd76090ff520c3b1be431cd86d8aa06
    origin_main=92ca2ab59cd76090ff520c3b1be431cd86d8aa06
    date=2026-09-07

This is a docs/evidence refresh from current origin/main; no Android source
change was required.

## Device

Recorded in metadata/device-identity.txt with the ADB serial redacted:

    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560

This record is Nubia P0110 / pacific / Android 16 / SDK 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from baseline/AndroidClient unless noted.

    adb -s <redacted-adb-serial> reverse --list
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest,dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest
    adb -s <redacted-adb-serial> reverse --list

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Pre-run no-Host boundary | logs/adb-reverse-before-tests.txt | adb reverse --list showed only UsbFfs tcp:8908 tcp:8908; no tcp:54321 mapping was present. |
| P0110 focused dialog instrumentation | logs/connected-dialog-instrumentation.log | Gradle ran Starting 5 tests on P0110 - 16, Finished 5 tests on P0110 - 16, and BUILD SUCCESSFUL in 22s. |
| JUnit XML report | android-test-results/TEST-P0110 - 16-_app-.xml | tests=5, failures=0, errors=0, skipped=0. |
| HTML report | android-test-report/index.html | Gradle connected-test report copied for review. |
| Post-run no-Host boundary | logs/adb-reverse-after-tests.txt | adb reverse --list still showed only UsbFfs tcp:8908 tcp:8908; no tcp:54321 mapping was created. |

The retained five methods are:

- FileTransferOfferDialogLayoutInstrumentedTest.narrowAndLargeFontOfferDialogKeepsDecisionContentReadableAndScrollable
- FileTransferOfferDialogLayoutInstrumentedTest.offerLayoutKeepsDecisionCopyStructuredForDialogButtons
- FileTransferOfferDialogLayoutInstrumentedTest.outgoingConfirmationLayoutKeepsPreflightDetailsReadableAndScrollable
- ClipboardConfirmationDialogLayoutInstrumentedTest.narrowAndLargeFontClipboardConfirmationKeepsContentReadableAndScrollable
- ClipboardConfirmationDialogLayoutInstrumentedTest.clipboardConfirmationCoversSendReceiveAndOverwriteCopy

The file-transfer coverage checks incoming offer content, outgoing preflight
details, long filenames, large text, narrow portrait and landscape constraints,
field-label relationships, selectable/non-horizontal text, scroll reachability,
and the Receive/Reject/Send action labels used by the product dialogs.

The clipboard coverage checks send, receive, and overwrite confirmation copy,
direction/protection/size/preview fields, bounded truncated preview text, large
text, narrow portrait and landscape constraints, field-label relationships,
selectable/non-horizontal preview text, and scroll reachability.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol
v1. It did not create an adb reverse tcp:54321 tcp:54321 mapping. The retained
pre-run and post-run reverse samples contain only the unrelated pre-existing
UsbFfs tcp:8908 tcp:8908 entry.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection in a real
product session, receiver approval in a real product session, saved remote
files, final SHA-256 equality, Android ClipboardManager <-> macOS NSPasteboard
E2E, LAN streaming, Internet traversal, video decode, input forwarding,
reconnect timing, latency, soak, Host signing/TCC readiness, native pointer,
stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi
behavior.

## Artifact Notes

UTP binary device-info and protobuf files were omitted because they include the
raw ADB serial. Retained text logs and reports are redacted and replace the
local checkout prefix with <repo-root>.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
