# Vibe Screen relay control plane

This directory contains a small, runnable control plane for a separately
deployed TURN data plane. It issues short-lived TURN REST credentials, accepts
authenticated usage events, enforces per-device quotas and concurrent-session
limits, estimates egress cost, and exposes authenticated Prometheus metrics.

It deliberately does **not** proxy WebRTC packets. A TURN server such as coturn
forwards already encrypted DTLS-SRTP media and encrypted data-channel traffic.
This service never receives SDP, media, input events, content keys, or plaintext
screen content, so the relay cannot terminate Vibe Screen content encryption.

## Requirements and build

- Go 1.23 or newer (verified with Go 1.24.13)
- PostgreSQL 16 or newer for the production storage backend
- A TURN server configured with the same REST authentication secret
- TLS termination in front of this HTTP service outside local development

```bash
cd services/relay
make verify
make build VERSION=0.1.0
./bin/vibe-relay --version
```

The control plane uses `pgx` for the optional PostgreSQL storage backend. The
container build pins `golang:1.24.13-alpine3.22` by OCI digest and produces a
static, non-root scratch image with CA certificates and the relay migration SQL:

```bash
docker build --build-arg VERSION=0.1.0 -t vibe-relay:0.1.0 .
```

## Configure and run

Copy `config.example.json` to `config.json`, replace the realm and TURN URIs,
then generate independent secrets. Never commit them.

```bash
export VIBE_RELAY_TURN_SECRET="$(openssl rand -base64 48)"
export VIBE_RELAY_CLIENT_TOKEN="$(openssl rand -base64 48)"
export VIBE_RELAY_USAGE_TOKEN="$(openssl rand -base64 48)"
export VIBE_RELAY_METRICS_TOKEN="$(openssl rand -base64 48)"
export VIBE_RELAY_ADMIN_TOKEN="$(openssl rand -base64 48)"
# Required only when authority_mode is production_authority:
export VIBE_RELAY_AUTHORITY_TOKEN="$(openssl rand -base64 48)"
./bin/vibe-relay --config config.json
```

- `VIBE_RELAY_TURN_SECRET` is shared only with coturn.
- `VIBE_RELAY_CLIENT_TOKEN` authenticates the trusted signaling service that
  requests credentials after it has authenticated a paired device.
- `VIBE_RELAY_USAGE_TOKEN` authenticates only the trusted TURN usage collector.
- `VIBE_RELAY_METRICS_TOKEN` authenticates only the Prometheus scraper.
- `VIBE_RELAY_ADMIN_TOKEN` authenticates device-revocation requests. The client,
  usage, metrics, and admin API tokens must differ.
- `VIBE_RELAY_AUTHORITY_TOKEN` authenticates relay to `vibe-authority` in
  `production_authority` mode. It must match Authority's
  `VIBE_AUTHORITY_RELAY_TOKEN` and remain distinct from every other relay,
  signaling, admin, metrics, usage, coturn, and TURN secret.

The service refuses to start when a secret is missing or shorter than 32
characters. The default `storage_backend` is `file`: state is atomically stored
at `state_file` with mode `0600`. Back up that file before an upgrade; the v0.1
JSON schema is forwards-readable by v0.1 releases. Stop the old process, replace
the binary, and restart against the same configuration and state file. Roll back
by restoring both the prior binary and its state backup.

Set `storage_backend` to `postgres` for production. In that mode the service
requires `VIBE_RELAY_DATABASE_URL` or `VIBE_RELAY_DATABASE_URL_FILE`, runs only
after migration `001_relay.sql` has been applied, and fails closed when `/readyz`
cannot verify the database clock, schema checksum, required relations, columns,
or constraints. Run the migration with a short-lived DDL role before starting
the service:

```bash
export VIBE_RELAY_DATABASE_URL_FILE=/run/secrets/relay_migration_database_url
./bin/vibe-relay --migrate migrations/001_relay.sql
```

Set `VIBE_RELAY_DATABASE_TLS_MODE=verify-full` in production; when present, the
database URL must be `postgres://` or `postgresql://` and include
`sslmode=verify-full`. `maximum_database_clock_skew_seconds` defaults to five
seconds and may only be tightened.

For a local file-backed container, mount a read-only configuration file and a
writable `/data` directory owned by UID/GID 65532. Set `state_file` to
`/data/relay-state.json`, inject secrets through the runtime secret store, and
publish the HTTP port only to the internal load balancer. A Postgres-backed
container does not need the `/data` state volume, but still requires runtime
secret files and a private load-balancer listener.

Each secret also supports a mutually exclusive `<NAME>_FILE` variable, for
example `VIBE_RELAY_TURN_SECRET_FILE=/run/secrets/turn_secret`. File contents
are trimmed of surrounding whitespace and unreadable/ambiguous sources fail
closed. The runnable coturn/Compose integration uses only these file variants;
see [`../../deploy/phase3/README.md`](../../deploy/phase3/README.md).

## API v1

All protected calls use `Authorization: Bearer <token>` and JSON bodies reject
unknown fields. Identifiers accept 1–128 ASCII letters, digits, `.`, `_`, or
`-`. Responses set `Cache-Control: no-store`.

Request a credential (trusted signaling service):

```bash
curl --fail-with-body -H "Authorization: Bearer $VIBE_RELAY_CLIENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"paired-device-id","session_id":"authorized-session-id","allocation_id":"turn-allocation-id","ttl_seconds":600}' \
  http://127.0.0.1:8090/v1/credentials
```

In `local_development` mode, `allocation_id` is optional and the relay uses
its process-local JSON store for revocation/quota checks. In
`production_authority` mode, `allocation_id` is required: before returning a
TURN credential, relay calls Authority's `/v1/relay/admissions` with the
configured `authority_source_id`, `device_id`, `session_id`, and
`allocation_id`. Authority failure, malformed response, revoked/unknown device
or session, quota rejection, or conflicting allocation identity fails closed and
no credential is returned.

The username is `<unix-expiry>:<device-id>` and the password is the base64
HMAC-SHA1 required by TURN REST authentication. `session_id` and
`allocation_id` remain in the authenticated control-plane request but are
excluded from the TURN username. After coturn removes the expiry prefix, every
credential for a device shares one stable `user-quota` principal across
sessions and expiries. Device IDs cannot contain the `:` separator. SHA-1 is
used only for this
TURN compatibility MAC with a high-entropy server secret; it is not content
encryption or a password hash.

Report lifecycle and cumulative byte deltas (trusted usage collector):

```bash
curl --fail-with-body -H "Authorization: Bearer $VIBE_RELAY_USAGE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"unique-event-id","device_id":"paired-device-id","session_id":"allocation-id","kind":"start","ingress_bytes":0,"egress_bytes":0}' \
  http://127.0.0.1:8090/v1/usage
```

`kind` is `start`, `update`, or `end`. Each `event_id` is idempotent for the
current UTC day. Byte fields are deltas, not totals. The collector must retry
with the same event ID until it receives `202 accepted` or `200 duplicate`.
Limits return `429`; malformed or out-of-order lifecycle events return `400`.

The trusted control plane can persistently block future credentials with
`POST /v1/devices/{device-id}/revoke` using the admin token. After revocation,
the service fails closed: it rejects new credentials and new usage lifecycle
events for that device with `403 device revoked`, including `start`, `update`,
and `end`. Retrying an event already accepted during the current UTC day still
returns `200 duplicate`, so a lost success response remains safely idempotent.
This control-plane state change does not terminate a coturn allocation that is
already active; the operator must separately invoke the data plane's
allocation-disconnect mechanism and reconcile any active-session ledger entry
left behind by the rejected lifecycle events.

Unauthenticated liveness/readiness endpoints are `/healthz` and `/readyz`;
readiness verifies that the file state directory is writable or that the
Postgres backend is reachable with the expected schema and clock bound. In
`production_authority` mode, readiness also requires Authority `/readyz` to be
reachable.
Prometheus scrapes `/metrics` with the dedicated metrics token. Metrics expose issued and
rejected requests, a dedicated
`vibescreen_relay_revoked_device_requests_rejected_total` counter, accepted
events, ingress/egress bytes, active sessions, and
the current UTC day's estimated egress microcents as a gauge. Never use these
application metrics as the sole
billing record; reconcile them with the TURN provider or network billing data.

## TURN integration and operational limits

`coturn.example.conf` shows the compatible REST-secret settings and basic data
plane abuse controls. Configure TLS certificates, external/public IP mapping,
port ranges, firewall rules, and the same realm/secret for the actual host.
Feed allocation lifecycle and byte deltas from a trusted coturn log/metrics
collector into `/v1/usage`; coturn does not call this custom HTTP API itself.
That collector is the authoritative source for enforcement: missed or delayed
events temporarily weaken byte and concurrency limits. Alert on collector lag
and enforce matching `user-quota`, `total-quota`, and `max-bps` limits in TURN.
`user-quota` is the immediate atomic per-device allocation boundary because the
signed TURN principal is device-only. It is an allocation cap, not a product
session cap; size it for the ICE transports a legitimate device needs. Multiple
TURN nodes require device-sticky routing or a distributed admission authority.

This component is not a WebRTC signaling/rendezvous server and does not
implement SDP exchange, ICE restart, P2P path selection, network handoff, or
STUN itself. Those remain transport/session responsibilities. The signaling
service must authenticate the paired device and authorized host/session before
using its client token; the token intentionally authenticates that service,
not the arbitrary `device_id` string in a request. In production, signaling must
obtain or derive a stable `allocation_id` for the TURN attempt and pass it to
relay so retries are exactly idempotent at Authority.

The file backend is intended for one local control-plane replica. The Postgres
backend provides shared transactional quota, revocation, active-session, and
event-idempotency state for multiple relay control-plane processes, while
credential issuance rate limiting remains per process and per device. The edge
proxy should additionally enforce source-IP and global limits. Authority-backed
relay admission blocks new credentials after device or session revocation, but a
credential already issued remains valid until its short expiry. Immediate removal
additionally requires blocking the device at signaling policy and disconnecting
its TURN allocation; rotating the shared TURN secret affects every device.

The `/v1/usage` daily-byte and active-session ledger is not authoritative until
a trusted coturn collector and reconciliation loop are deployed. It must not be
used as the real-time allocation security boundary; coturn's stable-device
`user-quota` remains that boundary in the current deployment.
For Authority-backed deployments, relay must set `allocation_registry_file`; after
Authority admits an allocation and before relay returns a TURN credential, relay
atomically records the `allocation_id`, `device_id`, `session_id`, and generated
TURN REST username in that registry. Registry write or identity-conflict failure
returns `503` and no credential. `scripts/phase3/coturn_reconcile.py` can then
run `scripts/phase3/coturn_cli_control.py export` as its exporter command and
`coturn_cli_control.py disconnect` as its executor. This is a minimal single-node
coturn CLI path; deployments still need durable collector scheduling/WAL,
provider/billing reconciliation, multi-node registry coordination, and public
production evidence before the release gate closes.

## Threat model

Protected assets are relay capacity, quota/cost records, TURN shared secret,
API tokens, database credentials, and the privacy of device identifiers.
Defenses cover stolen or replayed usage events (scoped bearer token plus
persistent event IDs), quota exhaustion (daily bytes, concurrent allocations,
event-size bounds), credential scraping (separate token, short TTL, rate limit),
parser abuse (16 KiB body cap, strict JSON), timing disclosure (constant-time
token comparison), restart replay (atomic persisted ledger), and production
storage drift (schema checksum and database clock readiness checks).

The deployment must supply TLS, trusted-device authentication at signaling,
token rotation, network isolation, log redaction, TURN allocation telemetry,
DDoS protection, and secret management. Bearer-token theft, host compromise,
malicious trusted collectors, volumetric attacks before the application, and
multi-region consistency are outside this process's trust boundary. WebRTC
DTLS-SRTP plus Vibe Screen's device/session encryption remains responsible for
content confidentiality and replay protection; TURN credentials do not provide
end-to-end device identity.

## Provenance and licenses

No third-party source code is copied into this module. The compiled service uses
the Go standard library plus the module dependencies listed below for PostgreSQL
connectivity; source is resolved by Go modules and not vendored.

| Project | Immutable version | License | Use | Copied code |
| --- | --- | --- | --- | --- |
| SideScreen, <https://github.com/tranvuongquocdat/SideScreen> | `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | Repository architecture/behavior context only; no relay implementation used | No |
| Telemachus, <https://github.com/aaditagrawal/telemachus> | `a5dd1298870846d749175812f936ceebfd8b6b69` | MIT | Repository reliability context only; no relay implementation used | No |
| pgx, <https://github.com/jackc/pgx> | module `github.com/jackc/pgx/v5` version `v5.7.5` | MIT | PostgreSQL driver and connection pool for the optional production storage backend | No |
| pgx transitive modules | `github.com/jackc/pgpassfile v1.0.0`, `github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761`, `github.com/jackc/puddle/v2 v2.2.2`, `golang.org/x/crypto v0.37.0`, `golang.org/x/sync v0.13.0`, `golang.org/x/text v0.24.0` | BSD/MIT-style and Go project licenses | PostgreSQL configuration, pooling, and support libraries resolved by Go modules | No |
| coturn, <https://github.com/coturn/coturn> | source `678996a52954ddc7a44afd9f72f5b5c647e41083` (`4.7.0`); container build `aa685e2669bac662d553a3d8eef6412d95ba7664` (`docker/4.7.0-r0`) | BSD-3-Clause; the container also carries its base/library licenses | External interoperable TURN data plane pinned by multi-platform digest `sha256:99bf5bf6ab1c119862d0c3d2dfb2bbf805a86a131492cab18c148be64ae7d978` | No |

The credential format implements the open TURN REST API mechanism documented
by coturn and uses the IETF TURN protocol family. coturn is not vendored or
linked into the control-plane image; the separate Phase 3 Compose service pulls
the digest-pinned upstream coturn image. Operators must retain its copyright,
LICENSE, bundled dependency notices, and release SBOM. No GPL or AGPL source
was consulted or copied for this implementation.
