# 2026-09-10 Nubia P0110 No-Host Internet Pairing Completion A11y

## Scope

This evidence records a focused no-Host Android validation for the Internet
pairing completion dialog after the accessibility and error-guidance update.
The checked surface is the acceptance-code completion dialog: inline parse
errors stay inside the dialog, the acceptance field exposes an accessibility
error without using the EditText.error popup, input changes clear the visible
error, the error row remains reachable in constrained IME and narrow-phone
layouts, and the production MaterialAlertDialogBuilder keeps content
scrollable.

This is not Host-backed product-session evidence. It does not claim Android/macOS
clipboard E2E, Android/macOS file-transfer E2E, Xiaomi 13/fuxi evidence, or any
macOS Host/TCC readiness result.

## Source

| Field | Value |
| --- | --- |
| Branch | codex/internet-pairing-completion-a11y-2 |
| Source HEAD | 9aeb7e3253f61025cb3ce6c0303ff632d462ccef |
| origin/main | 4c16432427d573aa5239f9d56de8ae1a77a04661 |
| Reviewed product files vs source HEAD | 0 changed files |

See metadata/source-provenance.txt for the captured source state. The evidence
commit is intentionally separate from the product/test commit, and source_head
points to that product/test commit.

## Device

| Field | Value |
| --- | --- |
| Manufacturer | Nubia |
| Model | P0110 |
| Codename | pacific |
| Android | 16 |
| API | 36 |
| ADB serial | <redacted-adb-serial> |

See metadata/device-identity.txt for retained device metadata. This record must
remain Nubia P0110/pacific evidence and must not be relabeled as Xiaomi 13/fuxi
evidence.

## Host Boundary

No macOS Host was started, installed, modified, re-signed, or granted Screen
Recording, Accessibility, Microphone, or other TCC permissions for this run. No
adb reverse tcp:54321 tcp:54321 mapping was created. The only ADB reverse
operation recorded here is read-only adb reverse --list.

| Boundary check | Evidence | Result |
| --- | --- | --- |
| ADB reverse before tests | logs/adb-reverse-before-tests.txt | Empty |
| ADB reverse after tests | logs/adb-reverse-after-tests.txt | Empty |
| Local listener on tcp:54321 before tests | logs/no-host-boundary-lsof-54321-before-status.txt | Exit status 1 |
| Local listener on tcp:54321 after tests | logs/no-host-boundary-lsof-54321-after-status.txt | Exit status 1 |
| Instrumentation test process before tests | logs/instrumentation-pid-before-status.txt | Exit status 1 |
| Instrumentation test process after tests | logs/instrumentation-pid-after-tests-status.txt | Exit status 1 |

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Diff whitespace check | logs/git-diff-check.log, logs/git-diff-check-status.txt | PASS, status 0 |
| Focused JVM contracts | logs/focused-control-surface-jvm.log, unit-test-results/ | PASS, 91 tests across 4 suites, BUILD SUCCESSFUL in 5s |
| AndroidTest compile | logs/compile-debug-android-test-kotlin.log | PASS, BUILD SUCCESSFUL in 4s |
| Focused instrumentation on Nubia P0110/pacific | logs/connected-no-host-uiux-instrumentation.log, android-test-results/, android-test-report/ | PASS, Starting 6 tests on P0110 - 16; Finished 6 tests on P0110 - 16; BUILD SUCCESSFUL in 16s |

The focused instrumentation class is
dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest. It covers
the pairing completion dialog and the adjacent profile-import dialog layout
guards retained in that shared test class. The retained JUnit XML reports
tests=6, failures=0, errors=0, skipped=0 for the device run.

The focused JVM contracts include:

- MainActivityTerminalGuidanceContractTest
- MainActivityClipboardSystemBoundaryContractTest
- MainActivityFileTransferSystemBoundaryContractTest
- MainActivityTransferReadinessContractTest

Together they preserve the no-Host control-surface boundaries around terminal
guidance, clipboard, file transfer, and transfer readiness while the completion
dialog behavior changes.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol v1
with a product Host. It did not create an adb reverse tcp:54321 tcp:54321
mapping. The retained read-only reverse samples are empty. The retained local
lsof samples show lsof was available and returned no tcp:54321 listener rows.

This package does not prove Host-backed pairing completion, LAN streaming,
Internet traversal, video decode, input forwarding, reconnect timing, latency,
soak, Host signing/TCC readiness, Android ClipboardManager <-> macOS NSPasteboard
E2E, Android/macOS file-transfer product E2E, native pointer, stylus,
controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi behavior.

## Artifact Notes

UTP binary device-info.pb, binary test-result.pb, cpuinfo, meminfo, lock files,
and per-test raw logcat files were omitted because JUnit XML, HTML report,
textproto, and Gradle logs are sufficient for this focused no-Host UI/UX
validation and avoid retaining extra device identifiers or unrelated system
network telemetry. Retained text artifacts redact the ADB serial.

## Integrity

Verify retained evidence from the repository root with:

    shasum -a 256 -c docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-10-nubia-p0110-no-host-internet-pairing-completion-a11y/SHA256SUMS
