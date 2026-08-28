# 2026-08-27 current-base Host RSS readiness blocked

Created: 2026-08-27T10:39:02+08:00
Baseline: `origin/main` commit `77441edf982a15101bf9fe15f44a49af74b16b9d`, plus retained readiness-probed PR source commit `afca8bc7246a8056bffba35ccfe07e2fbfe51833` on branch `codex/host-rss-current-base-build-fix`. The final PR refresh rebases the same blocked readiness record onto the newer current base and re-runs local offline gates; it does not rerun or close the formal Host RSS gate.
Device checked: nubia P0110 / pacific / Android 16 / SDK 36

## Verdict

BLOCKED for Host RSS no-growth gate closure. This record does not contain a
new two-hour USB or LAN soak and does not close the README Phase 0 / Protocol v1
Host resident-memory no-growth gate. The formal gate remains open until a
complete `host_rss_gate` evaluation reports `verdict=pass` for a continuous
current-source two-hour run.

## What changed before readiness

The current `origin/main` MacHost Protocol v1 sources did not build because
`StreamingServer` and self-tests referenced the multi-client display routing
surface after it had disappeared from `ProtocolV1Session.swift`. This PR
restores the host-side Protocol v1 display router, resource-limit
advertisement/negotiation, session route cleanup, and stream-target validation
without changing the soak gate criteria. Follow-up commits also fix current-base
release gate blockers for iOS native-input readiness, Harmony/Phase 3 contract
validation, and the macOS dev-host preflight alias used by CI.

## Verification

- `make baseline-macos-build` passed.
- `make baseline-macos-self-test` passed, including Protocol v1 multi-client
  routing, epoch, targeted input, graceful disconnect, error, and media checks.
- `make release-tools-test` passed: 230 tests.
- `make phase3-test` passed.
- `make protocol` passed.
- `make evidence-tools-test` passed.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_rss_gate tools.tests.test_soak_report tools.tests.test_soak tools.tests.test_host_memory_diagnostic -v` passed: 102 tests.
- `cd baseline/MacHost && swift test --filter ProtocolV1SessionTests` was
  attempted, but this local toolchain cannot compile XCTest (`no such module
  'XCTest'`). The release build and built-in MacHost self-test are the retained
  local Swift verification.

## Readiness result

After updating the PR to source commit `afca8bc7246a8056bffba35ccfe07e2fbfe51833`,
the Host readiness probe was rerun from a clean branch state before this
evidence refresh. It reported
`status=blocked`, `can_start_host_rss_gate=false`, and
`current_source_dirty=false`.

Blocking conditions retained by the readiness probe:

- `codesign identity 'Vibe Screen Dev' not found in the keychain`.
- Installed Host lacks source commit/tree provenance and must be rebuilt through
  the packaging flow before formal evidence.
- TCC permissions cannot be verified read-only from this environment.
- Installed Host is missing `com.apple.developer.hid.virtual.device`.
- Login/headless readiness is blocked because Launch at Login is unverified.
- Login/headless readiness is also blocked because no active display is visible
  to the current WindowServer session.

The readiness probe observed an existing listener on TCP port `54321`, but that
does not prove a fresh current-source Host launched with
`VIBE_SCREEN_TELEMETRY_PATH`, and it is insufficient for formal Host RSS gate
closure.

## Files

- `commands.txt` - command ledger for source refresh, build fix, local
  verification, and readiness checks.
- `readiness-summary.json` - manually redacted summary of the clean-branch
  readiness result.

## Required rerun

To close the Host RSS no-growth gate, unblock the signing/TCC/provenance
preconditions, launch a stable-signed current-source Host with native telemetry
enabled, then run the formal target against the leased Android device:

```bash
export EVIDENCE_SERIAL='<lease-controlled-device-serial>'
export EVIDENCE_DIR='.build/evidence'
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
mkdir -p "$EVIDENCE_DIR/soak-2h"
# Launch the matching Host with that environment, establish a stable stream,
# then set HOST_PID to that current-source Host process.
export HOST_PID='<current-source-host-pid>'
make soak-2h-host-rss-gate \
  EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  HOST_PID="$HOST_PID"
```

Short runs, historical Xiaomi evidence, offline self-tests, or readiness
records cannot close this gate.
