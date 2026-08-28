# P0110 USB E2E current-source evidence

Date: 2026-08-28
Source base: `origin/main` at `f5db90a761e158798065ce1078bf49428031ce49`
Branch: `codex/p0110-usb-e2e-current-source`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: partial pass with fail-closed blockers.

The current-source Android side built, installed, launched, and streamed over
USB through ADB reverse. Short live-smoke evidence passed before and after the
Android instrumentation uninstall/reinstall cycle. The retained smoke captured
positive stream telemetry, a Protocol v1 session epoch, HEVC hardware decode, a
first output frame, decoder counters, and zero reported dropped frames.

The run does not close full current-source USB E2E or any Host-dependent product
gate because the available macOS Host was not a current-source,
stable-signed/TCC-proven Host. Clipboard and file-transfer remain explicitly
blocked rather than inferred from offline coverage.

## Passed Evidence

- `android-gradle-check.txt`: `clean testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest` completed successfully.
- `android-install-launch.txt`: current debug APK installed, ADB reverse mapped
  TCP `54321`, and `dev.telemachus.display/.MainActivity` launched.
- `usb-live-smoke.json`: initial USB live smoke returned `verdict=pass`, with
  positive stream FPS and HEVC decode evidence.
- `android-clipboard-instrumentation.txt`: `ClipboardManagerInstrumentedTest`
  ran 3 tests on P0110 and the Gradle task exited `0`.
- `android-file-transfer-jvm.txt`: targeted file-transfer/session JVM tests
  exited `0`.
- `android-reinstall-relaunch.txt` and `usb-live-smoke-after-reinstall.json`:
  product APK reinstalled after instrumentation, relaunched, and produced
  another passing USB live smoke.

## Blocked Evidence

- `host-readiness.json`: `status=blocked` and
  `can_close_runtime_gates=false`; blockers include missing stable
  `Vibe Screen Dev` signing identity, installed Host source provenance missing,
  read-only TCC verification unavailable, missing virtual HID entitlement, and
  login/headless readiness not verified.
- `usb-smoke-preflight.json`: `result=blocked` because the macOS Host
  stable-signing/TCC preflight failed before strict USB E2E could be admitted.
- `clipboard-e2e-gate.json`: `verdict=blocked`, `gate_closed=false`; no retained
  bidirectional Android ClipboardManager <-> macOS NSPasteboard product-flow
  evidence exists.
- `file-transfer-current-source-gate.json`: `verdict=blocked`,
  `gate_closed=false`; no retained Android <-> macOS product file-transfer flow
  exists.
- `usb-live-smoke-after-relaunch.json`: retained as an insufficient side-effect
  record because Android instrumentation removed the product package before the
  relaunch check. The later reinstall/relaunch smoke is the valid post-test
  live-smoke evidence.

## Scope Boundary

This bundle is public-sanitized current-source evidence for nubia P0110 /
pacific / Android 16 / SDK 36 only. It must not be relabeled as Xiaomi 13/fuxi
evidence. It does not claim Host RSS no-growth, latency, native pointer HID,
stylus, controller, reconnect timing, clipboard E2E, file-transfer E2E, or
Phase 0 stable-release closure.

## Artifact Index

- `source-baseline.txt`: sanitized source branch and commit snapshot.
- `device-baseline.txt`: sanitized P0110 identity and ADB device state.
- `toolchain-preflight.txt`: local Android/ADB toolchain snapshot.
- `host-existing-state.txt`: sanitized existing Host process/listener and bundle state.
- `host-readiness-command.txt`, `host-readiness.exit`, `host-readiness.json`,
  `host-signing-and-permissions.txt`: Host readiness attempt and blockers.
- `android-gradle-check.txt`: Android build, lint, unit test, and APK output.
- `android-install-launch.txt`: APK install, ADB reverse, and Activity launch.
- `usb-smoke-preflight*.txt`, `usb-smoke-preflight*.exit`,
  `usb-smoke-preflight.json`: strict USB preflight attempt and blocked result.
- `usb-live-smoke*.txt`, `usb-live-smoke*.exit`, `usb-live-smoke*.json`: USB
  live-smoke commands and results.
- `android-clipboard-instrumentation.txt`,
  `android-clipboard-instrumentation.exit`: P0110 ClipboardManager local smoke.
- `android-file-transfer-jvm.txt`, `android-file-transfer-jvm.exit`: targeted
  file-transfer/session JVM coverage.
- `clipboard-e2e-gate.json`, `clipboard-e2e-gate.exit`: fail-closed clipboard
  E2E gate.
- `file-transfer-current-source-gate.json`: fail-closed file-transfer E2E
  summary.
- `privacy-scan.json`: repository privacy scan manifest.
- `SHA256SUMS`: checksums for the retained public bundle.

