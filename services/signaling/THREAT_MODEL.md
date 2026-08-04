# Signaling threat model

## Assets and trust boundary

Protected assets are session role bearers, SDP/ICE rendezvous integrity and
availability, endpoint privacy, and the rule that signaling never becomes an
application-data tunnel. The trusted components are the session-authority
backend and correctly paired host/device endpoints. The network, reverse proxy,
other clients, STUN/TURN operators, and this service for content confidentiality
are not trusted.

The service learns random session IDs, coarse timing, SDP, ICE candidates, and
the connecting IP at the TCP layer. It never needs pairing QR secrets, private
identity keys, derived application keys, plaintext control/input, encoded media,
or frame metadata. Vibe Screen application E2EE and signed transcript checks are
mandatory even when signaling authentication succeeds.

## Threats and mitigations

| Threat | Mitigation in v0.1 | Remaining control |
| --- | --- | --- |
| Session guessing/token theft | 128-bit session IDs, 256-bit random role bearers, TTL, no-store responses, no secret logging | TLS, secret manager, authenticated token delivery |
| Role swap/offer overwrite | Role comes from server-held bearer binding; explicit offer/answer state machine | Endpoint transcript and DTLS fingerprint binding |
| Replay/conflicting retry | Request/message IDs, exact-body idempotency, conflict on mutation, monotonic event sequence | Clients persist retry IDs only for session TTL |
| Candidate/SDP flood | Body/SDP/candidate/count/message-rate/session/waiter caps | Edge IP/global DDoS and connection limits |
| Cross-session read | Every poll/write re-authenticates session-scoped token; wrong/unknown is uniform 404 | TLS prevents bearer interception |
| Signaling content leak | No payload logging or metric labels; memory-only TTL deletion | Operator access control and crash/core-dump policy |
| Arbitrary data tunneling | Closed JSON schema permits only offer/answer/candidate/end records | Edge traffic anomaly alerts |
| Slow request/poll exhaustion | HTTP read/header/write deadlines and per-role waiter cap | Reverse-proxy global concurrency limits |
| Stale state after restart | State is intentionally not persisted, so restart destroys all sessions | Clients establish a fresh rendezvous/session epoch |
| Compromised signaling | Cannot decrypt application E2EE or authenticate peer transcript | Endpoint identity pinning; rotate role credentials |

## Explicit residual risks

- A stolen valid role bearer can act as that role until the short session TTL;
  there is no v0.1 per-session revocation endpoint or account/device revocation
  feed. Kill the instance or wait for TTL, revoke the device in the authority,
  and block relay credentials during incident response.
- The service is single-instance and in-memory. Horizontal replicas do not share
  state, rate limits, or idempotency. Sticky routing does not make this durable.
- The global issuer token authenticates only the trusted backend, not a human or
  endpoint. It must never ship in host/mobile clients.
- The monotonic numeric poll cursor is not a capability. A bearer holder can skip
  its own events by advancing it, but cannot access another role/session.
- v0.1 supports one offer/answer negotiation per rendezvous. ICE restart uses a
  fresh session to avoid mixing candidate generations.
- Go's standard JSON decoder rejects unknown fields and trailing values but does
  not reject duplicate object keys. Clients and the authority must emit canonical
  unique keys; a future protocol version should add duplicate-key rejection
  before accepting untrusted public issuance.
- Process memory and crash dumps can contain live SDP, ICE candidates, and role
  tokens until TTL/collection. Disable core dumps and restrict process debugging.

## Security test gates

Automated tests must cover wrong/cross-session/cross-role tokens, answer before
offer, conflicting and exact retries, candidate count/size/body limits, unknown
fields, repeated queries, concurrent waiter rejection, TTL wakeup, process log
redaction, and graceful cancellation. Before an Internet release, additionally
test TLS policy, proxy parsing, device revocation propagation, ICE generations,
TURN credential TTL binding, multi-instance storage, fuzzed JSON/SDP/candidates,
process/core-dump handling, and an independent peer-transcript security review.
