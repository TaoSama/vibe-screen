# Nubia P0110 Clipboard System Cap No-Host

Date: 2026-09-15 (Asia/Shanghai)
Source commit: `daeeb6a2c4aafccf4516002630001039afd29799`
Base commit: `737646a46e8c9772681e8a26502e62561e0e7033`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This no-Host run proves that the Android product policy preserves the Protocol
v1 1 MiB wire ceiling while limiting Mac-to-Android system clipboard writes to
the 320 KiB boundary already demonstrated on this device. Oversize 512 KiB and
1 MiB candidates are rejected by policy without calling
`ClipboardManager.setPrimaryClip`.

## Results

- `ClipboardManagerInstrumentedTest`: 9 tests, 0 failures, 0 errors, 0 skipped.
- 320 KiB UTF-8 text was written to and read from Android ClipboardManager.
- Empty clipboard clearing, ordinary text, 256 KiB Unicode text, non-text and
  multi-item ClipData behavior remained passing.
- The new policy test accepted the 320 KiB boundary and rejected 512 KiB and
  1 MiB candidates without performing those known unsafe Binder writes.
- Network clipboard offers remain non-empty by protocol; only the low-level
  Android system-write policy permits zero bytes for local clearing.

## Boundary

No Mac Host was started. No ADB reverse mapping or TCP 54321 listener existed
before or after the run. No macOS Screen Recording, Accessibility, Microphone,
or other TCC state was requested or changed.

This evidence does not prove Android ClipboardManager to macOS NSPasteboard or
the reverse direction. It does not close `clipboard_android_macos_product_e2e`
or the Phase 0 stable-release gate. It must not be relabeled as Xiaomi 13/fuxi
evidence.

## Command

```bash
ANDROID_SERIAL=REDACTED_P0110_USB_SERIAL ./gradlew --no-daemon --console=plain \
  :app:connectedDebugAndroidTest \
  '-Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ClipboardManagerInstrumentedTest'
```

## Artifacts

- `logs/clipboard-manager-instrumentation.xml`
- `logs/clipboard-manager-instrumentation.log`
- `logs/no-host-boundary.txt`
- `metadata/device-identity.txt`
- `metadata/source-provenance.txt`
