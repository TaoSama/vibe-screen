# 2026-08-25 Host RSS gate telemetry readiness

Created: 2026-08-25T00:00:00Z
Baseline: `origin/main` commit `fed8ac0c891b610def1cb03cb8bfd5216af56784`
Device checked: nubia P0110 / pacific / Android 16 / SDK 36

## Verdict

BLOCKED for Host RSS gate closure. This record strengthens the formal gate so a
future two-hour Host RSS pass also requires complete native Host stream
telemetry for the same exact window. It does not include a new current-source
two-hour USB or LAN soak and does not close the README Phase 0 Host RSS
no-growth gate.

## What changed

The formal `host_rss_gate` now consumes the `soak_report` exact-window output
alongside `summary.json` and `samples.jsonl`. A pass still requires the original
RSS no-growth criteria, and now also requires native
`VIBE_SCREEN_TELEMETRY_PATH` coverage that proves the stream remained active and
bounded during the same two-hour window. Missing exact-window telemetry, legacy
log-reencoded telemetry, partial reports, missing heartbeat, stale telemetry
coverage, queue over-capacity, encoder in-flight/registry over-capacity, latest
pixel-buffer over-capacity, frame queue drops, or an absent encoder all prevent
the gate from passing.

`soak_report` now derives the stream lifecycle counters that already exist in
Host telemetry: queue depth/capacity, encoder in-flight/capacity, callback
registry count, latest pixel-buffer retained/capacity, fallback capture state,
and encoder-present state.

## Current-source soak status

No two-hour soak was started from this task. The connected Android device was
available and identified as nubia P0110 / pacific / Android 16 / SDK 36, but
the environment was not controlled enough for a formal run: an Android test lock
was present, and existing Host processes were already running outside a fresh
current-source `VIBE_SCREEN_TELEMETRY_PATH` launch. Starting a two-hour run in
that state would risk producing ambiguous evidence, so the result is retained
as blocked/readiness evidence only.

## Historical evidence replay

The historical 2026-08-09 Xiaomi/fuxi two-hour soak was replayed through the
new gate using its retained `summary.json`, `samples.jsonl`, and
`soak-report.json`. The current gate returned `verdict=insufficient` with a
nonzero exit code. RSS criteria still show growth, and the older telemetry lacks
heartbeat and new lifecycle counters required for a telemetry-backed pass.

Key replay failures:

- `second_half_ols_slope_ci_upper_kib_per_minute` exceeded 40 KiB/min.
- `second_half_theil_sen_slope_kib_per_minute` exceeded 40 KiB/min.
- `second_half_endpoint_median_drift_kib` exceeded 4 MiB.
- `full_window_endpoint_median_drift_kib` exceeded 8 MiB.
- `heartbeat_present`, `accepted_heartbeat_present`, `queue_metrics_present`,
  `encoder_metrics_present`, `latest_pixel_buffer_metrics_present`, and
  `capture_state_booleans_present` were insufficient.

## Files

- `commands.txt` - command ledger for the readiness and replay checks.
- `preflight-output.txt` - retained raw command output for source baseline,
  explicit ADB identity, local lock files, running Host process discovery, and
  the fetched `origin/main` baseline refreshes.
- `historical-xiaomi-soak2h-current-gate.json` - current gate replay of the
  retained historical two-hour soak.
- `historical-xiaomi-soak2h-current-gate.exit` - replay exit code.

## Required rerun

To close the Host RSS no-growth gate, start a stable-signed current-source Host
with Screen Recording and Accessibility grants and native telemetry enabled,
then run the formal two-hour target:

```bash
export EVIDENCE_SERIAL='<lease-controlled-device-serial>'
export EVIDENCE_DIR='.build/evidence'
export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/soak-2h/host-telemetry.jsonl"
mkdir -p "$EVIDENCE_DIR/soak-2h"
# Launch the matching Host with that environment, establish a stable stream,
# then set HOST_PID to that Host process.
export HOST_PID='<current-source-host-pid>'
make soak-2h-host-rss-gate \
  EVIDENCE_SERIAL="$EVIDENCE_SERIAL" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  HOST_PID="$HOST_PID"
```

Only a complete `host-rss-gate.json` with `verdict=pass` can close the README
Phase 0 Host RSS no-growth gate.
