# Vibe Screen signaling service

`vibe-signaling` is the runnable Phase 3 rendezvous service. It creates short-
lived sessions and exchanges only validated WebRTC offer, answer, ICE candidate,
and end-of-candidates records between an authenticated host and device. It does
not proxy data channels, media, input, long-lived private keys, application
traffic keys, pairing QR secrets, or arbitrary payloads.

Version `0.1.0` is a single-process, in-memory vertical slice. It is suitable for
local integration and one-instance deployments behind TLS. It is not an account
service, durable multi-replica broker, device revocation authority, or proof that
the product stream is end-to-end encrypted. Endpoints must still authenticate
the signed Vibe Screen session transcript and DTLS fingerprint independently.

## Build and run

Requirements: Go 1.23 or newer. The tested local toolchain is Go 1.24.13.

```bash
cd services/signaling
cp config.example.json config.json
export VIBE_SIGNALING_ISSUER_TOKEN="$(openssl rand -base64 48)"
export VIBE_SIGNALING_METRICS_TOKEN="$(openssl rand -base64 48)"
go build -trimpath -o build/vibe-signaling ./cmd/vibe-signaling
./build/vibe-signaling --config config.json
```

Do not put either token in the JSON file, shell history, repository, mobile app,
or diagnostic bundle. In production, inject them from a secret manager. The
issuer token belongs only to the trusted session-authority backend; a host or
Android binary must receive a session-scoped role token, never this global
credential. The metrics token belongs only to the Prometheus collector.

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

`SIGTERM` and `SIGINT` stop readiness, cancel long polls, drain HTTP requests,
and exit with a bounded ten-second shutdown deadline.

## Protocol v1 HTTP API

Every response has `Cache-Control: no-store`. JSON request bodies require
`Content-Type: application/json`, reject unknown fields and trailing objects,
and are capped before decoding. Bearer tokens are random, scoped in server state
to exactly one session and role, and expire with the session. The request body
never selects its own role.

Create a session through the trusted authority:

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $VIBE_SIGNALING_ISSUER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"01J-AUTHORITY-RETRY-ID","ttl_seconds":300}' \
  http://127.0.0.1:8088/v1/sessions
```

The `201` response contains an opaque `session_id`, separate `host_token` and
`device_token`, and `expires_at`. Deliver each role token over an already
authenticated channel to that endpoint. Repeating the same `request_id` and TTL
returns the identical response with `200`; changing the TTL returns `409`.

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
by default. Sessions and all SDP/ICE state are deleted from memory at TTL.

### Status codes

| Code | Meaning |
| --- | --- |
| `200` | Poll success or exact idempotent replay |
| `201` | Session or message created |
| `400` | Invalid JSON, query, identifier, payload, or configured limit |
| `401` | Invalid internal issuer/metrics authentication |
| `404` | Unknown session or wrong session/role bearer; deliberately indistinguishable |
| `409` | Role/state violation or conflicting idempotency replay |
| `410` | Session expired and the caller proved possession of its role token |
| `429` | Rate, waiter, candidate, or active-session limit reached |

## Configuration and limits

All JSON fields are required. Unknown fields fail startup.

| Field | Purpose |
| --- | --- |
| `listen_address` | TCP bind address; keep loopback unless a secure sidecar provides TLS |
| `session_ttl_seconds`, `max_session_ttl_seconds` | Default and authority-selectable upper TTL |
| `max_active_sessions` | Hard in-memory session cap |
| `session_creates_per_minute` | Global trusted-authority request cap per process |
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
- `GET /readyz` is unauthenticated readiness and reveals no dependency details.
- `GET /metrics` requires the independent metrics bearer.

Prometheus output contains low-cardinality counts for sessions, accepted
messages, idempotent retries, rejected requests, poll timeouts, expired cleanup,
and an active-session gauge. It has no session/device/IP/token labels. Logs are
limited to lifecycle and generic network-write failures; raw SDP, candidates,
tokens, keys, stable identifiers, and source addresses are never logged.

## Container

The Dockerfile uses an immutable Go 1.24.13 Alpine build image and a `scratch`
runtime. The final image contains only a static binary and runs as UID/GID
65532. Mount the config read-only and inject secrets:

```bash
docker build --build-arg VERSION=0.1.0 -t vibe-signaling:0.1.0 .
docker run --rm --read-only --cap-drop=ALL \
  -p 127.0.0.1:8088:8088 \
  -e VIBE_SIGNALING_ISSUER_TOKEN \
  -e VIBE_SIGNALING_METRICS_TOKEN \
  -v "$PWD/config.container.example.json:/etc/vibe-screen/signaling.json:ro" \
  vibe-signaling:0.1.0
```

The container example binds `0.0.0.0:8088`; the published host port remains
loopback unless a TLS proxy is in front. Docker was unavailable in the recorded local
environment, so image execution remains unverified; the native process is
covered by the real-process integration test.

## Verification

```bash
make verify
go test -run TestRealProcessHostDeviceExchangeAndGracefulShutdown -count=1 .
```

The process test builds and starts the real binary, waits for health, creates a
session, performs offer/answer and bidirectional ICE exchange, scrapes metrics,
sends `SIGTERM`, verifies a clean exit, and checks that known SDP/candidate/token
secrets were absent from logs. This proves rendezvous behavior, not a WebRTC ICE
connection or TURN allocation.

## Upgrade and rollback

1. Back up the config and record the current image digest/binary checksum.
2. Read release notes and diff `config.example.json`; startup rejects unknown or
   missing fields instead of silently using unsafe defaults.
3. Start the new instance on a separate loopback port, verify `/healthz`,
   `/readyz`, authenticated `/metrics`, and run a synthetic two-peer exchange.
4. Drain the old instance before switching traffic. Sessions are in memory and
   do not migrate; a rolling restart requires clients to create a fresh session.
5. Roll back by routing to the prior binary/image. Existing sessions on the
   failed instance are intentionally lost and credentials must not be reused.

See [OPERATIONS.md](OPERATIONS.md) for production controls and incident actions,
and [THREAT_MODEL.md](THREAT_MODEL.md) for the security boundary and residual
risks.

## Provenance and licensing

No third-party source code was copied into this module and `go list -m all`
contains only this module. Runtime code uses the Go standard library.

| Project | Immutable version | License | Use | Copied code |
| --- | --- | --- | --- | --- |
| Go | `go1.24.13`, <https://github.com/golang/go/tree/go1.24.13> | BSD-3-Clause | compiler/build stage and standard-library runtime | No source copied; standard library linked into binary |
| Official Go container | `golang:1.24.13-alpine3.22@sha256:3641e0d9b931dc4f2f185dcd669c4679670e9277c8166a838ddb98a2d4389cb5` | Go BSD-3-Clause plus Alpine package licenses | build stage only; absent from final `scratch` image | No |
| SideScreen | commit `a651a81b7d6468c7a564c038551872d3346a2d55`, <https://github.com/tranvuongquocdat/SideScreen> | MIT | repository architecture context only | No |
| Telemachus | commit `a5dd1298870846d749175812f936ceebfd8b6b69`, <https://github.com/aaditagrawal/telemachus> | MIT | repository reliability context only | No |

The container digest was read from Docker Registry's immutable manifest on
2026-08-04. The original Vibe Screen signaling code still requires the project
owner to select a repository-wide license before public distribution; the root
repository currently states that as a release blocker. No GPL/AGPL source was
consulted or copied for this implementation.
