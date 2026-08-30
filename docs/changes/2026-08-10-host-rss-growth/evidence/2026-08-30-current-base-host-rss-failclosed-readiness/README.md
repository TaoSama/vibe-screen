# 2026-08-30 current-base Host RSS fail-closed readiness

Created: 2026-08-30

## Verdict

BLOCKED for the formal Host RSS no-growth gate closure. This record refreshes
the current-base readiness state from a clean `origin/main` checkout at commit
`87e16d8bea4446c1ca449045678f1bafc7fd6cb2`. It does not include a 10-17 minute
short diagnostic window, does not include a two-hour USB or LAN soak, and does
not close the README Phase 0 Host RSS no-growth gate.

## Readiness facts

- `pgrep -x sfltool || true` produced no output before and after the checks; no
  residual `sfltool` process was observed.
- The readiness command was run without `--include-login-item-diagnostic`,
  `--inspect-login-items`, `--probe-login-item`, or `--probe-login-items`.
  `login_item.state=unverified` and `sfltool_dumpbtm_was_run=false`.
- `baseline-macos-host-readiness` exited `2` from a clean source checkout and
  wrote `status=blocked`, `can_start_host_rss_gate=false`,
  `host.current_source_commit=87e16d8bea4446c1ca449045678f1bafc7fd6cb2`,
  and `host.current_source_dirty=false`.
- Blocking conditions were: missing configured `Vibe Screen Dev` signing
  identity, failed codesign inspection for the installed Host WebRTC
  framework, no Host listener on TCP `54321`, missing virtual-HID entitlement,
  and unverified Launch at Login.
- `scripts/macos_dev_host.py xctest-preflight` exited `2` because the selected
  developer directory is Command Line Tools, not full Xcode, and XCTest is
  unavailable.

## Why no two-hour run was started

The formal `soak-2h-host-rss-gate` target requires a current-source Host PID
from a stable-signed, TCC-ready Host with native `VIBE_SCREEN_TELEMETRY_PATH`
coverage and an active USB or LAN stream. This environment has
`can_start_host_rss_gate=false`, so starting a two-hour collection would only
produce non-closing evidence. The retained 2026-08-09 Xiaomi two-hour soak is
historical evidence that showed host RSS growth and is not a current-source
pass; short diagnostic windows and partial summaries cannot close this gate.

## Files

- `commands.txt` - sanitized command ledger and exit codes.
- `readiness.json` - structured blocked/fail-closed evidence summary.
- `host-readiness.json` - raw macOS Host readiness report.
- `host-signing-and-permissions.txt` - raw Host signing/TCC text report.
- `readiness.stdout` and `readiness.stderr` - raw command output from the
  blocked Host readiness run.
- `xctest-toolchain.json` - structured full-Xcode/XCTest preflight report.
- `xctest-toolchain.txt` - text confirmation from the XCTest preflight.
- `SHA256SUMS` - checksums for retained evidence files.

## Required rerun

To close the Host RSS no-growth gate, first unblock stable signing, installed
Host integrity/provenance, Screen Recording/Accessibility TCC, listener
availability, and full-Xcode prerequisites. Then launch the matching
current-source Host with native telemetry enabled, establish a stable USB or
LAN stream, and run:

```bash
export EVIDENCE_SERIAL='<lease-controlled-device-serial>'
export EVIDENCE_DIR='.build/evidence'
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
export HOST_PID='<current-source-host-pid>'
make soak-2h-host-rss-gate \
  EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  HOST_PID="$HOST_PID"
```

Only a complete `host-rss-gate.json` with `verdict=pass`, backed by the same
exact-window `soak_report`, can close the README Phase 0 Host RSS no-growth
gate.
