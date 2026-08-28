# 2026-08-28 Nubia P0110 File-Transfer Current-Source Blocked Refresh

Device: nubia P0110 / pacific / Android 16 / SDK 36.
Serial label: `REDACTED_P0110_USB_SERIAL`.
Branch: `codex/p0110-file-transfer-e2e-gate`.
Current-base source commit: `e90463e5d24ee055686a9b6d3a1acd02c616b81b`.

## Verdict

`blocked.json` reports `result=blocked`, `gate_closed=false`, and
`can_close_file_transfer_android_smoke_gate=false`. This evidence does not prove
Android -> macOS or macOS -> Android product file transfer.

The refreshed P0110 Android instrumentation smoke passed for the file-transfer
control-bar entry point: `android-file-transfer-instrumentation.txt` records
`OK (2 tests)`. Those tests verify that the file-transfer control remains
visible, labelled, clickable, and non-overlapping at phone widths when shown,
and that the production layout applier accounts for the extra action in
COMPACT, INLINE, STACKED, and COLUMN mode decisions.

## Blockers

- Host readiness is blocked. A Host listener was observed on TCP 54321, but the
  installed Host is not accepted as current-source stable-signing/TCC evidence:
  the stable `Vibe Screen Dev` signing identity is unavailable to the preflight,
  installed Host source provenance is missing, TCC cannot be verified read-only,
  the virtual HID entitlement is absent, and login/headless readiness remains
  `unverified`.
- USB preflight is blocked by the same Host signing/TCC prerequisite. The P0110
  device identity and ADB reverse were present, but the transport gate cannot
  pass without a ready current-source Host.
- No trusted-LAN preflight was collected for this bundle.
- No `file-transfer-product-e2e.json` exists for this run, so there is no
  retained evidence for file offer/request/content packets, explicit sender
  action, receiver approval, destination file write, positive session epoch,
  final SHA-256 equality, or cancel cleanup.

## Safety

`pgrep -x sfltool || true` returned no output at the start of the owner run and
again before final packaging. No `/usr/bin/sfltool dumpbtm` command was run, and
the readiness command used the default path without
`--include-login-item-diagnostic`, `--inspect-login-items`,
`--probe-login-item`, or `--probe-login-items`.

## Artifacts

- `blocked.json` - fail-closed file-transfer Android smoke gate summary.
- `host-readiness.json` and `host-signing-and-permissions.txt` - read-only
  macOS Host readiness output.
- `usb-smoke-preflight.json` - P0110 USB preflight output with redacted serial.
- `android-file-transfer-instrumentation.txt` - P0110 focused Android
  instrumentation log.
- `android-focused-jvm-tests.txt` - focused Android JVM file-transfer and
  layout policy tests.
- `android-install-debug-test.log` - androidTest build/install log for P0110.
- `protocol-tests.txt` - Protocol fixture and shared-model tests.
- `macos-host-swift-build.txt` - MacHost SwiftPM build.
- `macos-host-file-transfer-xctest-attempt.txt` - blocked MacHost XCTest
  attempt; local paths are redacted.
- `file-transfer-gate-unit-tests.txt` - unit coverage for the fail-closed gate.
- `commands.txt` - sanitized command ledger.
- `SHA256SUMS` - artifact checksums.
