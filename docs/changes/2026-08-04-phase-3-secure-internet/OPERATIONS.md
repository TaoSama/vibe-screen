# Phase 3 Internet operations

This runbook describes the required production shape. `services/signaling/` and
`services/relay/` are runnable experimental control-plane binaries with local
tests and container definitions. The pinned coturn data plane is bundled through
Compose and has passed local REST-credential, Allocation, ChannelBind and forced
WebRTC relay integration. This is still not a deployable production stack:
signaling is single-instance/in-memory, no authoritative usage exporter is
bundled, and the pinned container has not run on a public host in this environment.

The current `services/relay/` binary is an experimental credential/usage control
service, not the production shape below. A trusted control-plane bearer requests
session-scoped credentials, usage comes from a trusted collector, quota state is
stored in one local file, and request-rate state is process-local. Admin revocation
blocks future credentials but does not terminate an active TURN allocation or
prove a signed device/host authorization. The binary itself remains separate from
the coturn data-plane process in the Compose deployment.
Do not expose it to the public Internet until those boundaries and the
container/readiness findings in [TECH.md](TECH.md#open-implementation-findings)
are resolved.

The signaling service accepts one offer/answer per session. Current client ICE
restart attempts to renegotiate in the existing session and will receive a state
conflict. Operators must not enable unattended network-handoff recovery until the
generation/new-session contract is implemented consistently.

## Service inventory

Maintain separate ownership and deployment records for:

- authenticated signaling/rendezvous API;
- STUN/TURN pools by region;
- ephemeral TURN credential issuer;
- quota/rate-limit store and abuse controls;
- metrics, alerting, audit events, and redacted diagnostic ingestion.

Each release records image/binary digest, source revision, dependency manifest,
configuration schema version, rollout region, and rollback version.

## Configuration contract

Production clients consume signed configuration containing environment, signaling
origin, ordered ICE URLs, certificate/pin policy where applicable, credential TTL,
supported protocol range, feature flags, and telemetry sampling. Secrets are
injected at runtime from a secret manager and are never committed, included in QR
payloads beyond one-time pairing material, or emitted in diagnostics.

TURN credentials are short-lived and scoped to an authenticated session/device.
Static shared TURN passwords in clients are prohibited. `turns:` is preferred for
credential and metadata protection; application E2EE remains mandatory regardless
of TURN transport.

## Required dashboards

### User experience

- signaling success and time-to-authorize;
- ICE success and time-to-connect by direct/relay, candidate pair, region, client
  version, and network class;
- reconnect/ICE restart rate and recovery latency;
- RTT/loss/jitter, target/rendered FPS, bitrate, profile changes, queue drops, and
  keyframe recovery;
- error codes and user-visible failure stage.

### Relay and cost

- active allocations, allocation success/denial, auth failures, permission/channel
  counts, bytes in/out, bandwidth, and session duration;
- relay percentage and cross-region percentage;
- bytes and estimated cost by region/build/pseudonymous tenant;
- quota/rate-limit decisions and top anomaly cohorts, without exposing content or
  unnecessary personal data.

### Security

- expired/reused pairing offers, transcript failures, replay rejects, old epochs,
  rotation failures, revoked-device attempts, credential issuance anomalies, and
  administrative changes.

## Initial alert policy

Thresholds require baseline tuning, but launch must at minimum alert on:

- regional connection success or recovery latency regression;
- unexpected relay-rate or egress-cost growth;
- allocation/auth failure spikes;
- quota store/credential issuer unavailable or accepting expired credentials;
- replay/revoked-device/identity mismatch spikes;
- telemetry pipeline loss that makes security or spend controls blind.

Every alert links to a named owner, dashboard, first diagnostic queries, safe
mitigation, escalation path, and rollback/feature-disable control.

## Abuse and cost controls

- authenticate before issuing signaling or TURN authorization;
- limit pairing attempts, sessions, allocations, peers, bandwidth, bytes, and
  duration per account/device/IP risk bucket;
- enforce limits on the service and TURN server; client counters are not trusted;
- use short expiry and rotate credential-signing secrets with overlap;
- apply anomaly scoring and progressive throttling before account suspension;
- expose a user-visible relay budget/error rather than silently degrading into an
  endless reconnect loop;
- regularly reconcile TURN counters against provider/network billing.

## Incident procedures

### Suspected endpoint-key compromise

1. Persist and distribute a monotonic revocation.
2. Terminate matching signaling sessions, TURN credentials, and active transport.
3. Confirm direct and relay reconnect rejection.
4. Preserve redacted audit events; do not collect screen/input content.
5. Require explicit re-pairing with a new device identity after remediation.

### TURN credential leak or abuse

1. Disable/rotate the issuer secret and stop new allocations for the affected
   scope; avoid global outage when a narrower scope is known.
2. Expire active credentials, enforce emergency bandwidth/allocation caps, and
   inspect pseudonymous usage/region/version dimensions.
3. Verify that captured relay traffic remains application ciphertext.
4. Reconcile cost, document affected metadata, and rotate service credentials.

### Signaling compromise

Disable new pairing/session establishment, keep authenticated active P2P sessions
only if the threat analysis permits, rotate service credentials, and verify peer
identity/E2EE downgrade defenses. A signaling compromise alone must not reveal
screen or input content.

### Regional failure

Drain the region, stop issuing its TURN URLs, prefer a healthy direct or nearest
relay route, watch cross-region latency/cost, and restore gradually. Do not relax
identity or E2EE checks to recover availability.

## Rotation procedures

- TURN issuer secrets: rotate with two-key verification overlap shorter than the
  credential maximum TTL; then remove the old key and test rejection.
- service TLS/signing keys: follow provider runbook, validate clients with clock
  skew and rollback scenarios.
- device identity keys: use the authenticated protocol rotation transaction and
  durable monotonic epoch; never replace silently from signaling metadata.
- application traffic keys: rotate by time/bytes and after session recovery using
  derived session keys; record only epoch/reason, never key material.

## Data retention and diagnostics

Define and test deletion for signaling payloads, ICE/connection metadata, security
audit events, aggregates, and diagnostic bundles. Use the minimum duration needed
for security, reliability, and billing. Raw candidate/IP records and diagnostic
bundles have the shortest retention and restricted access. Document jurisdiction,
processor, and user deletion behavior before public service launch.

## Release and rollback checklist

- protocol compatibility and security vectors pass on old/new supported clients;
- direct and forced-relay canaries pass in every enabled region;
- quotas, expiry, alerts, dashboards, and deletion jobs are verified;
- packet capture and artifact secret scan pass;
- Android Xiaomi 12 Internet evidence is attached;
- rollback has been exercised and does not roll back revocation/key epochs;
- feature flags can disable new sessions by version/region while preserving clear
  user errors.
