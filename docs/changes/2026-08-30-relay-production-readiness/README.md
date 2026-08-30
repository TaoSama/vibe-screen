# 2026-08-30 relay.taoai.site production readiness preflight

Status: blocked. This record is a read-only preflight snapshot only. It does not
deploy, start, stop, or change the production relay stack.

## Result

- Deployment state: **blocked**
- `/readyz`: not runnable
- Public deployment claim: none

## Preflight checks

| Check | Result | Evidence / blocker |
| --- | --- | --- |
| Relay DNS | BLOCKED | `relay.taoai.site` returned `NXDOMAIN`; no A or AAAA answer. |
| Local SSH alias availability | BLOCKED | No usable operator-local alias resolved from this workspace/run. Production host checks could not be executed. |
| Docker/Compose locally | PASS (local dev machine only) | `docker --version` and `docker compose version` available locally; this does not prove remote production host readiness. |
| Production host disk | NOT CHECKED | Blocked by SSH alias availability. |
| Production host ports | NOT CHECKED | Blocked by SSH alias availability. |
| Local `/readyz` | BLOCKED | No listener on loopback ports `8088` or `8090`; curl exit 7 / HTTP 000. |
| Remote `/readyz` | NOT CHECKED | Blocked by SSH alias availability. |
| Relay production secrets | BLOCKED | Tracked/ignored runtime files were not present in this worktree: `deploy/phase3/secrets/{turn_secret,client_token,usage_token,metrics_token,admin_token,authority_token}.txt`, `deploy/phase3/tls/fullchain.pem`, `deploy/phase3/tls/privkey.pem`. No production env `VIBE_RELAY_MIGRATION_DATABASE_URL_FILE`, `VIBE_RELAY_DATABASE_URL_FILE`, `VIBE_SIGNALING_*` DB URL files, issuer/metrics/authority token files, or image digest values were provided/visible. |
| TLS prerequisite | BLOCKED | No ignored production TLS files present in this worktree. |
| Immutable image digests | NOT CONFIRMED | No production image repository/digest values were provided/visible. |
| DNS/TLS/port prerequisites | BLOCKED | DNS prerequisite failed, so required inbound UDP/TCP `3478`, TCP `5349`, and UDP `49152-65535` are not validated. |

## What to unblock next

- Add a working public DNS record for `relay.taoai.site` pointing to the
  intended relay host.
- Provide a working local SSH alias for the relay host (not written here) and
  re-run the host preflight: `docker --version`, `docker compose version`, disk
  headroom, `docker system df`, and port listeners.
- Provision ignored production TLS and relay/signaling secret files with the
  expected file layout and `sslmode=verify-full` PostgreSQL URLs.
- Provide production relay/signaling image repository plus exact SHA-256
  digests.
- Start or confirm the production stack, then require `http://127.0.0.1:8088/readyz`
  and `http://127.0.0.1:8090/readyz` to pass before any public deployment claim.

## Safety

This record intentionally uses no real IP addresses, SSH usernames, local home
paths, tokens, private keys, database URLs, or secret values.
