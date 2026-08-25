# Phase 3 Revocation Propagation Current-Base Blocked Evidence

Date: 2026-08-25
Source branch: codex/phase3-revocation-propagation-current-base
Rebased baseline: c754f2dab4d3781847b40988105fcdefe1723538
Source commit: recorded by the `git rev-parse HEAD` command in `commands.txt` before checks run; the command log is intentionally pinned by the full baseline SHA and clean-worktree assertion rather than a self-referential commit literal.

## Scope

This record captures the current-base status of the Phase 3 cross-service
revocation propagation gate after adding bounded signaling reauthorization,
Authority-admitted relay usage ingestion, a relay allocation registry, and a
local coturn CLI control helper. The result is a blocked readiness artifact for
the local PR source tree, not a release-pass artifact.

The local service tests cover Authority-backed signaling denial after session and
device revocation, long-poll reauthorization during a pending wait, future relay
credential rejection, post-revocation same-allocation credential retry rejection, relay
`/v1/usage` Authority admission and post-revocation rejection, restart-safe
allocation-registry persistence, and strict coturn CLI helper mapping.

This is not production or public-Internet evidence. No real deployed coturn
exporter, production scheduler, active-allocation disconnect executor, stale
issued TURN credential reuse denial, packet capture, or post-revocation
data-plane denial log was available in this workspace.

## Local Contract

The report in `revocation-propagation-current-base-blocked.json` intentionally
omits the live allocation teardown and stale credential/data-plane denial
observations, does not claim pre-revocation media/data-plane traffic, and does
not claim a separately inspected Authority audit log. Running the verifier
against it must return exit code 4 and status `blocked`:

```bash
python3 scripts/phase3/revocation_propagation_verifier.py \
  --report docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-25-revocation-propagation-current-base/revocation-propagation-current-base-blocked.json \
  --write-summary docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-25-revocation-propagation-current-base/revocation-propagation-current-base-summary.json
```

## Remaining Gate

A passing run still requires a live Authority/signaling/relay/coturn deployment
that proves all of the following in one auditable report without storing secrets:

- an active coturn allocation existed before revocation;
- Authority revocation rejected the active signaling session;
- the Authority revocation audit event was inspected;
- signaling long-poll woke and failed closed;
- new relay credential admission was rejected;
- post-revocation same-allocation relay credential retry was rejected;
- reuse of the already-issued TURN credential was rejected or expired before
  reuse;
- the active allocation was disconnected by a concrete deployment executor;
- post-revocation data-plane traffic relayed zero packets.
