# Clipboard Preview Policy JVM Evidence

Date: 2026-09-08 (local, Asia/Shanghai)
Device probe: nubia P0110 / pacific / Android 16 / SDK 36, serial `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: Android clipboard local boundary strengthened. Product E2E remains open.

This run adds focused JVM coverage for the clipboard confirmation preview policy
used by Android clipboard send/receive overwrite dialogs. It does not start the
macOS Host, does not create `adb reverse tcp:54321 tcp:54321`, does not access
macOS `NSPasteboard`, and does not prove Android `ClipboardManager` <-> macOS
`NSPasteboard` USB/LAN product transfer.

## What Changed

- Extracted the Android clipboard confirmation preview wrapping/truncation logic
  from `MainActivity` into `ClipboardPreviewPolicy`.
- Added `ClipboardPreviewPolicyTest` coverage for per-line wrapping, exact
  280-character non-truncation, 281-character truncation-before-wrapping, and
  empty preview behavior.

## Verification

```text
cd baseline/AndroidClient
./gradlew :app:testDebugUnitTest \
  --tests dev.telemachus.display.ClipboardPreviewPolicyTest \
  --tests dev.telemachus.display.MainActivityClipboardSystemBoundaryContractTest \
  --tests dev.telemachus.display.ClientExperienceTest \
  --tests dev.telemachus.display.ClipboardApprovalStateTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest \
  --tests dev.telemachus.display.internet.InternetClipboardTest

BUILD SUCCESSFUL in 6s
```

Device identity was checked with read-only ADB commands:

```text
adb -s REDACTED_P0110_USB_SERIAL get-state
adb -s REDACTED_P0110_USB_SERIAL shell getprop ro.product.manufacturer
adb -s REDACTED_P0110_USB_SERIAL shell getprop ro.product.model
adb -s REDACTED_P0110_USB_SERIAL shell getprop ro.product.device
adb -s REDACTED_P0110_USB_SERIAL shell getprop ro.build.version.release
adb -s REDACTED_P0110_USB_SERIAL shell getprop ro.build.version.sdk
adb -s REDACTED_P0110_USB_SERIAL reverse --list

device
nubia
P0110
pacific
16
36
```

`adb reverse --list` printed no `tcp:54321` mapping.

## Device Instrumentation Note

An attempted expansion of `ClipboardManagerInstrumentedTest` to six tests did
not produce a stable completed result on the connected device in this run. The
attempt was discarded from the code change. Existing retained no-Host Android
`ClipboardManagerInstrumentedTest` evidence therefore remains the 2026-09-05
`OK (5 tests)` package, and this evidence package only claims the new JVM
preview-policy boundary coverage above.
