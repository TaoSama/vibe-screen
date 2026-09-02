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
multi-instance operation is not proved, no authoritative production usage
exporter or live active-allocation disconnect executor is deployed, macOS
Authority-backed session-profile request and refresh are wired only as a local
control-plane path, Android UI import/bootstrap/handoff remain unproved, the
bundled coturn deployment does not run a production-scheduled usage exporter/reconciliation
worker or concrete data-plane disconnect executor, and no integrated
implementation has run on a public host in this environment. The repository now
contains a current-base local operator slice for those boundaries, but it
operates on reviewed structured JSON and a local active-allocation state file; it
is not a live coturn allocation teardown proof.

The current `services/relay/` binary is an experimental credential/usage control
service, not the complete production shape below. A trusted control-plane bearer
requests session-scoped credentials and usage comes from a trusted collector.
Local development can store quota/revocation state in one local file; the
production-authority path uses PostgreSQL for shared quota, revocation, active
session, and event-idempotency state while keeping request-rate state
process-local. Admin revocation or Authority revocation blocks future credentials
and rejects every subsequent non-duplicate usage event for that device/session,
but does not by itself terminate an active TURN allocation or prove a signed
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
admission now delegates to the authority before TURN credential issuance when
`services/relay/` is run in its Authority-backed production mode; relay usage
events also delegate to Authority before non-duplicate ledger mutation; and
Authority owns coturn usage/reconciliation APIs. Relay writes a strict
allocation registry that maps Authority allocation IDs to TURN REST usernames so
operator tooling can identify exact coturn sessions. The repository also includes
`scripts/phase3/coturn_reconcile.py`, a bounded helper that submits a trusted
structured coturn allocation snapshot to Authority, can call an external exporter
command whose stdout is that same strict JSON, retries failures when explicitly
configured, and invokes an external disconnect executor for unauthorized,
conflicting, or revoked active source allocations. The current-base local product
slice adds `scripts/phase3/coturn_allocation_exporter.py` for structured collector
adaptation, `scripts/phase3/coturn_reconciliation_loop.py` for bounded durable
missing-allocation tracking, `scripts/phase3/coturn_disconnect_executor.py` for
idempotent local active-allocation state removal plus non-secret audit records,
and `scripts/phase3/coturn_cli_control.py` for coturn CLI `ps` export and
`cs <session-id>` disconnect when the registry mapping is exact. This still is
not a production-proven coturn machine exporter,
production scheduler, or concrete data-plane disconnect implementation. Therefore
this does not remove the public-launch prohibition below. See the service README
for the migration procedure, API contract, and remaining infrastructure gates.
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
backup automation, Android UI profile import/bootstrap/handoff, production coturn
exporter/disconnect wiring, or
active disconnection after revocation.

Production enforcement cannot be closed from any single service log. The release
owner must run scripts/phase3/production_e2e_enforcement.py against a reviewed
manifest that names owners for release decision, Authority, signaling, coturn
data plane, and evidence review. That manifest must bind all three policy views
to the same authority source, TURN realm, TTL, allocation, byte-budget, and clock
skew limits; a mismatch is a failed deployment, not a blocked environment. The
same manifest must prove public route and remote TURN observations with real
ScreenCaptureKit capture, Android MediaCodec decode, Authority admission,
signaling authorization, coturn allocation plus disconnect, and a 120-minute
mixed-route production soak. The current repository record is blocked in
evidence/2026-08-25-production-e2e-enforcement-current-base-blocked/ because those deployed
dependencies are unavailable here.

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
An Authority profile issued through the admin API can be used by signaling after
successful role authorization, but that is still an operator-mediated control
flow rather than automatic product issuance.

The current-base owner for automatic session-authority issuance is
`scripts/phase3/session_authority_readiness.py`. Treat it as the release-blocking
contract for this gap: local Authority, Signaling, Relay, and Mac signer tests
are not enough unless a sanitized report proves that the product flow itself
registered the account/device, called Authority profile issuance, kept the
unsigned lease inside product-controlled transport, had the Mac sign the exact
Authority epoch, and had Android import the signed lease through product UI. Any
operator profile copy, unsigned lease file handoff, or manual Android import
keeps the result blocked. A static TURN password in product flow is a failure,
not a readiness blocker.

## Service inventory

Maintain separate ownership and deployment records for:

- authenticated signaling/rendezvous API;
- STUN/TURN pools by region;
- ephemeral TURN credential issuer;
- quota/rate-limit store and abuse controls;
- metrics, alerting, audit events, and redacted diagnostic ingestion.

Each release records image/binary digest, source revision, dependency manifest,
configuration schema version, rollout region, and rollback version.

## Public Internet soak evidence

Before a Phase 3 result is described as public Internet, create
`phase3-internet-soak-manifest.json` from the production deployment under test:

```bash
make phase3-internet-soak-manifest PHASE3_INTERNET_SOAK_DIR=/tmp/vibe-screen-phase3-internet \
  PHASE3_INTERNET_TURN_URIS="turns:relay.prod.your-domain.com:5349?transport=tcp" \
  PHASE3_INTERNET_SIGNALING_ORIGIN=https://signaling.prod.your-domain.com \
  PHASE3_INTERNET_RELAY_ORIGIN=https://relay.prod.your-domain.com \
  PHASE3_INTERNET_AUTHORITY_SOURCE_ID=turn-prod-1 \
  PHASE3_INTERNET_REMOTE_PEER=peer.prod.your-domain.com \
  PHASE3_INTERNET_TLS_CERTIFICATE_SHA256=... \
  PHASE3_INTERNET_DEPLOYMENT_READINESS=authority-readyz,relay-readyz,coturn-tls \
  PHASE3_INTERNET_PLANNED_HANDOFFS=wifi-to-cellular \
  PHASE3_INTERNET_HOST_BUILD="signed Host build and SHA" \
  PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256=...
```

After the run, place privacy-reviewed summaries beside the manifest using these
filenames: `remote-turn-verifier.json`, `media-continuity.json`,
`network-handoff.json`, `revocation-propagation.json`, and
`soak-exact-window-report.json`. Then run:

```bash
make phase3-internet-soak-gate PHASE3_INTERNET_SOAK_DIR=/tmp/vibe-screen-phase3-internet
```

The gate passes only when those inputs jointly prove public remote TURN packet
exchange, real encoded screen decode on Android, fresh-session network handoff,
revocation propagation to active coturn allocation disconnect and packet denial,
and a clean two-hour mixed direct/relay soak. If deployment config, TLS material,
runtime secret source, readiness endpoints, remote peer, or any report is
missing, archive the result only with `PHASE3_INTERNET_ALLOW_BLOCKED=1`; do not
substitute local Compose, forced local coturn, or synthetic peer evidence.

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
`pinned_host_id`, `pinned_device_id`, `lease_device_key_id`, `signaling_url`,
`signaling_session_id`, `session_epoch`, `host_identity_epoch`,
`device_identity_epoch`, `expires_at`, `transcript_context`,
`protocol_session_id`, `signaling_token`, `ice_servers`, and
`allow_insecure_for_testing`. Each ICE server contains exactly `urls`,
`username`, and `credential`; nullable values must be JSON `null`. The issuer
adds `lease_host_key_id` and the DER ECDSA `lease_signature` over the Android
canonical transcript. The issuer verifies local host and paired-device identity
bindings, reserves the exact Authority-supplied `session_epoch` in
pairing-scoped durable Keychain state, and rejects any value at or below the
local high-water mark before signing. The unsigned `expires_at` field is an
admission-boundary compatibility input: it must be present and bounded, but the
issuer rewrites it to the local bounded TTL before signing, so input JSON cannot
choose the accepted expiry.

This manual issuer is an operator bridge for unsigned Authority leases. The
macOS host now also has a local Authority-backed request and refresh path, but
neither path closes Android UI import/bootstrap/handoff, public Internet, or
real media transport gates.

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
3. Revoke relay credential issuance, inspect the relay allocation registry for
   matching `allocation_id` entries, then separately disconnect existing coturn
   allocations and reconcile any ledger entry whose final usage event is rejected.
   The local coturn CLI helper can assist an operator only when its registry and
   coturn `ps` output identify one exact session; retain the command transcript
   as deployment evidence.
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

For the current Nubia substitute path, use the same shared lease-aware
acceptance flow as the runner. The operator must atomically create and keep a
separate process holding `/tmp/vibe-screen-device-internet.lock`, then recheck
that the soak and Android locks are absent and that the Internet lease still
matches before every ADB subprocess. Use an explicit serial in every command:

```bash
test ! -e /tmp/vibe-screen-device-soak.lock
test ! -e /tmp/vibe-screen-device-android.lock
export ADB_ENDPOINT='<device-serial>'
export LEASE_OWNER='<opaque-owner-value>'
export VIBE_SCREEN_COMMIT="$(git rev-parse HEAD)"
python3 - <<'PY' &
import json, os, pathlib, time
path = pathlib.Path("/tmp/vibe-screen-device-internet.lock")
payload = json.dumps({
    "owner": os.environ["LEASE_OWNER"],
    "pid": os.getpid(),
    "task": "phase3-android-internet-acceptance",
    "commit": os.environ["VIBE_SCREEN_COMMIT"],
}, separators=(",", ":")).encode()
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, payload)
os.fsync(fd)
try:
    while True:
        time.sleep(60)
finally:
    os.close(fd)
    path.unlink(missing_ok=True)
PY
LEASE_PID=$!
export LEASE_PID
trap 'kill "$LEASE_PID"; wait "$LEASE_PID" 2>/dev/null || true; rm -f /tmp/vibe-screen-device-internet.lock' EXIT

check_android_internet_locks() {
  test ! -e /tmp/vibe-screen-device-soak.lock
  test ! -e /tmp/vibe-screen-device-android.lock
  python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path("/tmp/vibe-screen-device-internet.lock")
stat = path.stat()
assert stat.st_mode & 0o777 == 0o600
root = json.loads(path.read_text())
assert root["owner"] == os.environ["LEASE_OWNER"]
assert root["task"] == "phase3-android-internet-acceptance"
assert root["commit"] == os.environ["VIBE_SCREEN_COMMIT"]
assert root["pid"] == int(os.environ["LEASE_PID"])
os.kill(root["pid"], 0)
PY
}

adb_guarded() {
  check_android_internet_locks
  adb -s "$ADB_ENDPOINT" "$@"
  check_android_internet_locks
}

adb_guarded devices -l
adb_guarded shell getprop ro.product.manufacturer
adb_guarded shell getprop ro.product.model
adb_guarded shell getprop ro.product.device
adb_guarded shell getprop ro.build.version.release
adb_guarded shell getprop ro.build.version.sdk
```

The recorded identity for that path is `nubia P0110 / pacific / Android 16 /
SDK 36`. Do not relabel it as Xiaomi 13/fuxi evidence, and do not use a
synthetic-media interop run to claim ScreenCaptureKit-to-Android-MediaCodec,
public Internet, handoff, latency, or soak gates.

## Authority integration open items

The signaling `production_authority` mode is implemented and covered by a
two-process PostgreSQL test (account/device registration, authority-delegated
session creation, offer/poll exchange, device revocation rejecting both role
tokens, and log redaction). The following remain open and must not be treated as
shipped:

- macOS Authority-backed session-profile request allocation, invocation, and
  fresh-session refresh are wired for local/offline control-plane use. Android
  UI profile import, first lease bootstrap, device handoff, and public-network
  E2E remain open.
- Automatic account and device registration is not wired; accounts and devices
  must be registered through the authority admin API before a profile or
  signaling admission can be created.
- Relay credential admission is wired to the authority; the structured exporter,
  bounded reconciliation loop, and local active-allocation disconnect executor are
  locally tested as a current-base operator slice. A real coturn/provider exporter,
  production scheduler, and concrete live allocation termination remain unproved.
- Active PeerConnection and TURN allocations are not actively disconnected on
  authority revocation; signaling invalidation only stops new rendezvous access.
- The authority per-device `session_epoch` floor and the Mac pairing-scoped
  durable high-water mark are both enforced, but product-side reconciliation and
  recovery for mismatched floors remain open.
- PostgreSQL durable signaling routing is implemented, including cross-instance
  message delivery, connection-scoped long-poll waiter leases that can be
  reclaimed after a failed instance loses its database backend, shared
  per-device/action session-create rate rows for production-authority creates
  after Authority admission, and one shared `local_development` bucket for local
  creates. Create-rate rows are removed after two minutes of idle time based on
  `refilled_at`. Throughput under multiple replicas, production load-balancer
  behavior, and multi-region consistency remain unproved.
- Per-message remote authority authorization and the global PostgreSQL advisory-lock
  create serialization are fail-closed correctness choices, not a
  high-throughput design. Create transactions take that lock before opening a
  serializable transaction, and cleanup paths that delete session or create-rate
  rows use the same lock to avoid repeated serialization failures under
  concurrent creates.
- Signaling and authority require NTP clock synchronization. Authority startup
  and `/readyz` compare PostgreSQL `clock_timestamp()` with the application
  clock and fail closed when the configured conservative skew bound cannot be
  proven. This relative check does not prove external time correctness; expiry
  checks, session TTLs, and the skew limit must not be relaxed to hide a clock
  failure.
- The signaling `max_session_ttl_seconds` and authority
  `maximum_session_ttl_seconds` must be kept consistent.

## Public NAT/TURN readiness owner

`scripts/phase3/public_nat_turn_preflight.py` is the current-base owner for the
public NAT/TURN deployment readiness slice. It now requires two separate remote
records before returning pass: sanitized connectivity evidence, plus deployment
evidence using schema `dev.vibescreen.phase3-public-nat-turn-deployment/v1`. The
deployment evidence must prove public STUN, UDP/TCP TURN, TLS TURN, certificate
hostname validation, TLS 1.2 or newer, production quota enforcement, credential
rotation with old-credential rejection after TTL, allocation/auth-failure/relay
byte/quota monitoring, alert rules, and independent remote observers outside the
host network.

The verifier output hashes endpoint-like values and keeps raw endpoints,
credentials, device identifiers, and operator paths out of archived evidence.
When real public infrastructure or protected credentials are unavailable, archive
a blocked package rather than weakening the preflight or relying on local coturn
loopback. Local coturn, synthetic peers, self-reported JSON without an external
canary, or a deployment record without rotation and monitoring proof cannot
close the public NAT/TURN or Phase 3 Internet release gates.
