# 2026-08-28 current-base Host RSS fail-closed readiness

Created: 2026-08-28T12:10:00Z
Baseline: commit `3a81482b7350194a792408efae23f3a543ef2c3d` on branch `codex/host-rss-nogrowth-readiness`

## Verdict

BLOCKED for formal Host RSS no-growth gate closure. This record verifies the
current fail-closed tooling and current-source readiness state after the Host
RSS evidence-gate hardening changes. It does not include a real 10-17 minute
short diagnostic window, does not include a two-hour USB or LAN soak, and does
not close the README Phase 0 Host RSS no-growth gate.

## Readiness facts

- `pgrep -x sfltool || true` produced no output before, between, or after the
  readiness commands; no residual `sfltool` process was observed.
- `scripts/macos_dev_host.py readiness` was run without
  `--include-login-item-diagnostic`, `--inspect-login-items`,
  `--probe-login-item`, or `--probe-login-items`; the generated readiness JSON
  records `login_item.state=unverified` with an empty evidence list because the
  login-item probe was skipped.
- The readiness command exited `2` and wrote `status=blocked`,
  `can_start_host_rss_gate=false`, and `host.current_source_dirty=false`.
- The configured `Vibe Screen Dev` signing identity was not visible in the
  keychain, the installed Host lacks source commit/tree provenance, TCC grants
  could not be verified read-only, the installed Host is missing the virtual HID
  entitlement, and Launch at Login remains unverified.
- `scripts/macos_dev_host.py xctest-preflight` exited `2` because the selected
  developer directory is Command Line Tools, not full Xcode, and XCTest is not
  available.

## Tooling checks bound to this record

The same source commit adds fail-closed protections so automation cannot confuse
short or incomplete memory evidence with the formal two-hour gate:

- `host_memory_diagnostic` reports
  `gate.can_close_host_rss_no_growth_gate=false` on complete, partial, and
  failed reports.
- `host_rss_gate` now requires both a qualifying wall-clock window and a
  qualifying sample `elapsed_seconds` span. A wall-clock-stretched short window
  is `insufficient`.
- `real_device_gate --require-host-rss-gate` now requires
  `--host-rss-exact-window-report` and passes it through to the formal
  `host_rss_gate` evaluator, so real-device aggregation can consume the same
  telemetry-backed two-hour report as `make host-rss-gate`.

## Verification completed

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_real_device_gate tools.tests.test_host_rss_gate tools.tests.test_host_memory_diagnostic tools.tests.test_phase0_stable_release -v` passed 129 tests.
- `make evidence-tools-test` passed 1030 tests.
- `make phase0-stable-release-gate` kept the aggregate blocked with
  `readme_guard=pass`; blocking gates still include `host_rss_2h_no_growth`.

## Files

- `commands.txt` - sanitized command ledger and exit codes.
- `host-readiness.json` - structured macOS Host readiness report.
- `xctest-toolchain.json` - structured full-Xcode/XCTest preflight report.
- `SHA256SUMS` - checksums for retained evidence files.

## Required rerun

To close the Host RSS no-growth gate, unblock stable signing/TCC/provenance and
full-Xcode prerequisites, launch the matching current-source Host with native
telemetry enabled, establish a stable USB or LAN stream, and run:

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

Only a complete `host-rss-gate.json` with `verdict=pass` can close the README
Phase 0 Host RSS no-growth gate.
