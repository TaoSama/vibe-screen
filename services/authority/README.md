# Phase 3 production authority slice

`vibe-authority` is the shared PostgreSQL control-plane authority for Phase 3.
It owns pseudonymous account/device admission, monotonic device revocation,
short-lived signaling-session admission, relay-allocation reservations, and
coturn cumulative usage reconciliation. It never receives screen/input payloads
or application traffic keys.

This service replaces process-local admission decisions. It does not replace the
existing signaling message broker or coturn data plane. Signaling can call this
internal API before returning a session or when adopting an admin-issued session
profile, and relay credential admission can call it before returning TURN
credentials. Production callers must fail closed when the authority is
unavailable.

The signaling service (`vibe-signaling`) in `production_authority` mode
delegates session creation, per-request role-token authorization, and session
invalidation to this authority. The shared credential is configured as
`VIBE_SIGNALING_AUTHORITY_TOKEN` in signaling and
`VIBE_AUTHORITY_SIGNALING_TOKEN` in authority; it is distinct from issuer,
metrics, admin, relay, and coturn tokens. Dependency, transport, or malformed
authority responses cause signaling to return `502` and never fall back to
locally minted tokens; normal policy rejections remain `404`, `409`, or `429`.

## Run locally

Requirements are Go 1.25+ and PostgreSQL 15+.

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

Each environment variable above also supports an exclusive `_FILE` form, such
as `VIBE_AUTHORITY_ADMIN_TOKEN_FILE`, for container secret mounts. Do not set
both forms of the same value.

Migration execution is an explicit one-shot operation. Application replicas
must not receive DDL permission. Back up the database and record the migration
checksum before applying it.

## Container and Compose

`Dockerfile` uses the pinned Go 1.25.5 Alpine build image, verifies
the locked modules, and copies only the static binary, CA bundle, container
config, and versioned migration into a `scratch` runtime. The runtime
uses UID/GID 65532. Its health check calls the binary's strict
`--healthcheck` probe against `/readyz`, so schema or
database failure makes the container unready while `/healthz` remains
a process-liveness signal.

The reproducible local profile includes PostgreSQL and persists its data in a
named volume:

```bash
cd deploy/phase3
./scripts/generate-authority-secrets.sh
docker compose -f docker-compose.authority.yml config --quiet
docker compose -f docker-compose.authority.yml up -d --build --wait
curl --fail http://127.0.0.1:8091/healthz
curl --fail http://127.0.0.1:8091/readyz
```

PostgreSQL must become healthy before the one-shot
`authority-migrate` service runs, and Authority starts only after
migration exits successfully. Runtime tokens are not mounted into the migration
service. The local profile uses one database role and
`sslmode=disable` on its private Compose network; it is for
development and CI only, not a production PostgreSQL or TLS example. Stop it
without deleting state using `docker compose -f
docker-compose.authority.yml down`. Add `--volumes` only when
intentionally destroying the local authority ledger.

The production profile is `docker-compose.authority.production.yml`.
It does not create PostgreSQL and requires an Authority image repository plus an
exact SHA-256 digest, a reviewed `config/authority.production.json`, and
external secret files supplied by the deployment secret manager. Use separate
database roles: the migration URL may execute reviewed DDL, while the runtime URL
has only the table/sequence privileges needed by Authority. Both URLs must use
PostgreSQL TLS with certificate and hostname verification, normally
`sslmode=verify-full`; the production profile sets
`VIBE_AUTHORITY_DATABASE_TLS_MODE=verify-full`, so both jobs reject any other
mode before connecting. The published HTTP port is loopback-only because
Authority has no built-in TLS; an authenticated private proxy or service mesh
must provide TLS 1.2+ and network policy for callers.
File-backed Compose secrets must be readable as UID 65532 inside the container.
Have the secret manager materialize that ownership/mode, or keep read-only source
files beneath an operator-only parent directory. Do not run Authority as root to
work around a secret-mount permission error.

Before a production rollout, require all of the following:

- synchronized host and database clocks with monitored NTP offset; expiry and
  epoch decisions fail closed rather than widening TTLs for skew;
- independent admin, signaling, relay, coturn, role-token, migration-database,
  and runtime-database secrets from the secret manager;
- managed PostgreSQL high availability, encrypted storage, PITR, defined
  RPO/RTO, a recent restore exercise, and a backup taken before migration;
- migration checksum review, successful one-shot migration, `/readyz`,
  a synthetic admission/authorization canary, and retained redacted audit data;
- read-only root filesystem, no Linux capabilities, bounded CPU/memory/PIDs,
  log rotation, and a stop grace period longer than the server's ten-second
  shutdown deadline.

Authority remains the durable source of truth for accepted per-device session
epoch floors in production. Callers must never mint a local fallback epoch or
credential when Authority is unavailable. This Compose profile does not add
Mac/Android automatic profile issuance, a production coturn exporter or
disconnect executor, active transport disconnect, public ingress, or
horizontally shared signaling state.

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

### Signaling admission

`POST /v1/signaling/sessions` (signaling token) creates or idempotently replays
a signaling admission. The request must contain `request_id`, `account_id`,
`host_device_id`, `client_device_id`, `session_epoch`, and `ttl_seconds`. The
authority checks that both devices are registered to the account and not
revoked, that the account is not suspended, and that `session_epoch` is strictly
greater than the per-device epoch floor. On success it returns `session_id`,
`host_token`, `client_token`, `expires_at`, and `created`. Role tokens are
derived from the session ID and a server secret, so an exact idempotency replay
returns the same credentials without storing raw bearer tokens.

`POST /v1/signaling/sessions/{session_id}/authorize` (signaling token) validates
a role token against the session. It returns `{"role":"host","expires_at":"..."}`
or `{"role":"client","expires_at":"..."}`. A revoked session, revoked device,
suspended account, or expired admission returns `403`; signaling maps that to
`404` so it does not disclose whether the session exists.

`DELETE /v1/signaling/sessions/{session_id}` (signaling or admin token) revokes
the admission. Subsequent role authorizations fail. The authority API returns
`404` when the admission is absent; signaling treats that as already invalid,
clears any stale local route, and returns its own idempotent `204`.

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
`ttl_seconds` must not exceed `maximum_session_ttl_seconds`. Every authorization
rechecks account/device/session tombstones and expiry.

The `session_epoch` is checked against a per-device epoch floor stored in
`authority_session_epoch_floors`. A new admission must use an epoch strictly
greater than the floor for both the host and client devices; the floor is then
raised to the admitted epoch. This prevents replay of an old session epoch after
revocation. Note that this per-device floor is scoped to the authority's device
identifiers, which is a different scope from the Mac pairing-scoped epoch; the
two are not yet unified.

### Session profile issuance

`POST /v1/session-authority/profiles` (admin token) issues an operator-provided
session profile for already registered account and device IDs. The request
includes the pairing ID, host and client public identities, signaling URL,
authority-selected `session_epoch`, TTL, transcript context, protocol session
ID, and ICE server list. HTTP signaling URLs are accepted only when
`allow_insecure_for_testing` is true and the host is loopback; production input
must use HTTPS.

On success the authority creates or replays the underlying signaling admission,
returns the host signaling token, and returns an unsigned Android lease containing
the client signaling token and routing material. The Mac host must verify its
local pairing bindings, reserve that exact Authority-supplied `session_epoch`,
and sign the lease before Android imports it. The authority ledger stores only a
request digest and identifiers; it does not store role tokens, TURN credentials,
or signed/unsigned lease JSON.

This endpoint is an admin/operator control-plane primitive. It does not register
accounts or devices automatically, does not make Mac or Android call the
authority automatically, and does not prove Android UI import, public Internet,
or real media transport.

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
admission share one deny-wins database ordering. The supplied deployment profile
runs one Authority process; multi-process behavior is not claimed by the container
gate.

## Coturn ingestion contract

`POST /v1/coturn/usage` accepts a machine-generated event containing
`source_id`, stable `event_id`, `allocation_id`, device/session IDs, a strictly
increasing `sequence`, cumulative ingress/egress counters, `observed_at`, and a
`closed` flag. Event retries are idempotent. Counter or sequence regression is
`409`. `observed_at` may equal the preceding observation but cannot move
backward; quota accounting uses the database's UTC ingestion day rather than the
collector timestamp. The usage delta, daily ledger update, allocation high-water
mark, and first over-quota device/session revocation are one serializable
transaction, so the event that crosses quota is retained before new admission is
cut off. An exact event retry replays as a duplicate without debiting the day or
revoking again. A new usage event for a revoked device, suspended account,
revoked session, expired session, or already closed allocation fails closed and
does not advance counters. Revocation does not prove the coturn data plane
disconnected an already running allocation. Relay admission retries with the
same source, allocation, device and session identity return the original
reservation only while the allocation, device, account, and session are still
active; replay after revocation or expiry fails closed, and reuse with different
identity is a conflict.

`POST /v1/coturn/reconcile` accepts one source snapshot (maximum 10,000
allocations). Its `observed_at` cannot be in the future, including for an empty
snapshot. The service applies newer counters and returns ledger allocations missing
from a source beyond `reconciliation_grace_seconds`. The response separately
lists `unauthorized_allocation_ids` that exist only at the source,
`conflict_allocation_ids` whose identity or counters conflict with the ledger,
and `revoked_allocation_ids` for source-observed allocations whose Authority
ledger has already been closed by account suspension, device revocation,
signaling invalidation, expiry, or quota policy. One conflict or revoked
allocation does not stop processing the rest of the snapshot. Revoked allocation
observations fail closed by refusing to advance counters, while still giving the
operator's disconnect executor an exact allocation ID to terminate. Allocations
applied earlier in that request remain committed and replay as duplicates or
already-ahead entries on retry. Operators must disconnect unauthorized,
conflicting, and revoked source allocations, and close ledger-only allocations
only after the configured consecutive-snapshot policy in their collector.

The repository does **not** yet contain a production-proven coturn exporter.
Launch remains blocked until the pinned coturn build or provider API proves it
exports a stable allocation ID, the complete REST username mapping, monotonic
cumulative counters, close events, boot identity and snapshot support. Parsing
human-oriented coturn logs may run in shadow mode but is not an authoritative
quota or billing source.

`scripts/phase3/coturn_reconcile.py` is the current operator-side contract for a
future trusted exporter. It accepts either the structured snapshot shape above or
an external `--exporter-command` whose stdout is that same strict JSON object,
submits it to `/v1/coturn/reconcile`, retries transient failures when explicitly
configured, and requires a configured idempotent disconnect executor for every
unauthorized, conflicting, or revoked source allocation. A missing ledger-only
allocation exits non-zero so the caller's consecutive-snapshot policy must decide
whether to close the ledger record. This helper does not parse coturn logs, does
not create a durable collector cursor/WAL, does not install a production
scheduler, and does not prove a
production disconnect mechanism.

## Clock synchronization and TTL consistency

The authority and its callers (signaling, relay) require synchronized clocks
(NTP). Admission expiry, device revocation timestamps, and coturn usage
sequence/observation checks all depend on wall-clock time. Do not relax expiry
checks or extend TTLs to compensate for clock skew; fix the clock source
instead. The authority's `maximum_session_ttl_seconds` and the signaling
`max_session_ttl_seconds` must be kept consistent so a TTL accepted by
signaling is never rejected by the authority.

`maximum_database_clock_skew_seconds` defaults to 5 when omitted and accepts
only stricter values from 1 through 5. At startup and on every `GET /readyz`
probe, the authority samples PostgreSQL `clock_timestamp()` between two
application-clock samples. Readiness fails closed when the query fails, the
application clock moves backwards, the round-trip is too wide to prove the
configured bound, or the database clock could be outside that bound. The public
failure remains the generic `503 {"error":"authority storage unavailable"}`
response; `/healthz` continues to report process liveness. Signaling in
`production_authority` mode therefore also becomes unready after its bounded
readiness cache expires.

On a clock-readiness failure, compare the host's UTC time with
`SELECT clock_timestamp()` from the configured PostgreSQL endpoint, then repair
the host/database time synchronization or the path causing excessive probe
latency. Do not increase the skew limit or extend session TTLs to hide the
failure. An already-running authority becomes ready again after the clocks are
within bounds; an instance that failed its startup probe must be restarted by
the process supervisor. This relative comparison does not prove that either
clock agrees with an external trusted time source, so NTP monitoring remains a
separate production requirement.

## Production gates

- managed PostgreSQL multi-AZ deployment, TLS, PITR and restore exercise;
- migration checksum/required-schema/database-clock readiness and database
  credentials from a secret manager;
- signaling and relay integration that fails closed on authority errors
  (signaling `production_authority` mode is implemented and covered by a
  two-process PostgreSQL test; relay credential admission is wired to Authority,
  while the production coturn exporter and active disconnect path remain open);
- ledger-side closure of relay allocations when an account is suspended, a
  device is revoked, or a signaling admission is invalidated is implemented;
  later coturn usage for revoked, suspended, expired, or closed allocations
  fails closed without advancing daily counters;
- collector durable cursor/WAL, node heartbeat, gap detection, production
  scheduling, and two-snapshot close reconciliation;
- mapping from issued allocation IDs to complete coturn REST usernames;
- active-allocation disconnect executor and outbox delivery;
- edge authentication, DDoS/rate limiting, audit retention/deletion policy,
  dashboards, cost reconciliation and public-region canaries.

### Remaining open items

- Mac and Android automatic invocation of session-profile issuance is not wired;
  local flows still require an operator to request the profile, pass the
  unsigned lease through the Mac signer, and import the signed lease.
- Automatic account and device registration is not wired; accounts and devices
  must be registered through the admin API before a signaling admission can be
  created.
- Relay credential admission is wired to the authority, and the structured
  reconcile helper can now call an external exporter command and route
  unauthorized, conflicting, or revoked source allocations to an external
  disconnect executor. The repository still has no production implementation for
  the coturn exporter, scheduled
  reconciliation loop, or concrete active-allocation disconnect executor, and
  production
  coturn enforcement remain open.
- An active PeerConnection or TURN allocation is not actively disconnected when
  a device is revoked or a signaling admission is invalidated; the current
  closure is an authority-ledger boundary, not a data-plane kill path.
- The authority per-device `session_epoch` floor and the Mac pairing-scoped
  epoch operate in different scopes and are not yet unified.
- Signaling supports PostgreSQL-backed durable routing state. Multi-instance
  throughput remains an open production gate. Per-message remote authorization
  remains a fail-closed correctness choice rather than a high-throughput design.

Until these gates pass, this is a runnable backend slice, not evidence of a
production Internet deployment.

## Container verification

The bounded Linux gate builds the image, validates both Compose files, starts a
real PostgreSQL container, runs migration, creates and authorizes one session,
restarts Authority, stops PostgreSQL to prove liveness/readiness separation and
write failure, restores PostgreSQL, re-authorizes the persisted session, checks
the non-root/read-only/capability settings, and scans container logs for the
generated secrets:

```bash
make phase3-authority-container-test
```

The CI step has a 15-minute timeout. The test uses disposable secrets and removes
its containers and named volume on exit.
