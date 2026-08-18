# Signaling operations

## Deployment checklist

- Bind the process to loopback or a private sidecar network.
- Terminate TLS 1.2+ at a maintained reverse proxy; redirect/reject plaintext.
- Restrict session creation/invalidation routes and `/metrics` to their internal callers.
- Inject separate 32+ character issuer, metrics, and (in `production_authority`
  mode) authority tokens from a secret manager. The authority token authenticates
  signaling to the authority service and must be distinct from the issuer token.
- In `production_authority` mode, configure `authority_url` to the authority
  service and ensure signaling can reach it over HTTPS (or loopback HTTP for
  local development). Signaling fails closed when the authority is unreachable.
- In `production_authority` mode, set `store_backend` to `postgres`, inject
  `VIBE_SIGNALING_DATABASE_URL` from a secret manager, run
  `vibe-signaling --migrate /usr/share/vibe-screen/migrations/001_signaling.sql`
  before startup, and require `sslmode=verify-full` for non-loopback databases.
- Run UID/GID 65532, read-only root filesystem, no Linux capabilities, no core
  dumps, and a bounded memory/CPU/process budget.
- Configure proxy body size at or below `max_request_body_bytes`, request read
  timeout below ten seconds, long-poll timeout just above `max_wait_seconds`,
  source-IP/global rate limits, connection caps, and DDoS protection.
- Scrape authenticated metrics and alert on rejection rate, reserved-record
  capacity, active sessions, tombstones, blocked/poll-timeout counts, and
  unexpected restart frequency.
- Run the synthetic real-process host/device exchange before shifting traffic.

Never log request/response bodies or authorization headers at the proxy. Default
access logs expose source IP and session paths; disable them or replace the path
with a route template and apply the organization's approved retention policy.

## Health and alerts

`/healthz` means the event loop can answer HTTP. `/readyz` means the process is
accepting traffic and its configured store is ready. For PostgreSQL, readiness
checks database reachability, schema checksum, required structure, and a bounded
database/application clock-skew probe; in `production_authority` mode it also
requires the authority `/readyz` to succeed. Neither proves peer connectivity,
TLS, TURN, or WebRTC.
An external synthetic should create a short session, exchange an offer/answer
and two candidates, then let it expire.

Alert on:

- readiness failure or restart loop;
- `reserved_session_records` approaching `max_active_sessions`, split by active
  sessions and invalidation tombstones;
- sustained `requests_rejected_total` or create/message rate rejection;
- active sessions increasing while created/expired counters stop moving;
- poll timeout changes correlated with client connection failures;
- TLS certificate expiry, proxy 4xx/5xx, and edge connection exhaustion.

Metrics are process-local and reset at restart. Do not use them as an audit log.

## Incidents

### Issuer or authority token exposure

1. Remove external reachability to `/v1/sessions`.
2. Rotate `VIBE_SIGNALING_ISSUER_TOKEN` in the trusted issuer and signaling. If
   the authority credential was compromised, rotate the shared value under
   `VIBE_SIGNALING_AUTHORITY_TOKEN` in signaling and
   `VIBE_AUTHORITY_SIGNALING_TOKEN` in authority.
3. Invalidate known sessions through the issuer endpoint. In `memory` mode, a
   restart deletes process-local sessions; in `postgres` mode, the database
   tombstone/TTL rows remain and must not be manually deleted to mint replacement
   credentials.
4. Review low-cardinality creation/rejection metrics and redacted edge telemetry.
5. Rotate TURN service credentials separately if the authority could access them.

### Role token or SDP/ICE disclosure

Invalidate the known signaling session through the issuer endpoint (which
forwards the revocation to the authority in `production_authority` mode), block
the paired device at the authority, revoke new TURN issuance, and require a
fresh signed session epoch. Restart the instance if the session is unknown or
the issuer is compromised. Signaling invalidation does not revoke an already
active TURN allocation or WebRTC connection; those require separate
data-plane actions.

### Memory/capacity exhaustion

Keep readiness false by removing the instance from the proxy and preserve only
redacted metrics. In `memory` mode, restart to atomically delete process-local
state; in `postgres` mode, keep the database online for TTL cleanup and lower
caps or strengthen edge limiting before re-entry. Do not capture a core dump or
database snapshot containing live SDP, candidates, and tokens.

## Upgrade, rollback, and compatibility

The HTTP schema is versioned under `/v1`. Additive response fields are allowed;
removing fields, changing role/state semantics, changing idempotency, or changing
candidate/SDP framing requires a new API version. Run old and new binaries on
separate ports and use a synthetic exchange. In `memory` mode, drain the old
process for at least the configured maximum session TTL or explicitly accept
client reconnects before stopping it. In `postgres` mode, short-lived routing
rows survive binary restart but still expire at the original TTL.

Rollback is binary/config rollback, not state recovery. Never copy opaque memory
state between versions or rewrite PostgreSQL routing rows. In `memory` mode, a
restart invalidates all sessions by design; in `postgres` mode, existing rows
remain valid only until their original TTL or invalidation tombstone.

## Clock synchronization and expiry

Signaling and the authority service require synchronized clocks (NTP). Session
expiry, authority admission expiry, and usage observation timestamps depend on
wall-clock time. Do not relax expiry checks or extend TTLs to compensate for
clock skew; fix the clock source instead. The signaling
`max_session_ttl_seconds` and the authority `maximum_session_ttl_seconds` must
be kept consistent so a TTL accepted by signaling is never rejected by the
authority.

The authority `/readyz` and the signaling PostgreSQL backend both fail closed
when PostgreSQL `clock_timestamp()` cannot be proven within their configured
application-clock skew bound. Repair the host/database time source or excessive
database-probe latency; do not extend session TTLs or raise the skew limit to
suppress the failure. This comparison checks relative consistency only and does
not replace external NTP monitoring.

## Backup and retention

In `memory` mode there is no signaling database to back up. In `postgres` mode,
the database stores short-lived SDP/ICE routing metadata, request IDs, session
IDs, tombstones, and local-mode role tokens until TTL cleanup, so backups, WAL,
snapshots, and support exports require encryption, short retention, restore
drills, and secret redaction. SDP, ICE, bearer tokens, request bodies, and
session identifiers must not enter logs, traces, analytics, or crash reports.
Expired state is physically removed from the store by request-time and periodic
cleanup; Go heap reclamation does not guarantee immediate byte-level erasure.

## Production authority open items

- Mac/Android automatic profile/account/session issuance is not wired to the
  authority.
- Automatic account/device registration is not wired.
- Relay credential admission is wired to the authority; coturn exporter
  reconciliation and active-allocation disconnect are not production proven.
- Active PeerConnection/TURN allocations are not actively disconnected on
  authority revocation.
- The authority per-device `session_epoch` floor and the Mac pairing-scoped
  epoch have different scopes and are not yet unified.
- PostgreSQL durable routing is implemented for `production_authority`, but
  multi-instance operation, global create-rate enforcement, and throughput under
  multiple replicas remain unproved.
- Per-message remote authorization and the global PostgreSQL advisory-lock create
  serialization are fail-closed correctness choices, not a high-throughput
  design; do not claim multi-instance throughput.
