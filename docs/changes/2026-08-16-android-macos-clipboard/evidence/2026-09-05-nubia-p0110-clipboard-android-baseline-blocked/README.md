# Nubia P0110 Clipboard Android Baseline Blocked

Date: 2026-09-05 (local, Asia/Shanghai; UTC 2026-09-04T17:20Z)
Source base: `origin/main` at `6a318241e7465b51e5ae84c91e8f18cfb4deed2d`
Branch: `codex/android-clipboard-current-baseline`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: blocked. Gate closed: false.

This package refreshes the Android-side current-base clipboard baseline for the
real Android `ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 USB/LAN
E2E gate. It proves local Android readiness only and does not prove either
system-pasteboard transfer direction.

## What Passed

- Android focused clipboard JVM tests passed locally, including protocol,
  approval-state, MainActivity boundary, managed-configuration, coordinator,
  and Internet clipboard coverage.
- Evidence-tool unit tests passed locally, including the new executed-test-count
  checks for Android clipboard logs.
- Android debug and androidTest APKs built successfully.
- The target device matched nubia P0110 / pacific / Android 16 / SDK 36.
- The run observed ADB reverse state with `adb reverse --list` only; no
  `tcp:54321` reverse was configured by this evidence pass.
- Android local `ClipboardManagerInstrumentedTest` passed on device with
  `OK (5 tests)`. The smoke now covers ordinary foreground text,
  instrumentation-argument set/read behavior, a 256 KiB UTF-8 Unicode text
  round trip, and safe handling of non-text Intent `ClipData`.
- The `clipboard-e2e-gate` aggregator preserved the blocked verdict while
  accepting the Android local smoke as `android_clipboardmanager_smoke=pass`.
- The gate parser now rejects Android clipboard logs that show only
  `BUILD SUCCESSFUL` or `OK (0 tests)` without any executed test count.

## Blockers

- Host readiness is blocked by missing stable `Vibe Screen Dev` signing
  identity, stale installed Host CodeResources entries, no Host listener on TCP
  `54321`, missing virtual HID entitlement, and unverified login/headless state.
- USB readiness is blocked because `adb reverse tcp:54321 tcp:54321` is not
  configured, the Android package is not installed/foreground for product
  preflight, the Mac Host is not listening on TCP `54321`, and Host
  stable-signing/TCC readiness failed.
- Trusted LAN readiness is blocked because the device Wi-Fi is not associated,
  `wlan0` has no IPv4 address or route to the Mac LAN candidate, and Host
  stable signing is blocked.
- No retained bidirectional product E2E record exists for Android
  `ClipboardManager` -> macOS `NSPasteboard` or macOS `NSPasteboard` ->
  Android `ClipboardManager`.

## Evidence Boundary

The Android instrumentation result proves foreground Android system clipboard
access on this P0110 only. The USB/LAN preflight files prove readiness state
only. This run did not start a signed Host/device Protocol v1 clipboard
session, did not exercise product clipboard UI actions against a Mac Host, did
not read or write macOS `NSPasteboard`, did not write a remote Android
`ClipboardManager` from macOS, and did not compare final marker text across both
systems. The P0110 evidence must not be relabeled as Xiaomi 13/fuxi evidence.

The Android local smoke intentionally uses a 256 KiB UTF-8 system clipboard
round trip. A protocol-size 1 MiB local Android `ClipboardManager` write was
attempted during development and hit Android Binder transaction-size limits on
the P0110, so it is not used as device smoke evidence. The Protocol v1 1 MiB
negotiated ceiling remains covered by offline JVM/protocol tests and does not
close the real system-pasteboard E2E gate.

## Artifacts

- `android-focused-jvm-tests.txt` - focused Android clipboard JVM output, exit
  0.
- `android-clipboard-instrumentation-adb.txt` - native instrumentation output
  with `OK (5 tests)`, used by the gate.
- `android-clipboard-instrumentation.txt` - Gradle connected test output showing
  `Finished 5 tests on P0110 - 16`.
- `device-info.json`, `adb-device.txt`, `adb-devices.txt`, `adb-manufacturer.txt`,
  `adb-model.txt`, `adb-release.txt`, `adb-sdk.txt` - sanitized device identity
  artifacts.
- `adb-reverse-list.txt` - read-only ADB reverse snapshot, showing no product
  `tcp:54321` reverse.
- `host-readiness.json`, `host-signing-and-permissions.txt` - blocked Host
  readiness snapshot.
- `usb-smoke-preflight.json`, `usb-host-preflight.txt` - blocked USB readiness
  snapshot.
- `trusted-lan-preflight.json`, `trusted-lan-preflight.txt` - blocked
  trusted-LAN readiness snapshot.
- `clipboard-e2e-gate.json` - sanitized gate output, verdict `blocked`.
- `evidence-tool-unittest.txt` - focused evidence tool unit tests, exit 0.
- `privacy-scan.json` - public evidence privacy scan.
- `commands.txt` - sanitized commands used for this current-base run.
- `SHA256SUMS` - artifact checksums.
