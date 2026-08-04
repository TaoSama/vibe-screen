# Signaling operations

## Deployment checklist

- Bind the process to loopback or a private sidecar network.
- Terminate TLS 1.2+ at a maintained reverse proxy; redirect/reject plaintext.
- Restrict session creation/invalidation routes and `/metrics` to their internal callers.
- Inject separate 32+ character issuer and metrics tokens from a secret manager.
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
accepting traffic. Neither proves peer connectivity, TLS, TURN, or WebRTC. An
external synthetic should create a short session, exchange an offer/answer and
two candidates, then let it expire.

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

### Issuer token exposure

1. Remove external reachability to `/v1/sessions`.
2. Rotate `VIBE_SIGNALING_ISSUER_TOKEN` in the authority and signaling process.
3. Restart signaling; all in-memory sessions and stolen role tokens disappear.
4. Review low-cardinality creation/rejection metrics and redacted edge telemetry.
5. Rotate TURN service credentials separately if the authority could access them.

### Role token or SDP/ICE disclosure

Invalidate the known signaling session through the authority endpoint, block
the paired device at the authority, revoke new TURN issuance, and require a
fresh signed session epoch. Restart the instance if the session is unknown or
the issuer is compromised. Signaling invalidation does not revoke an already
active TURN allocation or WebRTC connection.

### Memory/capacity exhaustion

Keep readiness false by removing the instance from the proxy, preserve only
redacted metrics, restart to atomically delete in-memory state, then lower TTL/
caps or strengthen edge limiting before re-entry. Do not capture a core dump
containing live SDP, candidates, and tokens.

## Upgrade, rollback, and compatibility

The HTTP schema is versioned under `/v1`. Additive response fields are allowed;
removing fields, changing role/state semantics, changing idempotency, or changing
candidate/SDP framing requires a new API version. Run old and new binaries on
separate ports and use a synthetic exchange. Because state is not shared, drain
the old process for at least the configured maximum session TTL or explicitly
accept client reconnects before stopping it.

Rollback is binary/config rollback, not state recovery. Never copy opaque memory
state between versions. A restart invalidates all sessions by design; clients
must acquire new role credentials and use a new product session epoch.

## Backup and retention

There is no signaling database to back up. Back up only reviewed configuration,
deployment manifests, redacted metrics, and immutable binary/image digests. SDP,
ICE, bearer tokens, request bodies, and session identifiers must not enter logs,
traces, backups, analytics, or crash reports. Expired state is physically removed
from the process maps by request-time and periodic cleanup; Go heap reclamation
does not guarantee immediate byte-level erasure.
