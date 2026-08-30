# 2026-08-30 current-base external latency blocked evidence

Status: BLOCKED for USB/LAN glass-to-glass and input P95 latency closure, and
BLOCKED for `phase1-reconnect-within-3s`.
Device identity: not recorded in this directory because this owner record is
read-only and did not run a new device or camera measurement.
Owner worktree branch: codex/external-latency-owner-subagent-20260830.

## What this records

- Current base: origin/main `fe58cb6715cf203405820bd0eab352d0a93f56d9`.
- The latest retained latency preflight remains
  `docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-28-nubia-p0110-latency-current-base-blocked`.
  Its generated `latency-preflight.json` keeps all three README latency profiles
  blocked with `can_close_performance_gate=false`.
- The latest retained reconnect timing owner remains
  `docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked`.
  Its generated summary keeps `verdict=blocked`, `can_close_timing_gate=false`.
- A read-only owner test scans the repository for committed real-camera latency
  artifacts and fails if one appears under `docs/` outside fixtures without a
  corresponding owner update.

## Commands run

Only read-only git/status and unit-test commands were run for this evidence
record. No forbidden `/usr/bin/sfltool dumpbtm` command was executed.

```bash
pgrep -x sfltool || true
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_external_latency_current_base -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_latency_preflight -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_reconnect_timing -v
pgrep -x sfltool || true
```

Both sfltool process probes returned no matching process.

## Boundary

This record does not contain raw camera media, annotated latency samples,
synchronized-clock proof, LAN transport proof, physical input proof, or
reconnect timing observations. It must not be cited as a latency or reconnect
pass.
