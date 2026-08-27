---
name: deploy
description: |
  Deploy Vibe Screen relay or run deployment readiness checks. Use this skill when the user says /deploy, asks to deploy relay.taoai.site, operate the Phase 3 relay stack, prepare deployment docs, run production preflight, or diagnose relay deployment status. Keep public repository output open-source safe: never write private IPs, SSH usernames, local home paths, device serials, tokens, keys, or secret values into tracked files.
argument-hint: '[preflight|local|production|status|rollback]'
---

# Vibe Screen Deploy

Use this skill for Vibe Screen deployment work, especially the Phase 3 relay
stack under `deploy/phase3`. Start from the repository top level unless the user
gives a different checkout.

## First Steps

1. Read `DEPLOY.md` and `deploy/phase3/README.md` before changing deployment
   state.
2. Run a read-only status check first: `git status --short --branch`, DNS for
   `relay.taoai.site`, Docker/Compose availability on the target host, disk
   space, and listening ports.
3. Keep the local SSH alias `lumina-vps` opaque. It is acceptable to run
   `ssh lumina-vps ...`; do not expand that alias into an address or username in
   repository files, PR text, commit messages, or public logs.

## Open-Source Safety

- Never commit private IP addresses, SSH usernames, home-directory paths, Android
  serials, TLS private keys, tokens, API keys, database URLs, or generated secret
  files.
- Use placeholders in tracked docs: `<public-or-nat-mapping>`,
  `<registry>/<image>`, `<64-character-image-digest>`, and
  `<path-to-secret-file>`.
- Runtime material belongs in ignored locations documented by `DEPLOY.md`, or in
  the deployment secret manager.
- Before reporting a deployment-related diff as ready, run a sensitive scan over
  changed docs and skill files.

Suggested scan workflow:

1. Put deployment-specific private values in an ignored local pattern file, one
   regex per line.
2. Run `rg -n -f <private-pattern-file> DEPLOY.md .claude/skills/deploy/SKILL.md`.
3. Separately scan for key material, generated secret files, and concrete local
   paths introduced by the current diff.

## Preflight Mode

Use preflight when prerequisites are uncertain or the user asks whether the relay
is deployed. Prefer read-only commands:

~~~bash
dig +short relay.taoai.site A relay.taoai.site AAAA
ssh lumina-vps 'docker --version && docker compose version'
ssh lumina-vps 'df -h / && docker system df'
ssh lumina-vps 'ss -ltnup | sed -n "1,160p"'
~~~

Report production as blocked if DNS, TLS, disk headroom, image digest, database
secrets, or required port exposure are missing. Do not weaken TLS, readiness,
database, authentication, or storage checks to force a deployment through.

## Local Mode

Run the loopback-only relay profile for development validation:

~~~bash
cd deploy/phase3
./scripts/generate-secrets.sh
docker compose pull coturn
docker compose build relay
docker compose up -d --wait
curl --fail http://127.0.0.1:8090/healthz
curl --fail http://127.0.0.1:8090/readyz
./scripts/verify-stack.sh
~~~

This is not public deployment evidence. It binds to loopback and is unsuitable
for phones or Internet traffic without separate reviewed changes.

## Production Mode

Deploy production only after preflight is green and the user has supplied or
approved the required runtime material. Use `docker-compose.production.yml` and
immutable relay image digests. Relay is live only when `/readyz` passes.

Do not run broad Docker cleanup on a shared host without explicit confirmation.
If disk space blocks deployment, report what is reclaimable and ask before
pruning or deleting artifacts that may belong to other services.

## Reporting

Be explicit about the state:

- `deployed`: production profile is running and `/readyz` passed.
- `validated locally`: local loopback stack passed `verify-stack.sh` only.
- `blocked`: list the missing prerequisites and keep the current state unchanged.

Keep public-facing summaries free of host IPs, usernames, tokens, and local file
paths.
