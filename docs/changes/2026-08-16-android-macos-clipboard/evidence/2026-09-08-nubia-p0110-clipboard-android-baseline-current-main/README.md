# Nubia P0110 Clipboard Android Baseline Current Main

Date: 2026-09-08 (local Asia/Shanghai; UTC 2026-09-07)
Source base: `853cd03ce8c26414a0c28bfbb312ebfff5311d34`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package refreshes the Android-side no-Host clipboard baseline on current
main. It proves local Android `ClipboardManager` and confirmation-dialog
readiness on the P0110 only. It does not prove Android `ClipboardManager` ->
macOS `NSPasteboard` or macOS `NSPasteboard` -> Android `ClipboardManager`
product transfer.

## What Passed

- Focused Android clipboard JVM tests passed locally: `:app:testDebugUnitTest`
  with `MainActivityClipboardSystemBoundaryContractTest`,
  `ClipboardApprovalStateTest`, `ProtocolV1ClipboardTest`, and
  `ProtocolV1ClipboardFailClosedTest`.
- `ClipboardManagerInstrumentedTest` passed on Nubia P0110 with 8 executed tests,
  0 failures, 0 errors, and 0 skipped. The smoke covers ordinary foreground
  text, instrumentation-argument set/read behavior, 256 KiB UTF-8 Unicode text,
  an expanded 320 KiB UTF-8 text round trip, empty clipboard clearing, safe
  handling of non-text Intent `ClipData`, and multi-item `ClipData` where the
  first item is non-text and later text is not treated as the first transferable
  value.
- `ClipboardConfirmationDialogLayoutInstrumentedTest` passed on Nubia P0110 with
  2 executed tests, 0 failures, 0 errors, and 0 skipped. The dialog coverage
  still proves send, receive, overwrite copy, size/protection/direction/preview
  fields, truncated previews, large font, narrow portrait, landscape, label
  ownership, selectable preview text, and scroll reachability.
- `adb -s REDACTED_P0110_USB_SERIAL reverse --list` was read only and showed no
  `tcp:54321` reverse mapping.

## Observed Device Limit

During this task, exploratory 512 KiB and 1 MiB local Android
`ClipboardManager.setPrimaryClip` attempts on the P0110 hit Android Binder
transaction-size limits and crashed the instrumentation process with
`TransactionTooLargeException`. Those failed attempts are not counted as passing
evidence. The product Protocol v1 1 MiB negotiated ceiling remains covered by
offline JVM/protocol tests; it is not claimed as a local Android system
clipboard device-smoke pass.

## Evidence Boundary

This run did not start Vibe Screen, MacHost, or Telemachus GUI. It did not run
`swift run`, request or reset Screen Recording, Accessibility, Microphone,
Keychain, TCC, or System Settings state, configure `adb reverse tcp:54321
tcp:54321`, read or write macOS `NSPasteboard`, or execute a bidirectional
Android/macOS product clipboard transfer.

The generated Android no-Host evidence is intentionally insufficient to close
`clipboard_android_macos_product_e2e`. The gate remains blocked until retained
product evidence proves both Android `ClipboardManager` -> macOS `NSPasteboard`
and macOS `NSPasteboard` -> Android `ClipboardManager` with exact endpoints,
explicit user action, receiver approval, Protocol v1 session ownership, verified
session epoch and origin, 16-byte change IDs, SHA-256 equality, bounded byte
length, distinct final markers, and non-empty retained artifacts for each role.

The P0110 evidence must not be relabeled as Xiaomi 13/fuxi evidence.

## Commands

```bash
cd baseline/AndroidClient
./gradlew :app:testDebugUnitTest \
  --tests dev.telemachus.display.MainActivityClipboardSystemBoundaryContractTest \
  --tests dev.telemachus.display.ClipboardApprovalStateTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest

./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ClipboardManagerInstrumentedTest

./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest

adb -s REDACTED_P0110_USB_SERIAL reverse --list
```

## Artifacts

- `logs/clipboard-manager-instrumentation.xml` - 8-test Android
  `ClipboardManagerInstrumentedTest` result, failures 0, errors 0, skipped 0.
- `logs/clipboard-manager-instrumentation.log` - instrumentation text log for
  the 8-test run.
- `logs/clipboard-manager-test-result.textproto` - Android test-result proto
  text for the 8-test run.
- `logs/clipboard-dialog-instrumentation.xml` - 2-test dialog layout
  instrumentation result, failures 0, errors 0, skipped 0.
- `logs/clipboard-dialog-instrumentation.log` - instrumentation text log for
  the dialog layout run.
- `logs/adb-reverse-list.txt` - read-only ADB reverse snapshot with no
  `tcp:54321` mapping.
