# Phase 3 Revocation Propagation Current-Base Blocked Evidence

Date: 2026-08-23
Source branch: codex/phase3-revocation-current-base
Rebased baseline: d3c62b25

## Scope

This record captures the current-base status of the Phase 3 cross-service
revocation propagation gate. The local control-plane path covers
Authority-backed signaling sessions, future relay credential rejection, and
same-allocation relay credential retry rejection, plus Authority coturn usage
rejection for allocations admitted before session or device revocation.
The branch was rebased onto `origin/main` commit `d3c62b25`; the report is a
blocked readiness artifact for the local PR source tree, not a release-pass
artifact.

This is not production or public-Internet evidence. No real deployed coturn
exporter, active-allocation disconnect executor, packet capture, or post-revoke
data-plane denial log was available in this workspace.

## Local Contract

The report in revocation-propagation-current-base-blocked.json intentionally
omits the live allocation teardown and stale credential/data-plane denial
observations, does not claim pre-revocation media/data-plane traffic, and does
not claim a separately inspected Authority audit log.
Running the verifier against it must return exit code 4 and status blocked:

    python3 scripts/phase3/revocation_propagation_verifier.py \
      --report docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-23-revocation-propagation-current-base-blocked/revocation-propagation-current-base-blocked.json

## Remaining Gate

A passing run still requires a live Authority/signaling/relay/coturn deployment
that proves all of the following in one auditable report without storing secrets:

- an active coturn allocation existed before revocation;
- Authority revocation rejected the active signaling session;
- the Authority revocation audit event was inspected;
- signaling long-poll woke and failed closed;
- new relay credential admission was rejected;
- same-allocation relay credential retry was rejected;
- reuse of the already-issued TURN credential was rejected or expired before
  reuse;
- the active allocation was disconnected by a concrete deployment executor;
- post-revocation data-plane traffic relayed zero packets.
