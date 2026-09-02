# P0110 USB current-source evidence

Date: 2026-08-28
Base: `origin/main` / `f5db90a761e158798065ce1078bf49428031ce49`
Branch: `codex/p0110-usb-e2e-current-source`
Device: nubia P0110 / pacific / Android 16 / SDK 36
Serial label: `REDACTED_P0110_USB_SERIAL`

## Verdict

Status: partial pass with fail-closed E2E blockers.

The current-source Android client built, passed JVM/lint checks, installed on the
P0110 handset, launched through explicit `adb -s REDACTED_P0110_USB_SERIAL ...`
commands, and produced short USB live-smoke passes against the already running
macOS Host. The retained smoke evidence shows ADB reverse on TCP `54321`, the
product Activity in the foreground, positive stream FPS, session epoch 1, HEVC
hardware decode, first output frame, decoder counters, and zero reported dropped
frames.

The run does not close full current-source USB E2E, clipboard E2E,
file-transfer E2E, reconnect timing, host RSS, native pointer, stylus,
controller, or stable-release gates. Host readiness remains blocked because the
stable local `Vibe Screen Dev` codesigning identity was unavailable, the
installed Host lacks source commit/tree provenance, read-only TCC verification
could not prove the required grants, and the Host does not expose the virtual HID
entitlement.

This evidence is only nubia P0110 / pacific / Android 16 / SDK 36 evidence. It
must not be cited as Xiaomi 13/fuxi evidence.

## Evidence

Primary bundle:

- `evidence/2026-08-28-p0110-pacific-usb-e2e-current-source/README.md`

Key machine-readable outputs:

- `usb-live-smoke.json`: initial short USB live-smoke result, `verdict=pass`.
- `usb-live-smoke-after-reinstall.json`: post-instrumentation reinstall and
  relaunch USB live-smoke result, `verdict=pass`.
- `usb-smoke-preflight.json`: strict USB smoke preflight, `result=blocked` on
  Host stable-signing/TCC readiness.
- `host-readiness.json`: Host runtime prerequisite snapshot, `status=blocked`,
  `can_close_runtime_gates=false`.
- `clipboard-e2e-gate.json`: Android/macOS clipboard E2E gate,
  `verdict=blocked`, `gate_closed=false`.
- `file-transfer-current-source-gate.json`: file-transfer current-source summary,
  `verdict=blocked`, `gate_closed=false`.
- `privacy-scan.json`: public evidence privacy scan, `result=pass`.

## Commands

The retained command logs include the exact commands, with the hardware serial
redacted in public evidence. Device-affecting commands used the required
explicit serial form:

```sh
adb -s REDACTED_P0110_USB_SERIAL ...
```

The main checks were:

```sh
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest
adb -s REDACTED_P0110_USB_SERIAL install -r -t baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s REDACTED_P0110_USB_SERIAL reverse tcp:54321 tcp:54321
adb -s REDACTED_P0110_USB_SERIAL shell am start -n dev.telemachus.display/.MainActivity --ez auto_connect true
make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>
make evidence-usb-smoke-preflight EVIDENCE_SERIAL=REDACTED_P0110_USB_SERIAL EVIDENCE_DIR=<evidence-dir> EVIDENCE_EXPECTED_MANUFACTURER=nubia EVIDENCE_EXPECTED_MODEL=P0110 EVIDENCE_EXPECTED_DEVICE=pacific EVIDENCE_EXPECTED_ANDROID_RELEASE=16 EVIDENCE_EXPECTED_SDK=36
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.usb_live_smoke --serial REDACTED_P0110_USB_SERIAL --package dev.telemachus.display --port 54321 --allow-existing-device-lock --output <evidence-dir>/usb-live-smoke.json
./gradlew --no-daemon connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ClipboardManagerInstrumentedTest
adb -s REDACTED_P0110_USB_SERIAL shell am force-stop dev.telemachus.display.test
adb -s REDACTED_P0110_USB_SERIAL uninstall dev.telemachus.display.test
adb -s REDACTED_P0110_USB_SERIAL shell pm list packages dev.telemachus.display.test
./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.protocol.FileTransferSessionTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest --tests dev.telemachus.display.StreamProtocolActionDispatcherTest
make clipboard-e2e-gate EVIDENCE_DIR=<evidence-dir>
python3 scripts/phase3/evidence_privacy.py --evidence-dir <evidence-dir> --output <evidence-dir>/privacy-scan.json
```

`pgrep -x sfltool || true` was run at the start, around key tests, and before
the final verification. No `sfltool` process was observed in the retained
console output, and no forbidden `forbidden login-item diagnostic command` or login-item diagnostic
flags were used.

## What Passed

- Android current-source build, lint, JVM unit tests, debug APK, and debug
  androidTest APK completed successfully.
- P0110 device identity matched nubia P0110 / pacific / Android 16 / SDK 36.
- Current debug APK installed and relaunched successfully after instrumentation.
- ADB reverse retained `tcp:54321 tcp:54321`.
- Short USB live-smoke observed a running foreground client, positive stream
  telemetry, HEVC hardware decoder `c2.qti.hevc.decoder`, 1920x1080 video, first
  output frame, decoder counters, and zero reported dropped frames.
- Android local ClipboardManager instrumentation passed 3 tests on P0110.
- Targeted Android file-transfer/session JVM coverage passed.
- The public evidence bundle passed the repository privacy scanner.

## Blockers And Boundaries

- The macOS Host available during the run was an existing installed application,
  not a rebuilt current-source Host with embedded source commit/tree provenance.
- `make baseline-macos-host-readiness` exited `2`; Host readiness is blocked.
- `make evidence-usb-smoke-preflight` exited `2`; strict USB E2E preflight is
  blocked by Host signing/TCC readiness.
- The live product session did not negotiate clipboard or file-transfer in the
  retained run, so clipboard/file-transfer controls and bidirectional product
  transfers were not proven.
- `clipboard-e2e-gate.json` intentionally remains blocked because no retained
  Android ClipboardManager <-> macOS NSPasteboard product-flow evidence exists.
- `file-transfer-current-source-gate.json` intentionally remains blocked because
  no retained Android <-> macOS product file-transfer flow exists.
- One relaunch smoke after `connectedDebugAndroidTest` is retained as
  insufficient because instrumentation removed the product package; the later
  reinstall/relaunch smoke passed. This is not counted as a reconnect timing
  pass.
- `connectedDebugAndroidTest` or direct `am instrument` runs must clean up the
  Android test package after every terminal state by force-stopping, uninstalling,
  and verifying the absence of `dev.telemachus.display.test`. The cleanup must not
  target the product package/data or existing ADB reverse mappings. A later Nubia
  cross-package launch confirmation for the `.test` package is Android instrumentation residue,
  not evidence of macOS Screen Recording or Accessibility/TCC regression.
