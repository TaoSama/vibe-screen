# Phase 3 Internet Soak Blocked Evidence

Date: 2026-08-21
Source branch: `codex/phase3-internet-soak`
Baseline commit: `22da26816465257b4a09f95de47be8567e448b74`

## Scope

This record captures the current status of the Phase 3 public Internet soak gate
from this workspace. The repository now has a fail-closed composition checker for
the complete gate, but no public deployment inputs or privacy-reviewed runtime
reports were available here.

The gate is intentionally broader than any one preflight. A pass requires all of
these reports from the same source revision and run boundary:

- public remote TURN verification with an independently reachable peer;
- real ScreenCaptureKit-to-Android media continuity;
- network handoff recovery with stale media rejection and no plaintext fallback;
- revocation propagation through Authority, signaling, relay credential issuance,
  active coturn allocation disconnect, and post-revocation packet denial;
- a two-hour mixed direct/relay soak with sufficient samples and metric families.

## Result

`phase3-internet-soak-gate.json` is `blocked`. It does not close a release gate.
Missing deployment, TLS, secret, remote peer, media, handoff, revocation, duration,
and sample evidence is recorded as blocked rather than inferred from local
loopback, local coturn, or synthetic Protocol v1 evidence.

## Reproduce

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m \
  vibescreen_evidence.phase3_internet_soak gate \
  --output docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-21-internet-soak-blocked/phase3-internet-soak-gate.json \
  --blocked-reason "public TURN deployment, TLS/secret material, independent remote peer, real media continuity, network handoff, revocation propagation, and two-hour mixed-route soak evidence are unavailable in this workspace" \
  --allow-blocked
```

## Remaining Gate

A future pass must provide the full evidence bundle named by the manifest and run
the same gate without `--allow-blocked`. The bundle must pass the privacy scanner
before it is archived in the repository; raw endpoints, device identifiers, TURN
passwords, bearer tokens, private keys, and private logs stay outside tracked
evidence.
