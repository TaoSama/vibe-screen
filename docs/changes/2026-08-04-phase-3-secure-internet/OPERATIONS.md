# Phase 3 Internet operations

This runbook describes the required production shape. `services/signaling/` and
`services/relay/` are runnable experimental control-plane binaries with local
tests and container definitions. The pinned coturn data plane is bundled through
Compose. Authority now has a pinned non-root container, a persistent local
PostgreSQL profile, an external-database production-shaped profile, ordered
migration, readiness checks, and a bounded restart-persistence gate. The recorded
local REST-credential, Allocation, ChannelBind and forced
WebRTC relay integration used the host-installed coturn 4.16.0 binary; it does
not prove execution of the pinned container image. This is still not a
deployable production stack: signaling has PostgreSQL-backed durable routing but
multi-instance operation is not proved, no authoritative usage exporter is
bundled, automatic issuance is not wired to Authority, the current relay/coturn
deployment does not call Authority relay admission or coturn usage APIs, and no
integrated implementation has run on a public host in this environment.

The current `services/relay/` binary is an experimental credential/usage control
service, not the production shape below. A trusted control-plane bearer requests
session-scoped credentials, usage comes from a trusted collector, quota state is
stored in one local file, and request-rate state is process-local. Admin revocation
blocks future credentials and rejects every subsequent usage event for that
device, but does not terminate an active TURN allocation or prove a signed
device/host authorization. Credential issuance and revoke are serialized so no
new credential is returned after a completed revoke. The binary itself remains
separate from the coturn data-plane process in the Compose deployment.

`services/authority/` supplies the runnable shared-PostgreSQL admission and
account/device-revocation slice intended to replace process-local authority
state. It also exposes cumulative coturn usage ingestion and
snapshot reconciliation. The signaling service now supports a
`production_authority` mode that delegates session creation, per-request
role-token authorization, and session invalidation to the authority, with
PostgreSQL-backed routing state in production. Dependency or malformed-response
failures return `502` without falling back to locally minted tokens; signaling
storage failures return `503`; authority policy rejections remain denials.
Relay credential
admission now delegates to the authority before TURN credential issuance, and
Authority owns coturn usage/reconciliation APIs. The repository
still has no production-proven coturn machine exporter, reconciliation loop, or
active-allocation disconnect executor. Therefore this does not remove the
public-launch prohibition below. See the service README for the migration
procedure, API contract, and remaining infrastructure gates.
Do not expose it to the public Internet until those boundaries and the
remaining production gates below are resolved.

## Authority deployment gates

Use `deploy/phase3/docker-compose.authority.yml` only for a reproducible local or
CI stack. It owns a named PostgreSQL volume, uses a private-network
`sslmode=disable` URL and one database role, then orders PostgreSQL health, a
one-shot migration, and Authority startup. Those choices are deliberately not a
production database design.

The production-shaped `docker-compose.authority.production.yml` contains no
PostgreSQL service. It requires a digest-only Authority image, externally managed
secret files, an ignored reviewed config, and separate migration/runtime database
URLs. Before routing a production caller, operators must verify all of the
following outside Compose:

- PostgreSQL certificate and hostname verification (`sslmode=verify-full`),
  enforced by the production profile before migration/runtime startup, plus
  encrypted storage, HA, PITR, documented RPO/RTO, and a recent restore exercise;
- a short-lived DDL migration role and a least-privilege runtime DML role, with a
  backup and checksum review before each migration;
- monitored host/database NTP offset. Time uncertainty never permits wider TTLs,
  acceptance of expired credentials, or a local session-epoch fallback;
- private authenticated TLS 1.2+ transport to Authority, network policy,
  loopback-only host publishing, log redaction/rotation, resource limits, and a
  shutdown grace period longer than the application deadline;
- `/readyz` and a synthetic admission/authorization canary. `/healthz` is only
  process liveness and remains healthy during a database outage while readiness
  and storage-backed requests fail closed.

Authority's PostgreSQL floor is the durable decision point for accepted device
session epochs. Do not introduce a process-local fallback when it is unavailable.
An application rollback may roll back image/config but must not roll back the
logical revocation or epoch ledger. A database recovery remains fail-closed until
the recovery point and ledger invariants are verified.

The supplied production profile runs one Authority process. It does not prove
multi-process Authority operation, public ingress, NTP monitoring, database
backup automation, automatic account/session issuance, relay/coturn wiring, or
active disconnection after revocation.

The signaling service accepts one offer/answer per session and exposes an
issuer-only idempotent invalidation operation. In `production_authority` mode
session creation, per-request role authorization, and invalidation are delegated
to the PostgreSQL authority, while signaling stores SDP/ICE routing state in its
own PostgreSQL schema until TTL cleanup. A signaling process restart can replay
the existing `request_id` from this store, but it still does not create a second
offer generation after invalidation or expiry. Current product transports request
a wholly fresh session instead of attempting a second offer. Operators must not
enable unattended network-handoff recovery until authority issuance can deliver
both endpoints a new session ID, role tokens, optional TURN credential,
PeerConnection, and larger common epoch and a Mac/Android test proves it.

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

### Issue a host-signed Android session lease

The Mac host provides an explicit stdin/stdout issuer that reuses the existing
paired P-256 identity in the login Keychain. It never creates a signing identity,
and fails if `pinned_host_id` does not name an already provisioned host key:

```bash
cd baseline/MacHost
umask 077
swift build -c release
".build/release/Vibe Screen" --issue-phase3-internet-lease \
  < /protected/path/unsigned-lease.json \
  > /protected/path/android-lease.json
```

The unsigned JSON is strict: it contains exactly `version`, `pairing_id`,
`pinned_host_id`, `signaling_url`, `signaling_session_id`, `session_epoch`,
`identity_epoch`, `transcript_context`, `protocol_session_id`,
`signaling_token`, `ice_servers`, and `allow_insecure_for_testing`. Each ICE
server contains exactly `urls`, `username`, and `credential`; nullable values
must be JSON `null`. The issuer adds `lease_host_key_id` and the DER ECDSA
`lease_signature` over the Android canonical transcript. `session_epoch` in the
unsigned input is an untrusted compatibility field: the issuer ignores its value,
atomically reserves the next epoch from pairing-scoped durable Keychain state,
replaces the field, and only then signs. Input JSON cannot select or reset it.

Both input and output contain the signaling token and possibly TURN credentials.
Keep them in an owner-only temporary directory, never pass them as command-line
arguments, and delete them immediately after importing the output through the
Android Internet UI. The command writes only the signed JSON to stdout and never
logs lease contents. Verify the cross-language canonical fixture with:

```bash
".build/release/Vibe Screen" --phase3-internet-lease-self-test
```

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

1. Persist and distribute a monotonic revocation at the authority (device
   revocation epoch).
2. Invalidate each matching signaling session through the issuer endpoint,
   which forwards the revocation to the authority in `production_authority`
   mode, and verify both role tokens and any long poll fail immediately.
3. Revoke relay credential issuance, then separately disconnect existing coturn
   allocations and reconcile any ledger entry whose final usage event is rejected.
4. Terminate the endpoint transport; signaling invalidation alone does not stop a
   direct PeerConnection or an active TURN allocation.
5. Confirm direct and relay reconnect rejection before and after service restart.
6. Preserve redacted audit events; do not collect screen/input content.
7. Require explicit re-pairing with a new device identity after remediation.

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
- Android Xiaomi 13 (2211133C) Internet evidence is attached;
- rollback has been exercised and does not roll back revocation/key epochs;
- feature flags can disable new sessions by version/region while preserving clear
  user errors.

## Shared Android device lease

The caller must explicitly supply the lease-controlled local acceptance
endpoint as `$ADB_ENDPOINT`; the repository has no endpoint default. It uses three coordinated lock
paths. `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` must both be absent. The Internet task must
atomically create and hold `/tmp/vibe-screen-device-internet.lock` with a private
owner token and `0600` permissions before any ADB command, app install/stop/launch,
device query, media-port probe, or Mac host stream start. The acceptance script
requires an exact byte-for-byte match between that lock and `--lease-token`, and
rechecks all locks before every ADB subprocess. Extra `--device-lock` values only
add checks and cannot replace these mandatory paths.

On completion or failure, stop the app, Mac host, signaling and coturn processes;
remove only the ADB reverse/forward mappings created by this run; then delete the
Internet lock. Never include its owner token in evidence. Absence of the
coordination locks and ownership of the Internet lock authorize a run; neither is
evidence that any device test passed.

## Authority integration open items

The signaling `production_authority` mode is implemented and covered by a
two-process PostgreSQL test (account/device registration, authority-delegated
session creation, offer/poll exchange, device revocation rejecting both role
tokens, and log redaction). The following remain open and must not be treated as
shipped:

- Mac and Android automatic profile/account/session issuance is not wired to the
  authority.
- Automatic account and device registration is not wired.
- Relay credential admission is wired to the authority; coturn exporter
  reconciliation and active-allocation disconnect are not production proven.
- Active PeerConnection and TURN allocations are not actively disconnected on
  authority revocation; signaling invalidation only stops new rendezvous access.
- The authority per-device `session_epoch` floor and the Mac pairing-scoped
  epoch operate in different scopes and are not yet unified.
- PostgreSQL durable signaling routing is implemented, but multi-instance
  operation, global create-rate enforcement, and throughput under multiple
  replicas remain unproved.
- Per-message remote authority authorization and the global PostgreSQL advisory-lock
  create serialization are fail-closed correctness choices, not a
  high-throughput design.
- Signaling and authority require NTP clock synchronization. Authority startup
  and `/readyz` compare PostgreSQL `clock_timestamp()` with the application
  clock and fail closed when the configured conservative skew bound cannot be
  proven. This relative check does not prove external time correctness; expiry
  checks, session TTLs, and the skew limit must not be relaxed to hide a clock
  failure.
- The signaling `max_session_ttl_seconds` and authority
  `maximum_session_ttl_seconds` must be kept consistent.
