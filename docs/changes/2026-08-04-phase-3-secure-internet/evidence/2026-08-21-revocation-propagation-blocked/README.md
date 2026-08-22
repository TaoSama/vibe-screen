# Phase 3 Revocation Propagation Blocked Evidence

Date: 2026-08-21
Source branch: `codex/phase3-revocation-propagation`
Baseline commit: `22da26816465257b4a09f95de47be8567e448b74`

## Scope

This record captures the current status of the Phase 3 cross-service revocation
propagation gate. The local verifier contract is present and fail-closed, and the
existing process integration path now covers Authority-backed signaling sessions,
future relay credential rejection, and Authority coturn usage rejection for an
allocation admitted before session or device revocation.

This is not production or public-Internet evidence. No real deployed coturn
exporter, active-allocation disconnect executor, packet capture, or post-revoke
data-plane denial log was available in this workspace.

## Local Contract

The report in `revocation-propagation-blocked.json` intentionally omits the live
allocation teardown and stale credential/data-plane denial observations. Running
the verifier against it must return exit code `4` and status `blocked`:

```bash
python3 scripts/phase3/revocation_propagation_verifier.py \
  --report docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-21-revocation-propagation-blocked/revocation-propagation-blocked.json
```

## Remaining Gate

A passing run still requires a live Authority/signaling/relay/coturn deployment
that proves all of the following in one auditable report without storing secrets:

- an active coturn allocation existed before revocation;
- Authority revocation rejected the active signaling session;
- new relay credential admission was rejected;
- reuse of the already-issued TURN credential was rejected or expired before
  reuse;
- the active allocation was disconnected by a concrete deployment executor;
- post-revocation data-plane traffic relayed zero packets.
