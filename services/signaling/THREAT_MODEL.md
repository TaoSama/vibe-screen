# Signaling threat model

## Assets and trust boundary

Protected assets are session role bearers, SDP/ICE rendezvous integrity and
availability, endpoint privacy, and the rule that signaling never becomes an
application-data tunnel. The trusted components are the PostgreSQL-backed
`vibe-authority` service (in `production_authority` mode) and correctly paired
host/device endpoints. The network, reverse proxy, other clients, STUN/TURN
operators, and this service for content confidentiality are not trusted. In
`local_development` mode the authority is replaced by in-process issuance, which
is explicitly not trusted for production.

The service learns random session IDs, coarse timing, SDP, ICE candidates, and
the connecting IP at the TCP layer. It never needs pairing QR secrets, private
identity keys, derived application keys, plaintext control/input, encoded media,
or frame metadata. Vibe Screen application E2EE and signed transcript checks are
mandatory even when signaling authentication succeeds.

## Threats and mitigations

| Threat | Mitigation in v0.1 | Remaining control |
| --- | --- | --- |
| Session guessing/token theft | At least 128-bit session IDs, 256-bit random or HMAC-derived role bearers, TTL, no-store responses, no secret logging | TLS, secret manager, authenticated token delivery |
| Role swap/offer overwrite | Role comes from a session-scoped bearer binding; explicit offer/answer state machine | Endpoint transcript and DTLS fingerprint binding |
| Replay/conflicting retry | Request/message IDs, exact-body idempotency, conflict on mutation, monotonic event sequence | Clients persist retry IDs only for session TTL |
| Candidate/SDP flood | Body/SDP/candidate/count/message-rate/session/waiter caps | Edge IP/global DDoS and connection limits |
| Cross-session read | Every poll/write re-authenticates session-scoped token; wrong/unknown is uniform 404 | TLS prevents bearer interception |
| Signaling content leak | No payload logging or metric labels; TTL deletion from the configured store | Operator/database access control, backup retention, and crash/core-dump policy |
| Arbitrary data tunneling | Closed JSON schema permits only offer/answer/candidate/end records | Edge traffic anomaly alerts |
| Slow request/poll exhaustion | HTTP read/header/write deadlines and per-role waiter cap | Reverse-proxy global concurrency limits |
| Stale state after restart | `memory` mode loses routing on restart; `postgres` mode persists short-lived routing rows and idempotency until TTL | Clients still establish a fresh rendezvous/session epoch after invalidation or expiry |
| Active session invalidation | Authority marks the admission revoked; signaling clears events, wakes polls, and tombstones the request ID until original expiry | Product authority persists device revocation and also terminates product/TURN access |
| Compromised signaling | Cannot decrypt application E2EE or authenticate peer transcript | Endpoint identity pinning; rotate role credentials |
| Authority failure or compromise | In `production_authority` mode dependency/protocol failures return `502`, policy rejects stay denied, no local token fallback occurs, and `/readyz` reports unavailable | Deploy authority with HA PostgreSQL, TLS, and PITR; monitor authority latency/error rate |
| Signaling-to-authority token theft | Attacker could create or revoke signaling admissions at the authority | Keep the authority token distinct from the issuer token; rotate it from a secret manager; restrict authority network access to signaling |

## Explicit residual risks

- A stolen valid role bearer can act until the trusted authority invalidates
  that known session or its short TTL expires. In `production_authority` mode
  device revocation at the authority immediately rejects both role tokens on
  their next request, but an active PeerConnection or TURN allocation is not
  actively disconnected.
- `memory` mode is single-instance and process-local. PostgreSQL durable routing
  is implemented for `production_authority`, and session creation is rate-limited
  with shared per-device/action PostgreSQL rows for instances using the same
  database. Horizontal multi-replica throughput, load-balancer behavior, and
  multi-region consistency remain unproved.
- The global issuer token authenticates only the trusted backend, not a human or
  endpoint. It must never ship in host/mobile clients. The signaling-to-authority
  token is independent and must also never ship to clients.
- In `production_authority` mode every message publish and poll performs a
  remote authority authorization, and creates are serialized by a global
  PostgreSQL advisory lock. This is a fail-closed correctness choice, not a
  high-throughput design; multi-instance throughput is not claimed.
- The monotonic numeric poll cursor is not a capability. A bearer holder can skip
  its own events by advancing it, but cannot access another role/session.
- v0.1 supports one offer/answer negotiation per rendezvous. ICE restart uses a
  fresh session to avoid mixing candidate generations.
- The authority's per-device `session_epoch` floor and the Mac pairing-scoped
  epoch operate in different scopes; their interaction is not yet unified.
- Signaling and authority require synchronized clocks (NTP). Expiry checks must
  not be relaxed to compensate for clock skew.
- Go's standard JSON decoder rejects unknown fields and trailing values but does
  not reject duplicate object keys. Clients and the authority must emit canonical
  unique keys; a future protocol version should add duplicate-key rejection
  before accepting untrusted public issuance.
- Process memory and crash dumps can contain live SDP, ICE candidates,
  request/session identifiers, and local-mode role tokens until session TTL
  cleanup. PostgreSQL routing rows are removed by TTL cleanup, while
  session-create token bucket rows are removed after two minutes of idle time
  based on `refilled_at`. WAL, snapshots, and backups may retain those values
  until their separate encrypted retention and purge controls run. Disable core
  dumps, restrict process/database debugging, encrypt backups, and keep
  retention short.

## Security test gates

Automated tests must cover wrong/cross-session/cross-role tokens, answer before
offer, conflicting and exact retries, candidate count/size/body limits, unknown
fields, repeated queries, concurrent waiter rejection, TTL wakeup, authority-only
invalidation, request-ID tombstones, poll wakeup, process log redaction, and
graceful cancellation. The authority-backed process test additionally covers
account/device registration, authority-delegated session creation, offer/poll
exchange, device revocation rejecting both role tokens, and log redaction of all
service/role tokens and SDP. Before an Internet release, additionally
test TLS policy, proxy parsing, device revocation propagation to active
PeerConnections/TURN allocations, ICE generations, TURN credential TTL binding,
multi-instance storage behavior, PostgreSQL backup/deletion handling, fuzzed
JSON/SDP/candidates, process/core-dump handling, and an independent
peer-transcript security review.
