# 2026-08-20 latency gates readiness: blocked

This record covers the current readiness state for the README external latency
gates on origin/main commit `b9d768e55c75f03cd3cb5d20939576bc8d24ff27`.

## Verdict

BLOCKED for formal performance-gate closure. The repository contains the
latency summarizer, provenance checker, tests, and synthetic fixtures, but this
worktree does not contain a real high-frame-rate external-camera evidence
package for any of these profiles:

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

No Android device action was run for this record. The missing dependency is the
external-camera or documented synchronized-clock measurement package, not an
ADB preflight. A future Android run must still use the exclusive Android device
lock and `adb -s EP0110PZ0B9110300B` when it involves the connected Nubia P0110.

## What was verified

- `tools/vibescreen_evidence/latency.py` and
  `tools/vibescreen_evidence/latency_evidence.py` were read with
  `docs/testing.md`, `docs/runbook/latency-measurement.md`, and the README gate
  wording.
- The standard-library test path passed because `pytest` is not installed in
  this environment: `PYTHONPATH=tools python3 -m unittest
  tools.tests.test_latency tools.tests.test_latency_evidence` ran 41 tests with
  zero failures.
- Synthetic fixture reruns confirm the expected fail-closed behavior:
  `pass` exits 0, `fail` and `insufficient` exit nonzero, telemetry-stage output
  remains informational, and the formal checker rejects a package with missing
  raw camera video even when sample rows alone would pass.
- A file scan found only synthetic latency fixtures under
  `tools/fixtures/latency/`; no real `manifest.json` plus `raw-camera` plus
  `samples` package exists under the repository outside fixtures.

## Artifacts

- `commands.txt`: commands used for the readiness check and their outcomes.
- `fixture-usb-glass-to-glass-pass-summary.json`: synthetic USB pass summary.
- `fixture-lan-glass-to-glass-fail-summary.json` and
  `fixture-lan-fail-exit.txt`: synthetic LAN threshold miss and nonzero exit.
- `fixture-input-p95-pass-summary.json`: synthetic input-latency pass summary.
- `fixture-usb-insufficient-summary.json` and
  `fixture-usb-insufficient-exit.txt`: synthetic sample-count insufficiency and
  nonzero exit.
- `fixture-telemetry-stage-summary.json`: telemetry-stage diagnostic summary
  with `gate.can_close_performance_gate=false`.
- `fixture-formal-valid-report.json`: synthetic formal provenance pass.
- `fixture-formal-missing-video-report.json` and
  `fixture-formal-missing-video-exit.txt`: formal checker result proving a
  missing raw camera artifact remains `insufficient`.

These fixture artifacts are toolchain evidence only. They are not real-device
latency evidence and must not be used to claim shipped USB, LAN, or input
latency performance.

## Required next evidence

For USB glass-to-glass, capture the Mac display and P0110 in one 120 FPS or
higher external-camera frame, annotate at least five visible stimulus/result
pairs into `samples.csv`, then run:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency "$EVIDENCE_DIR/samples.csv" \
  --kind glass-to-glass \
  --transport usb \
  --measurement-method external-camera \
  --gate-profile usb-glass-to-glass-sub50 \
  --run-id "$RUN_ID" \
  --output "$EVIDENCE_DIR/summary.json"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile usb-glass-to-glass-sub50 \
  --output "$EVIDENCE_DIR/latency-evidence-report.json"
```

For LAN, use `--transport lan` and `--gate-profile lan-glass-to-glass-sub80`.
For input latency, use `--kind input` and `--gate-profile input-p95-sub50`, with
the physical input actuation and visible Mac result in the same external-camera
timebase, or a documented synchronized-clock setup whose error budget is small
enough for the sub-50 ms P95 gate.

## Boundaries

- This record does not close `usb-glass-to-glass-sub50`,
  `lan-glass-to-glass-sub80`, or `input-p95-sub50`.
- Host/client telemetry-stage summaries remain useful diagnostics only; they do
  not replace external-camera or valid synchronized-clock evidence.
- Fixture passes remain synthetic and are scoped only to the CLI/toolchain.
