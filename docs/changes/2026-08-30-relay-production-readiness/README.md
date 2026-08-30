# 2026-08-30 relay.taoai.site production readiness preflight

Status: blocked. This record is a read-only preflight snapshot only. It does not
deploy, start, stop, or change the production relay stack.

## Result

- Deployment state: **blocked**
- `/readyz`: not runnable
- Remote host preflight: partial operator-local inspection completed; Docker and
  Compose were present, while disk headroom, production listeners, and remote
  `/readyz` remained blocked.
- Public deployment claim: none

## Preflight checks

| Check | Result | Evidence / blocker |
| --- | --- | --- |
| Relay DNS | BLOCKED | `relay.taoai.site` returned `NXDOMAIN`; no A or AAAA answer. |
| Local SSH alias availability | PASS (operator-local only) | A private operator SSH alias reached the intended host during this preflight. The alias, address, and username are intentionally not recorded in this public evidence. |
| Production host Docker/Compose | PASS | The remote host reported Docker Engine and Docker Compose availability. This only proves tool availability, not deployment readiness. |
| Production host disk | BLOCKED | The remote system filesystem was about 96% used with less than 1 GiB free. This is insufficient headroom for production image pull/build, logs, rollback, and safe operation. |
| Production host ports | BLOCKED | Existing listeners were observed on unrelated service ports. No production relay/signaling/TURN listeners for TCP `3478`, TCP `5349`, local `8088`/`8090`, or the UDP relay range were validated. |
| Local `/readyz` | BLOCKED | No listener on loopback ports `8088` or `8090`; curl exit 7 / HTTP 000. |
| Remote `/readyz` | BLOCKED | No production relay or signaling stack was observed, and no remote loopback `/readyz` endpoint was validated. |
| Relay production secrets | BLOCKED | Tracked/ignored runtime files were not present in this worktree: `deploy/phase3/secrets/{turn_secret,client_token,usage_token,metrics_token,admin_token,authority_token}.txt`, `deploy/phase3/tls/fullchain.pem`, `deploy/phase3/tls/privkey.pem`. No production env `VIBE_RELAY_MIGRATION_DATABASE_URL_FILE`, `VIBE_RELAY_DATABASE_URL_FILE`, `VIBE_SIGNALING_*` DB URL files, issuer/metrics/authority token files, or image digest values were provided/visible. |
| TLS prerequisite | BLOCKED | No ignored production TLS files present in this worktree. |
| Immutable image digests | NOT CONFIRMED | No production image repository/digest values were provided/visible. |
| DNS/TLS/port prerequisites | BLOCKED | DNS prerequisite failed, so required inbound UDP/TCP `3478`, TCP `5349`, and UDP `49152-65535` are not validated. |

## What to unblock next

- Add a working public DNS record for `relay.taoai.site` pointing to the
  intended relay host.
- Free or expand production-host system disk space before pulling images or
  starting the production profile.
- Provision ignored production TLS and relay/signaling secret files with the
  expected file layout and `sslmode=verify-full` PostgreSQL URLs.
- Provide production relay/signaling image repository plus exact SHA-256
  digests.
- Re-run the host preflight with the private local SSH alias and confirm the
  required TURN, signaling, relay, and readyz ports are bound to the intended
  interfaces.
- Start or confirm the production stack, then require `http://127.0.0.1:8088/readyz`
  and `http://127.0.0.1:8090/readyz` to pass before any public deployment claim.

## Safety

This record intentionally uses no real IP addresses, SSH usernames, local home
paths, tokens, private keys, database URLs, or secret values.
