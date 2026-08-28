# Phase 3 deployment profiles

This directory contains two deliberately separate deployment slices:

- `docker-compose.authority.yml` runs Authority with a persistent local
  PostgreSQL for development and CI.
- `docker-compose.authority.production.yml` is a production-shaped Authority
  profile that requires an external PostgreSQL, immutable image digest, and
  runtime secret files.
- `docker-compose.yml` runs the experimental relay credential service beside
  coturn for local testing.
- `docker-compose.production.yml` is a production-shaped profile for signaling,
  relay credential issuance, and coturn. It requires external PostgreSQL
  databases, immutable image digests, and runtime secret files.

They are not an integrated public Internet stack. Authority-backed signaling and
relay credential admission can both call the shared Authority service, but these
profiles still do not provide automatic account/session issuance, public ingress,
validated multi-instance throughput, or active revocation of an established
PeerConnection/TURN allocation.

## Authority local profile

Requirements are Docker Engine with Compose v2 and OpenSSL. Generate disposable
local secrets, validate the effective model, and start the stack:

```bash
cd deploy/phase3
./scripts/generate-authority-secrets.sh
docker compose -f docker-compose.authority.yml config --quiet
docker compose -f docker-compose.authority.yml up -d --build --wait
curl --fail http://127.0.0.1:8091/healthz
curl --fail http://127.0.0.1:8091/readyz
```

PostgreSQL data is retained in the `authority-postgres` named volume. PostgreSQL
must be healthy before the one-shot migration runs, and Authority starts only
after that job exits successfully. The migration job receives only its database
URL; runtime API and role-token secrets are mounted only into Authority.

This profile uses one PostgreSQL role and `sslmode=disable` inside its private
Compose network. It binds Authority HTTP to host loopback and is only for local
development and CI. It is not a TLS, secret-management, backup, high-availability,
multi-instance, or public-network example. Stop it while preserving data with:

```bash
docker compose -f docker-compose.authority.yml down
```

Use `down --volumes` only when deliberately discarding the local admission,
revocation, and session-epoch ledger. The local secret generator refuses to
overwrite files, protects their parent directory with mode `0700`, and makes the
files read-only so Compose can mount them for the fixed container UID 65532.

## Authority production-shaped profile

Copy `config/authority.production.example.json` to the ignored
`config/authority.production.json`, review every limit, then provide:

- `VIBE_AUTHORITY_IMAGE_REPOSITORY` and the exact 64-character
  `VIBE_AUTHORITY_IMAGE_SHA256`; Compose constructs a digest-only image reference;
- independent migration/runtime PostgreSQL URL files and independent admin,
  signaling, relay, coturn, and role-token secret files from the deployment
  secret manager;
- an external managed PostgreSQL endpoint. The profile intentionally contains no
  database service or database volume.

Set `VIBE_AUTHORITY_CONFIG_FILE` only when the reviewed configuration lives at a
different host path; the default is the ignored production file above.
File-backed Compose secrets must be readable by UID 65532 inside the container.
Materialize them as UID/GID 65532 with restrictive mode, or place read-only files
under an operator-only parent directory; never solve a permission failure by
running Authority as root.

The migration URL should use a short-lived DDL role. The runtime URL should use a
least-privilege DML role. Both must use certificate and hostname verification,
normally `sslmode=verify-full`; the production profile enforces that exact mode
before either migration or runtime startup. `sslmode=disable` is local-only.
Authority has no built-in HTTP TLS, so keep its loopback listener behind an
authenticated private TLS 1.2+ proxy or service mesh and deny public ingress.

Before deployment, require a monitored NTP source for the host and database, an
alerted clock-offset budget, managed PostgreSQL HA/encryption, PITR with defined
RPO/RTO, and a recent restore exercise. Authority expiry and session-epoch checks
must fail closed during dependency or time uncertainty; never widen TTLs or mint
local fallback epochs/credentials to mask clock or database failures. The profile
does not itself monitor NTP offset, configure PostgreSQL backups, or prove a
multi-process Authority rollout, so those remain external production gates.

Back up before migration, review the migration checksum, validate Compose, run the
one-shot migration, and require `/readyz` plus an admission/authorization canary
before routing callers. `/healthz` only proves the process is alive; `/readyz` also
requires the database and exact schema. A database outage therefore leaves
`/healthz` at 200 while `/readyz` and storage-backed writes fail with 503.

Roll back image and configuration together, but never restore an older logical
revocation or session-epoch state as an application rollback. Database recovery
must use the approved PITR procedure, reconcile its recovery point, and keep
callers fail-closed until the recovered ledger is verified. The current profile
runs one Authority process; shared-database multi-instance correctness and rollout
behavior are not claimed.

Run the bounded local container gate with:

```bash
make phase3-authority-container-test
```

It builds the image, validates both Authority Compose files, exercises a real
PostgreSQL migration, readiness, admission/authorization, Authority restart
persistence, database-outage failure, runtime hardening, and secret-log scan. It
does not prove production TLS, NTP, backup/restore, public ingress, or multi-node
behavior.

## Signaling production configuration

The production profile now includes `signaling-migrate` and `signaling` services
that use the same external PostgreSQL and immutable-image pattern as the relay
profile. Copy `config/signaling.production.example.json` to the ignored
`config/signaling.production.json`, point `authority_url` at the private
Authority endpoint, and keep `authority_mode=production_authority` with
`store_backend=postgres`.

Provide `VIBE_SIGNALING_IMAGE_REPOSITORY` and
`VIBE_SIGNALING_IMAGE_SHA256`, independent migration/runtime PostgreSQL URL
secret files, and independent issuer, metrics, and Authority client token files.
The migration and runtime PostgreSQL URLs may use different credentials, but
they must target the same PostgreSQL database and schema so the migration job
creates the exact schema used by runtime readiness and traffic.
Both URLs must include `sslmode=verify-full`; the production profile sets
`VIBE_SIGNALING_DATABASE_TLS_MODE=verify-full` for migration and runtime so
weaker modes fail closed at startup.

```bash
export VIBE_SIGNALING_IMAGE_REPOSITORY=<registry>/<vibe-signaling-image>
export VIBE_SIGNALING_IMAGE_SHA256=<64-character-image-digest>
export VIBE_SIGNALING_MIGRATION_DATABASE_URL_FILE=<path-to-signaling-migration-db-url-secret>
export VIBE_SIGNALING_DATABASE_URL_FILE=<path-to-signaling-runtime-db-url-secret>
export VIBE_SIGNALING_ISSUER_TOKEN_FILE=<path-to-signaling-issuer-token-secret>
export VIBE_SIGNALING_METRICS_TOKEN_FILE=<path-to-signaling-metrics-token-secret>
export VIBE_SIGNALING_AUTHORITY_TOKEN_FILE=<path-to-signaling-authority-token-secret>
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml pull signaling
docker compose -f docker-compose.production.yml up -d --wait signaling
curl --fail http://127.0.0.1:8088/readyz
```

The migration job applies `001_signaling.sql` behind an advisory lock and a
checksum ledger. `/readyz` requires PostgreSQL reachability, exact schema,
database/application clock-skew proof, and Authority readiness. With PostgreSQL,
any signaling instance can authorize, publish, poll, and invalidate any
short-lived session row. Long-poll waiters are stored as connection-scoped
leases keyed by PostgreSQL backend PID and backend start time, so a replacement
instance can reclaim a waiter slot after the failed instance database backend
disappears.

The signaling runtime role must either be shared by all signaling instances or
have `pg_read_all_stats`/`pg_monitor` so live listener backend start times are
visible in `pg_stat_activity`. If a pooler sits between signaling and
PostgreSQL, use session pooling; transaction pooling breaks `LISTEN` and stable
backend identity.

Place signaling behind a private TLS 1.2+ reverse proxy or service mesh and route
only client role endpoints publicly. Keep issuer and metrics endpoints internal.
No sticky sessions are required for rendezvous correctness, but this profile has
not proved multi-replica throughput, global create-rate enforcement, production
load-balancer behavior, or multi-region consistency.

## Relay data plane

This directory runs the Vibe Screen relay credential service beside a real
coturn TURN/STUN data plane. Both processes read the same runtime-only TURN REST
secret. The control plane issues a short-lived username/password; coturn checks
that HMAC before creating an allocation. TURN forwards WebRTC ciphertext and
does not receive Vibe Screen content keys or plaintext screen/input data.

## Relay local start and health check

Requirements are Docker Engine with Compose v2 and OpenSSL. Docker Desktop can
run this local profile, but the production host-network profile is Linux-only.

```bash
cd deploy/phase3
./scripts/generate-secrets.sh
docker compose pull coturn
docker compose build relay
docker compose up -d --wait
curl --fail http://127.0.0.1:8090/healthz
curl --fail http://127.0.0.1:8090/readyz
./scripts/verify-stack.sh
```

The last command asks the live control plane for a 120-second credential and
runs `turnutils_uclient` inside the coturn container. It fails unless actual
authenticated allocations exchange relayed packets. Container health checks
cover coturn STUN responsiveness and relay-process liveness; `/readyz` is the
authoritative relay storage readiness check and, in `production_authority` mode,
also requires Authority readiness. A network-disabled one-shot init
container assigns the named state volume to relay UID/GID 65532 before the
non-root scratch control-plane container starts.

The local profile intentionally disables TURN TLS and allows loopback peers so
the self-contained test works. Its relay UDP allocation range is
`49160-49200`, bound only to host loopback. It is not suitable for public
exposure. A phone cannot use the advertised/bound `127.0.0.1`: explicitly bind
the Compose TURN and relay-range ports to the Mac's device-reachable address
and replace the local JSON URIs before a separately authorized device test.

Stop without deleting quota state:

```bash
docker compose down
```

Delete the named `relay-data` volume only when deliberately discarding local
quota/revocation state. Secret files under `secrets/` and TLS files under
`tls/` are ignored by Git; `generate-secrets.sh` refuses to overwrite them.

## Relay production configuration

Production uses host networking so coturn can bind the full relay port range
without Docker userland-proxy mappings. Perform these steps on a dedicated
Linux host:

1. Copy `config/relay.production.example.json` to the ignored
   `config/relay.production.json`. Replace every example hostname and verify
   its `turn_realm` equals `COTURN_REALM`. Keep
   `authority_mode=production_authority`, point `authority_url` at the private
   Authority endpoint, and set `authority_source_id` to a stable identifier for
   this TURN source. Keep the real Authority URL outside tracked files, PR text,
   commit messages, and public logs; use placeholders in public documentation.
   The production example selects `storage_backend: postgres`;
   do not change it to the file backend for a multi-process or public
   deployment. In PostgreSQL mode the relay ignores `state_file`, so the
   production example omits it and the Compose profile intentionally has no
   `/data` volume for file-backed quota state. Keep `allocation_registry_file`
   on the writable
   `/var/lib/vibe-coturn` mount so relay can persist the Authority
   `allocation_id` to TURN REST username mapping used by operator coturn
   control helpers.
2. Set `VIBE_RELAY_IMAGE_REPOSITORY` and the exact 64-character
   `VIBE_RELAY_IMAGE_SHA256`; Compose constructs a digest-only image reference
   and the production profile intentionally has no local relay build fallback.
3. Provision independent migration and runtime PostgreSQL URL secret files.
   Use a short-lived DDL role for migration and a least-privilege runtime role
   for relay. Both URLs must include `sslmode=verify-full` because the profile
   sets `VIBE_RELAY_DATABASE_TLS_MODE=verify-full`.
4. Provision independent secret files with mode `0600`: `turn_secret.txt`,
   `client_token.txt`, `usage_token.txt`, `metrics_token.txt`,
   `admin_token.txt`, and `authority_token.txt`. Distribute the same
   `turn_secret.txt` to relay and coturn, and provision `authority_token.txt`
   with the same value Authority exposes as `VIBE_AUTHORITY_RELAY_TOKEN`.
   Because the coturn container runs as UID/GID `65532`, make
   `turn_secret.txt` owned by `65532:65532` or otherwise readable by that
   account while retaining `0600` permissions. Store/rotate all secrets through
   the deployment secret manager, not source control.
5. Create the ignored `coturn-state` directory, or set
   `VIBE_COTURN_ALLOCATION_REGISTRY_DIR` to another pre-created host path, and
   make it writable by relay UID/GID `65532`. The Compose bind mount sets
   `create_host_path: false` so a missing directory fails startup instead of
   being created with root ownership. Relay `/readyz` fails closed if the
   configured allocation registry cannot be read or atomically updated.
6. Install the public certificate chain as ignored `tls/fullchain.pem` and its
   private key as `tls/privkey.pem`.
7. Set `COTURN_REALM` to the certificate DNS hostname and
   `COTURN_EXTERNAL_IP` to either `<public-ip>` on a directly addressed host or
   `<public-ip>/<private-ip>` behind one-to-one NAT. Do not write a real IP
   address into tracked files, PR text, commit messages, or public logs.
8. Allow inbound UDP/TCP 3478, TCP 5349, and UDP 49152-65535. Keep relay HTTP
   on loopback behind an authenticated TLS reverse proxy. Apply provider DDoS
   controls before these host rules.
9. Validate the effective configuration, start, and inspect health/logs:

```bash
export COTURN_REALM=relay.example.com
export COTURN_EXTERNAL_IP=<public-ip>
# Behind one-to-one NAT, use: COTURN_EXTERNAL_IP=<public-ip>/<private-ip>
export VIBE_RELAY_IMAGE_REPOSITORY=<registry>/<vibe-relay-image>
export VIBE_RELAY_IMAGE_SHA256=<64-character-image-digest>
export VIBE_RELAY_MIGRATION_DATABASE_URL_FILE=<path-to-relay-migration-db-url-secret>
export VIBE_RELAY_DATABASE_URL_FILE=<path-to-relay-runtime-db-url-secret>
export VIBE_SIGNALING_IMAGE_REPOSITORY=<registry>/<vibe-signaling-image>
export VIBE_SIGNALING_IMAGE_SHA256=<64-character-image-digest>
export VIBE_SIGNALING_MIGRATION_DATABASE_URL_FILE=<path-to-signaling-migration-db-url-secret>
export VIBE_SIGNALING_DATABASE_URL_FILE=<path-to-signaling-runtime-db-url-secret>
export VIBE_SIGNALING_ISSUER_TOKEN_FILE=<path-to-signaling-issuer-token-secret>
export VIBE_SIGNALING_METRICS_TOKEN_FILE=<path-to-signaling-metrics-token-secret>
export VIBE_SIGNALING_AUTHORITY_TOKEN_FILE=<path-to-signaling-authority-token-secret>
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml pull signaling relay coturn
docker compose -f docker-compose.production.yml up -d --wait
curl --fail http://127.0.0.1:8088/readyz
curl --fail http://127.0.0.1:8090/readyz
docker compose -f docker-compose.production.yml logs --since=10m signaling relay coturn
```

Before treating this as public NAT/TURN release evidence, write a sanitized
connectivity JSON outside the repository and run the fail-closed preflight:

```bash
python3 ../../scripts/phase3/public_nat_turn_preflight.py \
  --relay-config ./config/relay.production.json \
  --coturn-config ./coturn/production.conf \
  --turn-secret-file ./secrets/turn_secret.txt \
  --tls-certificate ./tls/fullchain.pem \
  --tls-private-key ./tls/privkey.pem \
  --coturn-external-ip "$COTURN_EXTERNAL_IP" \
  --authority-ready-url https://authority.example.com/readyz \
  --relay-ready-url https://relay.example.com/readyz \
  --connectivity-evidence <path-to-sanitized-connectivity-evidence.json> \
  --deployment-evidence <path-to-sanitized-deployment-evidence.json> \
  --output <path-to-public-nat-turn-preflight-output.json> \
  --connectivity-command <path-to-public-turn-canary-command>
```

The preflight returns non-zero and records `blocked` when any public address,
runtime secret, TLS material, readiness probe, quota/ACL invariant, or remote
connectivity artifact is missing. A saved `--connectivity-evidence` file is only
reviewed context; pass evidence requires `--connectivity-command` to run an
external observer during the preflight and emit a matching sanitized JSON record
on stdout. `--deployment-evidence` is a separate production-readiness record: it
must prove the public STUN endpoint, UDP/TCP TURN, TLS TURN, certificate hostname
validation, TLS 1.2 or newer, quota enforcement, credential rotation with old
credential rejection after TTL, allocation/auth-failure/relay-byte/quota
monitoring, alert rules, and at least two remote observers outside the host
network. Use `--allow-blocked` only to archive a readiness blocker. The
checked-in example config, local coturn profile, loopback runs, and synthetic
peers are expected to remain blocked and cannot close the public Internet or
remote TURN gates.

The `relay-migrate` job applies `001_relay.sql` behind an advisory lock and a
checksum ledger. Relay starts only after that job exits successfully. `/readyz`
requires the database, schema checksum, required relations/columns/constraints,
and database clock skew to be inside the configured bound. A database outage or
schema drift leaves `/healthz` at 200 while `/readyz`, credential issuance,
usage writes, revocation, and metrics fail closed with 503.

After production readiness passes, record the public Internet soak boundary from
the source revision under test with `make phase3-internet-soak-manifest`, then
evaluate it with `make phase3-internet-soak-gate` after the remote TURN, media
continuity, network handoff, revocation propagation, and two-hour soak summaries
have been privacy reviewed. The gate rejects local-only TURN, missing TLS or
secret-source declarations, absent readiness probes, missing remote peers, and
partial report families as `blocked`; it never converts this production profile
or the local Compose profile into public Internet evidence by itself.

`production.conf` enables UDP/TCP TURN, TLS on 5349, TLS 1.2+, fingerprints,
short nonces, stable per-device and total allocation quotas, a 20 MB/s
allocation cap, and a bounded relay range. Its CREATE_PERMISSION policy denies
unspecified, RFC1918, CGNAT, loopback, IPv4/IPv6 link-local, ULA, deprecated
IPv6 site-local, protocol-assignment, and benchmark/internal ranges; multicast
peers are also denied. Add every provider VPC, metadata, container, Pod,
Service, and overlay range visible in the host routing table, with a host egress
firewall as a second layer. Never add a broad `allowed-peer-ip`, which takes
precedence over denies.

## Upgrade, rollback, and rotation

- Resolve a new immutable multi-platform image digest, audit its SBOM and
  licenses, update tag plus digest together, then run local credential/TURN and
  forced-relay canaries before production rollout.
- Back up the relay PostgreSQL database before changing the control-plane
  binary or applying a migration. Roll back binary/image/config together, but
  never restore an older logical device-revocation, usage, or active-session
  ledger as an application rollback. Database recovery must use the approved
  PITR procedure and keep callers fail-closed until the recovered ledger passes
  `/readyz` and an issuance/usage canary.
- Rotate API-token files one service at a time. TURN-secret rotation requires
  a bounded dual-key or drain window; this coturn profile accepts one REST
  secret, so the safe current procedure is to stop new credential issuance,
  wait at most the configured maximum credential TTL, drain allocations,
  replace the shared file on both services, and restart.
- Authority-backed revocation stops future credential issuance only. For urgent
  abuse, also disable the signaling session and drain/terminate matching coturn
  allocations; do not wait for credential expiry alone.

## Abuse, observability, and current limitations

coturn enforces `user-quota`, `total-quota`, `max-bps`, peer-address filters,
nonce expiry, and a fixed port range. The relay control plane separately rate
limits issuance and exposes `/metrics` behind a dedicated metrics token. Place
both behind host/provider connection limits and alert on authentication failures,
allocation growth, relay bytes, port exhaustion, and credential rejections.

TURN REST usernames use `<expiry>:<device-id>`, so coturn strips the expiry and
atomically counts all session/expiry credentials under one device principal.
`user-quota=12` is therefore a per-device allocation cap. In
`production_authority` mode, relay also asks Authority to admit each
`device_id/session_id/allocation_id/source_id` tuple before returning that TURN
credential and before accepting each non-duplicate relay usage event; revoked or
expired Authority sessions, revoked devices, and conflicting allocation identity
fail closed before coturn sees a credential or before the relay ledger advances.
Accepted credential grants are recorded in the relay allocation registry so
operator tooling can correlate Authority allocation IDs with coturn sessions.
Revalidate `user-quota` against legitimate UDP/TCP/TLS ICE allocation counts
before changing it. The repository now has a current-base local structured
exporter adapter, bounded reconciliation loop, local active-allocation state
disconnect executor, and coturn CLI control helper for exact registry-matched
allocations. These helpers are not deployed by this profile: there is still no
production-deployed coturn-to-`/v1/usage` collector, no production scheduler for
the bounded reconciliation loop, and no concrete live coturn active-allocation
disconnect evidence.
Therefore the control plane's daily-byte and per-device concurrent-session
accounting is not authoritative for this deployment; coturn's own limits remain
the immediate enforcement boundary.
Postgres removes the previous local-state blocker for multiple relay
control-plane processes, but it does not provide TURN usage collection, billing
reconciliation, production database backups, NTP monitoring, or multi-region
consistency by itself. These are production launch blockers, not
implied features.

## Provenance and license

No coturn source is copied into this repository. The Compose files execute the
external image below and the repository contributes only original
configuration and test scripts:

| Artifact | Immutable source | License | Use |
| --- | --- | --- | --- |
| coturn source | <https://github.com/coturn/coturn>, tag `4.7.0`, commit `678996a52954ddc7a44afd9f72f5b5c647e41083` | BSD-3-Clause | TURN/STUN server implementation; no source copied |
| coturn container | `coturn/coturn:4.7.0-r0`, manifest `sha256:99bf5bf6ab1c119862d0c3d2dfb2bbf805a86a131492cab18c148be64ae7d978`, image-build revision `aa685e2669bac662d553a3d8eef6412d95ba7664` | coturn BSD-3-Clause plus licenses of bundled distribution libraries | Runtime data plane; no image layer vendored |

The arm64 child manifest observed during verification was
`sha256:caac4599652148becc606d7cfc7acbc8cb42012df27ae013a627bde4ff493d4c`.
The upstream BSD license and copyrights remain in the image. A public release
must archive the image SBOM and all bundled dependency notices; describing the
whole image as only BSD-3-Clause would be incomplete. No GPL/AGPL code was
copied or translated for this deployment.
