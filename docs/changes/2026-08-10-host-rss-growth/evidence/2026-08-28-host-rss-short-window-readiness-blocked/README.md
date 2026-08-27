# 2026-08-28 Host RSS short-window regression readiness: blocked

Created: 2026-08-27T16:18:20Z
Baseline: `origin/main` commit `27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`
Worktree: `codex/host-rss-short-window-regression`

## Verdict

BLOCKED for a real Host RSS short-window regression pass. This record verifies
the current diagnostic path and its fail-closed behavior, but it does not close
the short Host memory diagnostic gate and does not close the formal two-hour
Host RSS no-growth gate.

No stable-signed current-source Host was launched with
`VIBE_SCREEN_TELEMETRY_PATH`, no USB/LAN stream window was collected, and no
formal two-hour `host_rss_gate` run was started.

## Readiness facts

- `pgrep -x sfltool || true` produced no output before the run; no residual
  `sfltool` process was observed.
- `scripts/macos_dev_host.py readiness` was run without
  `--include-login-item-diagnostic`, `--inspect-login-items`, or
  `--probe-login-items`; the generated readiness JSON records
  `login_item.state=unverified` and `sfltool_dumpbtm_was_run=false`.
- The readiness command exited `2` and wrote `status=blocked` with
  `can_start_host_rss_gate=false`.
- The configured `Vibe Screen Dev` signing identity was not visible in the
  keychain, and the installed Host lacks current-source commit/tree provenance.
- TCC permission state could not be verified read-only from the local databases;
  `screen_recording_granted=false` and `accessibility_granted=false` are
  retained as blocked readiness.
- No Host listener was observed on TCP port `54321`, and the installed Host did
  not expose the virtual HID entitlement.
- `xcode-select -p` pointed at `/Library/Developer/CommandLineTools`;
  `xcrun --find xctest` exited `72`, and the repository XCTest preflight
  reported full Xcode as unavailable.

## Diagnostic path check

The documented short-window entry point is:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_memory_diagnostic \
  --host-pid "$HOST_PID" \
  --duration-seconds 900 \
  --interval-seconds 30 \
  --telemetry-jsonl .build/evidence/memory-short/host-telemetry.jsonl \
  --samples .build/evidence/memory-short/samples.jsonl \
  --output .build/evidence/memory-short/diagnostic.json
```

Because the required Host telemetry file was absent, a minimal fail-closed probe
against the shell process wrote `failclosed-diagnostic.json`, exited `1`, and
reported:

- `verdict`: `insufficient`
- `attribution`: `inconclusive`
- `error`: `host telemetry file does not exist`
- `sufficiency.stream_telemetry`: `false`
- `sufficiency.collection_complete`: `false`

This confirms the diagnostic does not silently pass without native
`VIBE_SCREEN_TELEMETRY_PATH` coverage. The probe is not a real short-window Host
memory run.

## Verification completed

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_memory_diagnostic -v`
  passed 62 tests.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_macos_dev_host -v`
  passed 57 tests, including default login-item skip and explicit opt-in tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_host_rss_gate -v`
  passed 22 tests, including short-window rejection for the formal two-hour
  gate and exact-window telemetry fail-closed cases.
- `python3 scripts/macos_dev_host.py xctest-preflight --report ...` exited `2`
  and recorded that full Xcode/xcodebuild are unavailable.

## What was not run

- `/usr/bin/sfltool dumpbtm` was not run.
- `--include-login-item-diagnostic`, `--inspect-login-items`, and
  `--probe-login-items` were not used.
- No stable-signed current-source Host bundle was built, installed, or launched.
- No 10-17 minute real Host memory diagnostic window was collected.
- `make soak-2h-host-rss-gate` was not run.

## Files

- `commands.txt` - command ledger for process check, readiness, fail-closed
  probe, host memory tests, formal Host RSS gate tests, and XCTest preflight.
- `host-readiness.json` - raw `macos_dev_host.py readiness` output.
- `failclosed-diagnostic.json` - raw short diagnostic failure report for missing
  Host telemetry.
- `readiness.json` - summarized machine-readable evidence for this blocked
  README gate owner run.
- `test-macos-dev-host-command.txt` - focused macOS Host readiness unit-test log.
- `xctest-toolchain.txt` - read-only full-Xcode/XCTest preflight output.
- `SHA256SUMS` - checksums for retained evidence files.

## Required rerun

For a real short-window regression result, select full Xcode, install or launch
a stable-signed current-source Host with Screen Recording and Accessibility
grants, set native telemetry, establish a USB or LAN stream, then run:

```sh
export EVIDENCE_DIR=.build/evidence/memory-short
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/host-telemetry.jsonl"
# Launch the matching Host with that environment and set HOST_PID to its PID.
PYTHONPATH=tools python3 -m vibescreen_evidence.host_memory_diagnostic \
  --host-pid "$HOST_PID" \
  --duration-seconds 900 \
  --interval-seconds 30 \
  --telemetry-jsonl "$EVIDENCE_DIR/host-telemetry.jsonl" \
  --samples "$EVIDENCE_DIR/samples.jsonl" \
  --output "$EVIDENCE_DIR/diagnostic.json"
```

For formal gate closure, retain a complete two-hour run and evaluate it with:

```sh
make soak-2h-host-rss-gate \
  EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  HOST_PID="$HOST_PID"
```

Only a complete `host-rss-gate.json` with `verdict=pass` can close the README
Phase 0 Host RSS no-growth gate.
