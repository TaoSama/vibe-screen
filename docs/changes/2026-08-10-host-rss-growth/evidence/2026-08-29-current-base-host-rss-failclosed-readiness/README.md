# 2026-08-29 current-base Host RSS fail-closed readiness

Created: 2026-08-29T04:29:02Z
Refreshed: 2026-08-29T13:11:52Z after rebasing this evidence-only update onto
`origin/main` commit `7c7c2d43568cd452f7a430cbd9657bbada6be3ff`.

## Verdict

BLOCKED for formal Host RSS no-growth gate closure. This record refreshes the
current-base readiness state from a clean source tree. It does not include a
10-17 minute short diagnostic window, does not include a two-hour USB or LAN
soak, and does not close the README Phase 0 Host RSS no-growth gate.

## Readiness facts

- `pgrep -x sfltool || true` produced no output before readiness, after
  readiness, or after XCTest preflight; no residual `sfltool` process was
  observed.
- The readiness command was run without `--include-login-item-diagnostic`,
  `--inspect-login-items`, `--probe-login-item`, or `--probe-login-items`.
  The generated readiness JSON records `login_item.state=unverified` because
  the opt-in login-item probe was intentionally skipped.
- `baseline-macos-host-readiness` exited `2` from a clean `origin/main`
  checkout and wrote `status=blocked`, `can_start_host_rss_gate=false`,
  `host.current_source_commit=7c7c2d43568cd452f7a430cbd9657bbada6be3ff`,
  and `host.current_source_dirty=false`.
- Blocking conditions were: missing configured `Vibe Screen Dev` signing
  identity, failed codesign inspection for the installed Host WebRTC framework,
  no Host listener on TCP `54321`, missing virtual-HID entitlement, and
  unverified Launch at Login.
- `scripts/macos_dev_host.py xctest-preflight` exited `2` because the
  selected developer directory is Command Line Tools, not full Xcode, and
  XCTest is unavailable.

## Why no two-hour run was started

The formal `soak-2h-host-rss-gate` target requires a current-source Host PID
from a stable-signed, TCC-ready Host with native `VIBE_SCREEN_TELEMETRY_PATH`
coverage and an active USB or LAN stream. This environment has
`can_start_host_rss_gate=false`, so starting a two-hour collection would only
produce non-closing evidence.

## Verification completed

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_rss_gate tools.tests.test_soak_report tools.tests.test_phase0_stable_release tools.tests.test_file_transfer_android_smoke scripts.tests.test_macos_dev_host -v`
  passed 159 focused tests after rebasing onto latest `origin/main`.
- `make phase0-stable-release-gate` exited 0 and kept the aggregate blocked
  with README guard pass.
- `make phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1`
  exited nonzero as expected because `host_rss_2h_no_growth` and other release
  gates remain open or blocked.
- `git diff --check` passed, the retained evidence `SHA256SUMS` verified, and
  a changed-file sensitive-content scan returned only expected category labels
  and public commit/checksum hashes.

## Files

- `commands.txt` - sanitized command ledger and exit codes.
- `host-readiness.json` - structured macOS Host readiness report.
- `xctest-toolchain.json` - structured full-Xcode/XCTest preflight report.
- `SHA256SUMS` - checksums for retained evidence files.

## Required rerun

To close the Host RSS no-growth gate, first unblock stable signing, installed
Host integrity/provenance, Screen Recording/Accessibility TCC, listener
availability, and full-Xcode prerequisites. Then launch the matching
current-source Host with native telemetry enabled, establish a stable USB or LAN
stream, and run:

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
