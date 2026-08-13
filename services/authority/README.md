# Phase 3 production authority slice

`vibe-authority` is the shared PostgreSQL control-plane authority for Phase 3.
It owns pseudonymous account/device admission, monotonic device revocation,
short-lived signaling-session admission, relay-allocation reservations, and
coturn cumulative usage reconciliation. It never receives screen/input payloads
or application traffic keys.

This service replaces process-local admission decisions. It does not replace the
existing signaling message broker or coturn data plane: those services call this
internal API before returning a session or TURN credential. Production callers
must fail closed when the authority is unavailable.

## Run locally

Requirements are Go 1.23+ and PostgreSQL 15+.

```bash
cd services/authority
cp config.example.json config.json
export VIBE_AUTHORITY_DATABASE_URL='postgres://authority@127.0.0.1/vibescreen?sslmode=require'
export VIBE_AUTHORITY_ADMIN_TOKEN="$(openssl rand -base64 48)"
export VIBE_AUTHORITY_SIGNALING_TOKEN="$(openssl rand -base64 48)"
export VIBE_AUTHORITY_RELAY_TOKEN="$(openssl rand -base64 48)"
export VIBE_AUTHORITY_COTURN_TOKEN="$(openssl rand -base64 48)"
export VIBE_AUTHORITY_ROLE_TOKEN_SECRET="$(openssl rand -base64 48)"
go run ./cmd/vibe-authority --config config.json --migrate migrations/001_authority.sql
go run ./cmd/vibe-authority --config config.json
```

Migration execution is an explicit one-shot operation. Application replicas
must not receive DDL permission. Back up the database and record the migration
checksum before applying it.

## Internal API

Tokens are independent and route-scoped:

- admin: `PUT /v1/accounts/{id}`, account suspension, device registration and
  monotonic device revocation;
- signaling: create/invalidate a signaling admission and introspect a role
  token;
- relay: reserve an allocation before issuing its TURN credential;
- coturn collector: ingest cumulative allocation counters and submit source
  snapshots for reconciliation.

All JSON decoders reject unknown fields/trailing values and cap request bodies.
Identifiers are pseudonymous ASCII tokens, not email addresses, hardware serials
or raw account names.

Create a scoped signaling admission:

```json
{
  "request_id": "01J-AUTHORITY-RETRY",
  "account_id": "acct_Ep8",
  "host_device_id": "host_Fm2",
  "client_device_id": "device_Qk9",
  "session_epoch": 19,
  "ttl_seconds": 300
}
```

The authority derives stable per-session role tokens from the secret and
session ID, so an exact idempotency replay returns the same credentials without
storing raw bearer tokens. A changed request with the same request ID is `409`.
Every authorization rechecks account/device/session tombstones and expiry.

Reserve relay capacity before returning a TURN credential:

```json
{
  "device_id": "device_Qk9",
  "session_id": "session_Wc4",
  "allocation_id": "allocation_7",
  "source_id": "turn_sin_1"
}
```

The reservation and quota checks are one serializable transaction. Every path
locks account before device, so account suspension/device revocation and new
admission have one deny-wins ordering across replicas.

## Coturn ingestion contract

`POST /v1/coturn/usage` accepts a machine-generated event containing
`source_id`, stable `event_id`, `allocation_id`, device/session IDs, a strictly
increasing `sequence`, cumulative ingress/egress counters, `observed_at`, and a
`closed` flag. Event retries are idempotent. Counter or sequence regression is
`409`; actual usage is recorded even after device revocation or after it exceeds
quota, because billing facts cannot be discarded. Revocation only forbids new
admission.

`POST /v1/coturn/reconcile` accepts one source snapshot (maximum 10,000
allocations), applies newer counters, and returns ledger allocations missing
from a source beyond `reconciliation_grace_seconds`. The response separately
lists `unauthorized_allocation_ids` that exist only at the source and
`conflict_allocation_ids` whose identity or counters conflict with the ledger;
one conflict does not stop processing the rest of the snapshot. Operators must
disconnect unauthorized allocations and close ledger-only allocations only after
the configured consecutive-snapshot policy in their collector.

The repository does **not** yet contain a production-proven coturn exporter.
Launch remains blocked until the pinned coturn build or provider API proves it
exports a stable allocation ID, the complete REST username mapping, monotonic
cumulative counters, close events, boot identity and snapshot support. Parsing
human-oriented coturn logs may run in shadow mode but is not an authoritative
quota or billing source.

## Production gates

- managed PostgreSQL multi-AZ deployment, TLS, PITR and restore exercise;
- migration checksum/required-schema readiness and database credentials from a
  secret manager;
- signaling and relay integration that fails closed on authority errors;
- collector durable cursor/WAL, node heartbeat, gap detection and two-snapshot
  close reconciliation;
- mapping from issued allocation IDs to complete coturn REST usernames;
- active-allocation disconnect executor and outbox delivery;
- edge authentication, DDoS/rate limiting, audit retention/deletion policy,
  dashboards, cost reconciliation and public-region canaries.

Until these gates pass, this is a runnable backend slice, not evidence of a
production Internet deployment.
