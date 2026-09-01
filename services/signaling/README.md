# Vibe Screen signaling service

`vibe-signaling` is the runnable Phase 3 rendezvous service. It creates short-
lived sessions and exchanges only validated WebRTC offer, answer, ICE candidate,
and end-of-candidates records between an authenticated host and device. It does
not proxy data channels, media, input, long-lived private keys, application
traffic keys, pairing QR secrets, or arbitrary payloads.

Version `0.1.0` runs in one of two explicit authority modes:

- `local_development`: the historical in-process session issuance and role-token
  authorization. It is intended only for local self-tests and scripts; production
  must not use it.
- `production_authority`: session creation, per-request role-token authorization,
  and session invalidation are delegated to the PostgreSQL-backed
  `vibe-authority` service. Any authority failure is fail-closed: the signaling
  process never falls back to locally minted tokens, and `/readyz` reports
  unavailable while the authority is unreachable.

The `production_authority` mode name means the signaling service delegates trust
decisions to Authority. It is not a claim that the public Internet deployment,
Mac/Android automatic profile issuance, Android UI import, or real media path is
production-ready.

The service has two explicit store backends. `memory` is process-local and
intended for local development; `postgres` persists the short-lived rendezvous
routing state and is required in `production_authority` mode. It is not an
account service, proven multi-replica broker, device revocation authority, or
proof that the product stream is end-to-end encrypted. Endpoints must still
authenticate the signed Vibe Screen session transcript and DTLS fingerprint
independently.

## Build and run

Requirements: Go 1.25.0 or newer. The tested local toolchain is Go 1.25.0;
the container build uses Go 1.25.5.

```bash
cd services/signaling
cp config.example.json config.json
export VIBE_SIGNALING_ISSUER_TOKEN="$(openssl rand -base64 48)"
export VIBE_SIGNALING_METRICS_TOKEN="$(openssl rand -base64 48)"
# Only required when authority_mode is production_authority:
export VIBE_SIGNALING_AUTHORITY_TOKEN="$(openssl rand -base64 48)"
# Required when store_backend is postgres:
export VIBE_SIGNALING_DATABASE_URL='postgres://signaling@db.example.com/vibescreen?sslmode=verify-full'
go build -trimpath -o build/vibe-signaling ./cmd/vibe-signaling
./build/vibe-signaling --config config.json
```

Do not put any token in the JSON file, shell history, repository, mobile app, or
diagnostic bundle. In production, inject them from a secret manager. The issuer
token belongs only to the trusted session-authority backend; a host or Android
binary must receive a session-scoped role token, never this global credential.
The metrics token belongs only to the Prometheus collector. The authority token
authenticates signaling to the authority service and is independent of the
issuer token; it must never be shipped to clients. The database URL is loaded
only from `VIBE_SIGNALING_DATABASE_URL` or `VIBE_SIGNALING_DATABASE_URL_FILE`;
non-loopback PostgreSQL URLs must use `sslmode=verify-full`.

The default config binds loopback because the process has no built-in TLS. For
remote use, terminate TLS 1.2+ at a trusted reverse proxy, restrict the issuer
and metrics routes to internal networks, disable caching and request buffering,
and forward to loopback. Never expose this service as plaintext HTTP over a LAN
or the Internet.

Check the process:

```bash
curl --fail http://127.0.0.1:8088/healthz
curl --fail http://127.0.0.1:8088/readyz
./build/vibe-signaling --version
```

Apply the PostgreSQL schema before starting a `postgres` backend:

```bash
./build/vibe-signaling --migrate migrations/001_signaling.sql
```

`SIGTERM` and `SIGINT` stop readiness, cancel long polls, drain HTTP requests,
and exit with a bounded ten-second shutdown deadline.

## Protocol v1 HTTP API

Every response has `Cache-Control: no-store`. JSON request bodies require
`Content-Type: application/json`, reject unknown fields and trailing objects,
and are capped before decoding. Role bearers are scoped to exactly one session
and role and expire with the session. Local mode stores random tokens in process;
production mode uses authority-derived tokens and rechecks them remotely instead
of retaining them in signaling state. The request body never selects its own role.

Create a session through the trusted authority. In `local_development` mode only
`request_id` and `ttl_seconds` are required. In `production_authority` mode the
request must also carry `account_id`, `host_device_id`, `client_device_id`, and
`session_epoch`; the requester still authenticates with the issuer token, and
signaling forwards the admission to the authority using its own independent
authority token:

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $VIBE_SIGNALING_ISSUER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id":"01J-AUTHORITY-RETRY-ID",
    "account_id":"acct_Ep8",
    "host_device_id":"host_Fm2",
    "client_device_id":"device_Qk9",
    "session_epoch":19,
    "ttl_seconds":300
  }' \
  http://127.0.0.1:8088/v1/sessions
```

The `201` response contains an opaque `session_id`, separate `host_token` and
`device_token`, and `expires_at`. In `production_authority` mode the session
identity and role tokens are issued by the authority; signaling stores routing
metadata and rechecks role tokens with the authority. Deliver each role token
over an already authenticated channel to that endpoint. Repeating the same
`request_id` and body returns the identical response with `200`; changing any
field returns `409`.

When an operator creates a session through Authority's admin-only
`POST /v1/session-authority/profiles` endpoint, signaling has no local `/v1/sessions`
creation record. In `production_authority` mode, the first successful role
authorization for that authority-issued `session_id` creates local routing
metadata with empty role-token columns and an Authority-derived expiry. The
role token is still rechecked remotely on every publish and poll; signaling does
not retain the bearer token as a local fallback.

With `store_backend: postgres`, the short-lived routing state, request-ID
idempotency record, invalidation tombstone, message cursor, per-role message
rate window, and session-create token bucket rows are backed by PostgreSQL.
Routing state survives a signaling process restart until session TTL cleanup;
session-create token bucket rows are removed separately after two minutes of
idle time based on `refilled_at`. Long-poll waiter leases are stored in
PostgreSQL and are reclaimed when their listener backend disappears. Waiter
leases are tied to the
PostgreSQL listener backend PID and start timestamp; another instance clears a
lease only after that backend disappears, so a crashed or killed signaling
process cannot permanently consume the per-role waiter slot. Replaying the same
`request_id` after restart therefore returns the existing session rather than
reconstructing an empty session. With `store_backend: memory`, a restart still
loses all routing state, so operators must issue a fresh `request_id`. In
`production_authority` mode, they must also use a larger `session_epoch`.

Invalidate a session through the same trusted authority when the product ends
or revokes it:

HarmonyOS HUKS-backed secure pairing uses this same `production_authority`
path. The Harmony client proves its HUKS-backed device identity to the Host,
but service credentials stay server-side: clients receive only their
session-scoped role token after the paired Host/backend has created the
Authority admission. A revoked Harmony device, expired admission, stale session
epoch, unreachable Authority, malformed Authority response, old peer, or
no-HUKS device path must fail closed; Signaling must not mint local replacement
tokens in production mode and the Harmony app must not treat trusted-LAN address
import as secure pairing.

```bash
curl --fail-with-body -X DELETE \
  -H "Authorization: Bearer $VIBE_SIGNALING_ISSUER_TOKEN" \
  "http://127.0.0.1:8088/v1/sessions/$SESSION_ID"
```

The first and repeated invalidations return `204`. In
`production_authority` mode signaling first asks the authority to revoke the
admission. A missing authority admission is already invalid and is treated as
idempotent success; any other authority error fails closed with `502` and leaves
local state untouched. On success the authority rejects both role tokens while
signaling destroys queued SDP/ICE events, wakes blocked long polls with `404`,
and rejects further role access. The service retains a tombstone until the
session's original expiry: replaying the original `request_id` returns `409`
instead of minting replacement credentials. The authority must use a new request
ID and a larger product `session_epoch` for a fresh reconnect. This endpoint
invalidates one known rendezvous session; it is not a durable device-revocation
database or a replacement for terminating the product session and blocking relay
credentials.

Publish the host offer (the device uses its token and type `answer`):

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $HOST_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message_id":"offer-1","type":"offer","sdp":"v=0\r\n..."}' \
  "http://127.0.0.1:8088/v1/sessions/$SESSION_ID/messages"
```

Publish a candidate or completion marker:

```json
{"message_id":"ice-host-1","type":"ice_candidate","candidate":{"candidate":"candidate:...","sdp_mid":"0","sdp_mline_index":0,"username_fragment":"..."}}
{"message_id":"ice-host-end","type":"end_of_candidates"}
```

`message_id` makes publishing idempotent. Reusing it with different content is
`409`. Host alone may publish the one offer; device alone may publish the one
answer, and only after the offer. Each role may publish at most the configured
candidate count and one completion marker. This v0.1 session represents one ICE
negotiation; an ICE restart currently creates a new short-lived rendezvous
session, which is an explicit limitation rather than accepting ambiguous stale
candidates.

Long-poll only remote events:

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  "http://127.0.0.1:8088/v1/sessions/$SESSION_ID/events?after=0&wait_seconds=25"
```

The response has `events` and a monotonic `next_cursor`. Pass that cursor to the
next poll. A cursor is scoped by the session bearer; changing it can only skip
that caller's events, never read another session. One waiter per role is allowed
by default. In `production_authority` mode every message publish is authorized
before parsing and again immediately before commit, while every poll is
authorized before and during its wait. Long polls are split into bounded
Authority refresh windows, so a revocation that lands during a long poll fails
closed without waiting for the caller's full `wait_seconds` timeout. Sessions
and all SDP/ICE state are deleted from the active store at TTL.

### Status codes

| Code | Meaning |
| --- | --- |
| `200` | Poll success or exact idempotent replay |
| `201` | Session or message created |
| `204` | Session invalidated, including an idempotent repeat |
| `400` | Invalid JSON, query, identifier, payload, or configured limit |
| `401` | Invalid internal issuer/metrics authentication, including invalidation |
| `404` | Unknown session or wrong session/role bearer; deliberately indistinguishable |
| `409` | Role/state violation or conflicting idempotency replay |
| `410` | Session expired and the caller proved possession of its role token |
| `429` | Rate, waiter, candidate, or reserved-session-record limit reached |
| `503` | Signaling storage unavailable or readiness dependency failure |
| `502` | Authority service unavailable in `production_authority` mode (fail-closed) |

## Configuration and limits

All JSON fields are required. Unknown fields fail startup.

| Field | Purpose |
| --- | --- |
| `listen_address` | TCP bind address; keep loopback unless a secure sidecar provides TLS |
| `authority_mode` | `local_development` (in-process issuance, local only) or `production_authority` (delegate to the authority service) |
| `authority_url` | Authority base URL; required only for `production_authority`. Must be `https://` or loopback `http://`, with no path/query/userinfo |
| `store_backend` | `memory` for local process state or `postgres` for PostgreSQL-backed routing. `production_authority` requires `postgres` |
| `session_ttl_seconds`, `max_session_ttl_seconds` | Default and authority-selectable upper TTL. In `production_authority` mode `max_session_ttl_seconds` must not exceed the authority's `maximum_session_ttl_seconds` |
| `max_active_sessions` | Hard session/reserved-tombstone cap in the active store |
| `session_creates_per_minute` | Session-create token-bucket cap. Local-development creates use one shared local bucket; production-authority creates use shared device/action rows for each authenticated host and client device identity after Authority admits the session |
| `messages_per_minute` | Per-role, per-session publish cap |
| `max_request_body_bytes` | HTTP JSON body cap |
| `max_sdp_bytes` | Single offer or answer cap |
| `max_candidate_bytes` | Candidate string cap |
| `max_candidates_per_role` | Candidate count cap for each endpoint |
| `max_wait_seconds` | Long-poll ceiling, at most 60 seconds |
| `max_waiters_per_role` | Concurrent poll cap per endpoint |
| `cleanup_interval_seconds` | Expired-state deletion cadence |

The process deliberately trusts neither `X-Forwarded-For` nor a caller-provided
device ID. Add edge source-IP/global limits and DDoS controls at the TLS proxy.

## Metrics and health

- `GET /healthz` is unauthenticated liveness and reveals only `{"status":"ok"}`.
- `GET /readyz` is unauthenticated readiness. It checks the configured store;
  the PostgreSQL backend verifies database reachability, schema checksum,
  required tables/columns/constraints, and a conservative database/application
  clock-skew bound. In `production_authority` mode it also probes the authority
  `/readyz` and returns `503` while the authority is unavailable; it reveals no
  dependency details.
- `GET /metrics` requires the independent metrics bearer.

Prometheus output contains low-cardinality counts for created/invalidated sessions,
accepted messages, idempotent retries, rejected requests, poll timeouts, and
expired cleanup. Gauges distinguish active sessions, retained invalidation
tombstones, total reserved records that consume `max_active_sessions`, and
currently blocked long polls. Thus `active_sessions=0` together with
`reserved_session_records=max_active_sessions` explains a capacity `429` rather
than implying free capacity. Metrics have no session/device/IP/token labels.
Logs are limited to lifecycle and generic network-write failures; raw SDP,
candidates, tokens, keys, stable identifiers, and source addresses are never
logged.

## Container

The Dockerfile uses an immutable Go 1.25.5 Alpine build image and a `scratch`
runtime. The final image contains only a static binary and runs as UID/GID
65532. Mount the config read-only and inject secrets:

```bash
docker build --build-arg VERSION=0.1.0 -t vibe-signaling:0.1.0 .
docker run --rm --read-only --cap-drop=ALL \
  -p 127.0.0.1:8088:8088 \
  -e VIBE_SIGNALING_ISSUER_TOKEN \
  -e VIBE_SIGNALING_METRICS_TOKEN \
  -e VIBE_SIGNALING_AUTHORITY_TOKEN \
  -e VIBE_SIGNALING_DATABASE_URL \
  -v "$PWD/config.container.example.json:/etc/vibe-screen/signaling.json:ro" \
  vibe-signaling:0.1.0
```

The image includes `/usr/share/vibe-screen/migrations/001_signaling.sql`; run
`/vibe-signaling --migrate /usr/share/vibe-screen/migrations/001_signaling.sql`
with the same database URL before routing traffic.

The container example binds `0.0.0.0:8088`; the published host port remains
loopback unless a TLS proxy is in front. Docker was unavailable in the recorded local
environment, so image execution remains unverified; the native process is
covered by the real-process integration test.

## Verification

```bash
make verify
go test -run TestRealProcessHostDeviceExchangeAndGracefulShutdown -count=1 .
# Requires running PostgreSQL URLs for both services:
VIBE_AUTHORITY_TEST_DATABASE_URL='postgres://...' \
VIBE_SIGNALING_TEST_DATABASE_URL='postgres://...' \
  go test -run Postgres -count=1 ./internal/signaling
VIBE_AUTHORITY_TEST_DATABASE_URL='postgres://...' \
VIBE_SIGNALING_TEST_DATABASE_URL='postgres://...' \
  go test -run TestAuthorityProcessSessionRevocationFailClosed -count=1 .
```

The local process test builds and starts the real binary in `local_development`
mode, waits for health, creates a session, performs offer/answer and
bidirectional ICE exchange, invalidates the session while a long poll is
blocked, verifies role-token and request-ID replay rejection, scrapes metrics,
sends `SIGTERM`, verifies a clean exit, and checks that known
SDP/candidate/token secrets were absent from logs.

The authority-backed process test starts `vibe-authority` (PostgreSQL),
`vibe-signaling` (`production_authority` with PostgreSQL), and `vibe-relay`
(`production_authority`), registers an account and both devices, creates
authority-backed sessions through the issuer endpoint, exchanges a host offer to
the device poll, obtains authority-admitted relay credentials, invalidates one
session, revokes the client device at the authority, and asserts that signaling
role access plus future relay credential admission are then rejected. It also
confirms that none of the processes logs any service token, role token, SDP
secret, or relay credential secret. This proves rendezvous behavior and future
TURN-credential fail-closed revocation propagation, not a WebRTC ICE connection
or an already-active TURN allocation.
The Postgres store tests apply the migration twice, verify readiness checksum and
schema drift failure, prove routing state survives a signaling restart, exercise
expiry cleanup, cross-instance long-poll wakeup, connection-scoped waiter-lease
recovery after backend disconnect, waiter caps, and concurrent capacity admission.

## Upgrade and rollback

1. Back up the config and record the current image digest/binary checksum.
2. Read release notes and diff `config.example.json`; startup rejects unknown or
   missing fields instead of silently using unsafe defaults.
3. Start the new instance on a separate loopback port, verify `/healthz`,
   `/readyz`, authenticated `/metrics`, and run a synthetic two-peer exchange.
4. Drain the old instance before switching traffic. In `memory` mode a rolling
   restart requires clients to create a fresh session. In `postgres` mode the
   short-lived routing rows survive binary restart but still expire at the
   original TTL.
5. Roll back by routing to the prior binary/image. Do not roll back or rewrite
   PostgreSQL routing rows; expired or invalidated sessions must remain closed.

See [OPERATIONS.md](OPERATIONS.md) for production controls and incident actions,
and [THREAT_MODEL.md](THREAT_MODEL.md) for the security boundary and residual
risks.

## Open items

The following are explicit limitations of the current `production_authority`
slice, not accepted production behavior:

- Mac and Android automatic invocation of Authority session-profile issuance is
  not wired; local development flows still require an operator to request the
  profile, pass the unsigned lease through the Mac signer, and import the signed
  lease.
- Automatic account and device registration is not wired; accounts and devices
  must be registered through the authority admin API before a session can be
  created.
- Relay credential and usage admission are wired to the authority, but the
  coturn exporter,
  reconciliation loop, and active-allocation disconnect path are not production
  proven.
- An active PeerConnection or TURN allocation is not actively disconnected when
  a session is revoked at the authority; signaling invalidation only stops new
  rendezvous access.
- The authority's per-device `session_epoch` floor and the Mac pairing-scoped
  epoch operate in different scopes; their interaction is not yet unified.
- PostgreSQL durable routing is implemented for `production_authority`, including
  cross-instance message delivery through `LISTEN`/`NOTIFY`, transaction-level
  session state locks, connection-scoped waiter leases that can be reclaimed
  after an instance loses its database backend, and shared per-device/action
  create-rate rows. Multi-instance throughput, public ingress behavior, rolling
  deployment behavior, load-balancer behavior, and multi-region consistency are
  still not proven.
  Local integration tests cover two store instances sharing routing, long-poll
  wakeups, and invalidation tombstones.
- Per-message remote authorization against the authority and the global
  PostgreSQL advisory lock serialization of creates are deliberate fail-closed
  correctness choices, not a high-throughput design. Do not claim multi-instance
  throughput until these are re-architected.
- Signaling and authority require synchronized clocks (NTP); expiry checks must
  not be relaxed to compensate for clock skew.
- The signaling `max_session_ttl_seconds` and the authority
  `maximum_session_ttl_seconds` must be kept consistent; signaling rejects TTLs
  above its own cap, and the authority rejects TTLs above its own.

## Provenance and licensing

No third-party source code was copied into this module. Runtime code uses the Go
standard library plus pgx client libraries for PostgreSQL access.

| Project | Immutable version | License | Use | Copied code |
| --- | --- | --- | --- | --- |
| Go | `go1.25.0`, <https://github.com/golang/go/tree/go1.25.0> | BSD-3-Clause | compiler/build stage and standard-library runtime | No source copied; standard library linked into binary |
| Official Go container | `golang:1.25.5-alpine3.22@sha256:3587db7cc96576822c606d119729370dbf581931c5f43ac6d3fa03ab4ed85a10` | Go BSD-3-Clause plus Alpine package licenses | build stage only; absent from final `scratch` image | No |
| pgx | `github.com/jackc/pgx/v5 v5.9.2`, <https://github.com/jackc/pgx> | MIT | PostgreSQL client, migration, readiness and store implementation | No |
| pgpassfile | `github.com/jackc/pgpassfile v1.0.0`, <https://github.com/jackc/pgpassfile> | MIT | pgx dependency for PostgreSQL password file support | No |
| pgservicefile | `github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761`, <https://github.com/jackc/pgservicefile> | MIT | pgx dependency for PostgreSQL service file support | No |
| puddle | `github.com/jackc/puddle/v2 v2.2.2`, <https://github.com/jackc/puddle> | MIT | pgx connection-pool dependency | No |
| SideScreen | commit `a651a81b7d6468c7a564c038551872d3346a2d55`, <https://github.com/tranvuongquocdat/SideScreen> | MIT | repository architecture context only | No |
| Telemachus | commit `a5dd1298870846d749175812f936ceebfd8b6b69`, <https://github.com/aaditagrawal/telemachus> | MIT | repository reliability context only | No |

The container digest was read from Docker Registry's immutable manifest on
2026-08-04. The original Vibe Screen signaling code still requires the project
owner to select a repository-wide license before public distribution; the root
repository currently states that as a release blocker. No GPL/AGPL source was
consulted or copied for this implementation.
