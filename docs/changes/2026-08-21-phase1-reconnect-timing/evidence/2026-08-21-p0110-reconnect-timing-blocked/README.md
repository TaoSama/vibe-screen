# P0110 reconnect timing blocked readiness

This directory records a blocked readiness check for the Phase 1
reconnect-within-three-seconds timing gate. It is not a reconnect pass and must
not be used to close the README gate.

## Target

- Device target: Nubia P0110 / pacific / Android 16 / `EP0110PZ0B9110300B`
- Gate profile: `phase1-reconnect-within-3s`
- Required disruption scenarios: `client-kill`, `adb-reverse-disconnect`,
  `lan-network-interrupt`

## Blockers

The real Protocol v1 timing run was not started because the current Host
environment failed preflight:

- `macos-dev-host-preflight.txt` reports the `Vibe Screen Dev` signing identity
  is unavailable in the current keychain.
- `host-54321-listener.txt` records the `lsof -nP -iTCP:54321
  -sTCP:LISTEN` probe, exit status `1`, and no process listening on TCP
  `54321`.

No `adb -s EP0110PZ0B9110300B ...` disruption command was run for this blocked
record, so there is no client-kill, ADB reverse removal/restoration, or LAN
network-interruption timing sample.

## Summary

`reconnect-timing-summary.json` was generated with:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.reconnect_timing \
  --blocked \
  --target-device "Nubia P0110 / pacific / Android 16 / EP0110PZ0B9110300B" \
  --blocker "Vibe Screen Dev signing identity is unavailable in the current keychain" \
  --blocker "Host is not listening on 127.0.0.1:54321 in this worktree" \
  --artifact docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-21-p0110-reconnect-timing-blocked/host-54321-listener.txt \
  --artifact docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-21-p0110-reconnect-timing-blocked/macos-dev-host-preflight.txt \
  --notes "Blocked readiness record only; no real Protocol v1 reconnect timing attempt was run." \
  --output reconnect-timing-summary.json
```

The generated verdict is `blocked` and `can_close_timing_gate=false`.
