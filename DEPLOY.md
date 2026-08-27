# Deployment

This repository contains a production-shaped Phase 3 relay deployment profile
under `deploy/phase3`. Treat deployment as an operator-controlled process: the
public repository documents required checks and placeholders, while hostnames,
credentials, certificates, database URLs, image digests, and infrastructure
details stay outside Git.

The default relay hostname is `relay.taoai.site`. Operators may keep a local SSH
alias named `lumina-vps` for the relay host, but the alias is local machine
configuration and must not be expanded into an address, username, or credential
inside this repository.

## Safety Rules

- Do not commit IP addresses, SSH usernames, local home-directory paths, Android
  device serials, TLS private keys, tokens, database URLs, or generated secret
  files.
- Use ignored files under `deploy/phase3/config/`, `deploy/phase3/secrets/`, and
  `deploy/phase3/tls/` for operator-provided runtime material.
- Keep relay HTTP bound to loopback or a private network behind an authenticated
  TLS reverse proxy. Public ingress is for TURN/STUN, not the relay control API.
- Prefer immutable image digests for production rollout. Do not deploy a mutable
  tag as the production source of truth.
- If a prerequisite is missing, stop at the preflight result and report the
  blocker instead of weakening TLS, storage, readiness, or authentication gates.

## Preflight Checklist

Run these checks before any production rollout:

```bash
dig +short relay.taoai.site A relay.taoai.site AAAA
ssh lumina-vps 'docker --version && docker compose version'
ssh lumina-vps 'df -h / && docker system df'
ssh lumina-vps 'ss -ltnup | sed -n "1,160p"'
```

Production deployment is blocked until all of these are true:

- `relay.taoai.site` resolves to the intended relay host.
- The host has enough free disk for images, build cache, logs, and rollback.
- Docker Engine and Docker Compose are installed and healthy.
- TLS material exists as ignored files: `deploy/phase3/tls/fullchain.pem` and
  `deploy/phase3/tls/privkey.pem`.
- Production secrets and PostgreSQL URL files exist outside source control and
  are readable by the service UID expected by the Compose profile. Required
  relay runtime secret files are `deploy/phase3/secrets/turn_secret.txt`,
  `deploy/phase3/secrets/client_token.txt`,
  `deploy/phase3/secrets/usage_token.txt`,
  `deploy/phase3/secrets/metrics_token.txt`,
  `deploy/phase3/secrets/admin_token.txt`, and
  `deploy/phase3/secrets/authority_token.txt`. The relay also requires separate
  migration and runtime PostgreSQL URL secret files supplied through
  `VIBE_RELAY_MIGRATION_DATABASE_URL_FILE` and
  `VIBE_RELAY_DATABASE_URL_FILE`; keep those files outside Git and out of
  shell history.
- Both relay PostgreSQL URLs use `sslmode=verify-full`; the production Compose
  profile enforces `VIBE_RELAY_DATABASE_TLS_MODE=verify-full` for migration and
  runtime, so weaker `sslmode` values fail startup instead of silently
  downgrading TLS.
- Required inbound ports are open: UDP/TCP `3478`, TCP `5349`, and UDP
  `49152-65535`.
- The relay image repository and exact SHA-256 digest are known.

## Local Relay Validation

The local profile is self-contained and loopback-only. Use it for development and
CI-style verification, not public phones or Internet traffic.

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

Stop the local profile without deleting quota state:

```bash
cd deploy/phase3
docker compose down
```

## Production Relay Rollout

Prepare ignored production files on the deployment host or through the chosen
secret manager:

```bash
cd deploy/phase3
cp config/relay.production.example.json config/relay.production.json
install -d -m 0700 secrets tls
```

Review `config/relay.production.json` and set `turn_realm` to
`relay.taoai.site`. Keep `authority_mode` set to `production_authority`, set
`authority_url` to the private Authority endpoint using an operator-supplied
placeholder or secret-manager value, and set `authority_source_id` to the stable
identifier for this TURN source. Do not write an internal Authority URL into
tracked files, PR text, commit messages, or public logs. Keep `storage_backend`
set to `postgres`; in that mode relay ignores `state_file`, and the production
Compose profile intentionally has no `/data` volume for file-backed quota state.
The writable `coturn-state` bind mount is still required for
`allocation_registry_file`.

Export deployment parameters using placeholders that are supplied by the
operator environment or secret manager:

```bash
export COTURN_REALM=relay.taoai.site
export COTURN_EXTERNAL_IP=<public-ip>
# Behind one-to-one NAT, use: COTURN_EXTERNAL_IP=<public-ip>/<private-ip>
export VIBE_RELAY_IMAGE_REPOSITORY=<registry>/<vibe-relay-image>
export VIBE_RELAY_IMAGE_SHA256=<64-character-image-digest>
export VIBE_RELAY_MIGRATION_DATABASE_URL_FILE=<path-to-migration-db-url-secret>
export VIBE_RELAY_DATABASE_URL_FILE=<path-to-runtime-db-url-secret>
```

Validate the effective Compose model before starting anything:

```bash
cd deploy/phase3
docker compose -f docker-compose.production.yml config --quiet
```

Deploy only after the preflight checklist is green:

```bash
cd deploy/phase3
docker compose -f docker-compose.production.yml pull relay coturn
docker compose -f docker-compose.production.yml up -d --wait relay coturn
curl --fail http://127.0.0.1:8090/readyz
docker compose -f docker-compose.production.yml logs --since=10m relay coturn
```

The `relay-migrate` job runs database migration first. Relay startup is valid only
when `/readyz` passes; `/healthz` alone is insufficient because it does not prove
database/schema readiness.

## Rollback And Cleanup

- Roll back image digest, configuration, and secrets as one reviewed deployment
  set.
- Do not restore an older logical revocation, usage, or active-session ledger as
  a simple application rollback. Database recovery must follow the approved PITR
  procedure and pass `/readyz` plus an issuance canary before traffic resumes.
- Clean Docker artifacts only after checking active containers and confirming the
  artifacts are unused by other services on the host. Prefer targeted removal over
  broad pruning on a shared machine.

## Current Public Host Status

At the time this document was added, the deployment host was reachable through
the local `lumina-vps` alias and had Docker/Compose installed, but production
rollout remained blocked by unresolved DNS/TLS readiness and low system-disk
headroom. Re-run the preflight checklist before treating the relay as deployed.
