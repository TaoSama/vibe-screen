# Phase 3 technical design

Except for paragraphs that explicitly describe current implementation status
and the [Implementation status and gates](#implementation-status-and-gates)
section, the architecture sections below describe the target Phase 3 design.
That section consolidates verified subsets and remaining release gates.

## Design constraints

- Protocol and product session semantics remain independent of a concrete
  WebRTC SDK, signaling provider, or TURN operator.
- Control and media have different delivery semantics and independent queues.
- TURN relays encrypted application bytes and cannot terminate Vibe Screen E2EE.
- Reconnection increments the session epoch; key rotation increments key epoch.
  Neither counter substitutes for the other.
- Production builds fail closed when the real WebRTC or cryptographic adapter is
  absent. TCP and fake engines are not Internet fallbacks.

## Dependency direction

```text
product UI -> session orchestration -> protocol + identity/key lifecycle
                                  -> InternetTransport port -> WebRTC adapter
                                  -> adaptive-media policy -> encoder/decoder ports
                                  -> structured telemetry

signaling client -> opaque session routing + SDP/ICE exchange
TURN             -> encrypted datagrams only
```

Protocol, identity, session, adaptive policy, and telemetry may not import an SDK
or platform network API. Platform adapters translate between stable ports and
WebRTC/network/key-store implementations.

## Connection lifecycle

1. Load the local device identity from Keychain/Android Keystore. If absent,
   create an ECDSA-P256 signing key and stable random device identifier.
2. Pair locally or through an already authenticated rendezvous. The QR offer is
   single-use, expires quickly, and carries a random challenge, host identity,
   ephemeral key, and supported algorithms.
3. Both peers sign a canonical transcript containing protocol range,
   capabilities, identities, ephemeral keys, offer identifier, challenge, and
   roles. Unknown required algorithms or downgrade attempts abort pairing.
4. Derive a root secret from ECDH-P256 and transcript using HKDF-SHA-256. Derive
   direction/channel/session-specific traffic keys; never use the raw shared
   secret as an AEAD key.
5. Before Android stores or activates a session lease, verify a signature from
   the paired host identity over every routing, epoch, transcript, token, ICE,
   TURN-credential, and test-policy field. Verify before advancing any durable
   high-water mark.
6. Exchange signaling messages over authenticated HTTPS/WebSocket. Authenticate
   the remote identity independently of the signaling channel.
7. Gather ICE candidates, prefer direct connectivity, and use short-lived TURN
   credentials only when needed.
8. Open two negotiated channels:
   - `vibescreen.control.v1`: ordered, reliable;
   - `vibescreen.media.v1`: unordered, `maxRetransmits = 0`.
9. Authenticate the session transcript, establish a new `session_epoch`, then
   send encrypted Protocol v1 traffic. Start media only after configuration is
   accepted and a keyframe is available.

## Application E2EE

WebRTC encrypts each hop, but Vibe Screen additionally encrypts application
packets so a TURN service or future media intermediary still cannot inspect
content. `SecurePacketHeader` is canonicalized and supplied as AEAD additional
authenticated data. For media, `MediaPacketHeader` is inside ciphertext so the
relay cannot observe frame timing, codec, or keyframe metadata.

Key derivation must domain-separate at least:

```text
protocol version | session_id | session_epoch | key_epoch |
sender role | receiver identity | control-or-media
```

Each direction/channel uses a separate sequence counter and key. Nonces must be
deterministically derived from a unique session/key/channel prefix plus sequence,
or randomly generated with a proven collision bound and persistent protection.
The current schema carries nonce bytes but does not implement or prove a nonce
construction.

### Replay protection

- Reject a packet before decrypt/dispatch if identity, session, epoch, key, or
  channel does not match the active context.
- After successful authentication, maintain a fixed-size sliding window per
  direction/channel/key epoch. Reject duplicate and too-old sequences.
- Persist the next local key/session epoch before first use so a crash cannot
  reuse a nonce/key pair. If persistence is uncertain, rotate to a fresh key.
- Control delivery to the application is strictly monotonic. Media may arrive
  out of order inside the replay window but is discarded when stale or from an
  older `session_epoch`, `config_epoch`, or frame generation.

## Key lifecycle

### Rotation

Rotation is authorized by the active signing key over the new identity, new
monotonic key epoch, nonce, activation time, protocol version, and peer identity.
The peer records the accepted epoch transactionally before acknowledging it.
A short, explicit overlap may accept the prior receive key for in-flight packets;
new sends use only the new key. Rollback and reuse of a rotation nonce fail.

Rotate after a documented time/byte threshold, on explicit user request, after
recovery from suspected compromise, and before any sequence space can wrap.

### Revocation

Revocation is monotonic and signed by the paired authority. It identifies device,
key, sequence, timestamp, reason, and nonce. Host policy must atomically persist
the tombstone, terminate matching active sessions, invalidate signaling/relay
credentials, and reject reconnect. “Forget display name” is not revocation.

## Signaling boundary

The signaling service may know account/routing identifiers, coarse timestamps,
source IP, SDP, and ICE candidates. It must not receive private identity keys,
derived traffic keys, one-time credentials after redemption, plaintext control,
input, frame metadata, or media. Signaling authorization is rate-limited and
scoped to one session. Candidates and SDP have strict size/count limits and are
deleted according to the operations retention policy.

`services/signaling/` now implements a short-lived authenticated REST/long-poll
rendezvous for one offer, one answer, and bounded ICE events. Swift and Android
clients interoperate with that contract in local tests. It is intentionally a
single-instance in-memory service; restart invalidates all sessions. The issuer
can also invalidate a session explicitly with an idempotent authenticated
`DELETE`: role tokens, queued signaling payloads, and long polls become unusable
immediately, while a request-ID tombstone remains until the original expiry.

Signaling now has an explicit `production_authority` mode. Session creation,
each role-token authorization, and invalidation are delegated to the
PostgreSQL-backed authority, while SDP/ICE routing remains process-local.
Authority failure, malformed response, or a session-ID collision fails closed
without local token fallback or state overwrite. A real two-process PostgreSQL
test covers account/device registration, admission, offer/poll, device
revocation rejecting both roles, bounded shutdown, and secret-log scanning. A
signaling restart cannot rebuild lost routing from an authority replay: the old
request returns `409`, and the owner must issue a fresh request with a larger
epoch. This is a signaling admission boundary, not automatic product issuance.

The service still rejects a second offer. The product transport therefore does
not attempt to reuse the old rendezvous after a network handoff: it suspends
application traffic and asks its owner for a fresh signaling session, role token,
TURN credential where needed, PeerConnection, and larger authority-agreed session
epoch. The macOS UI currently fails closed and asks the operator to supply that
fresh profile; automatic authority issuance and macOS/Android device proof of the
complete handoff remain release gates.

## TURN and ICE

- STUN discovers candidates; it is not an authentication or confidentiality
  boundary.
- TURN uses TLS where supported and time-limited REST-style credentials issued
  only after session authorization.
- Direct is preferred, but the selected route is telemetry, not a security mode:
  both direct and relay carry identical application ciphertext.
- Relay-only exists for diagnostics and restrictive networks, never to bypass
  device authorization.
- Coturn applies `user-quota` to a stable device principal after stripping the
  REST expiry, so session or expiry churn cannot reset the device allocation
  counter. Allocation lifetime, peer permissions, bandwidth, and concurrent
  allocations are bounded in the data plane.
- The current `/v1/usage` byte/session ledger is non-authoritative telemetry;
  it is not a real-time spend or admission-control boundary until a trusted
  coturn collector is deployed.

## Backpressure and recovery

Control has a strict message-size and total-backlog cap. Exceeding it fails the
session rather than silently dropping state-changing input or authorization
messages. Media holds at most the frame being sent and the newest replacement.
Dropping an inter-frame dependency requests a keyframe.

On a validated network fingerprint change or WebRTC disconnection:

1. suspend application sends while retaining only bounded control state;
2. request ICE restart with exponential backoff, jitter, a restart cooldown, and
   a finite attempt/deadline budget;
3. authenticate the resumed peer and allocate a larger `session_epoch`;
4. reset replay windows and media generation under newly derived session keys;
5. request a keyframe and resume only after configuration acknowledgment.

The macOS product composition now sends VideoToolbox output through a Protocol v1
media header into the protected media DataChannel and dispatches Protocol v1 touch,
video-configuration, heartbeat, disconnect, and keyframe control on the protected
reliable channel. Android has the matching Protocol v1 product-session composition
and consumes an authority-agreed epoch. Both sides reject an epoch at or below the
durable high-water mark before traffic keys are used. Network change
requests a replacement product session rather than a second offer in the old
rendezvous. The local lease issuer allocates the next pairing-scoped epoch from
durable Keychain state and never signs a caller-selected epoch. Packet seal and
open hold the peer-scoped durable epoch lock through nonce reservation or replay
check, AEAD, and replay commit, so an N+1 reservation cannot interleave after an
N check. Pairing cleanup markers remain durable until identity authorization,
reauthorization validation, and public metadata commit all succeed; failed
business commits retain restart-retryable secret and metadata cleanup. The prior
curated Android/macOS record remains withdrawn because its source and raw files
were unavailable. A fresh clean-commit run now records real Android UI and
Android M144/macOS M150 product-session interoperability through direct and
forced local coturn with Protocol v1 application AEAD. Its media source is
synthetic; automatic authority issuance, real screen capture, rotation,
disconnect/handoff, and old-record injection across a real handoff remain
unproved.

## Adaptive media

Adaptive video profiles apply only to the WebRTC Internet transport. The USB
and trusted-LAN transports continue to use manual client-driven presets
(bitrate/quality/frame-rate) and do not run the adaptive policy.

The WebRTC adapter reports monotonic samples for available outgoing bitrate,
loss, and RTT. Route changes use a separate transport callback; jitter,
encode/decode queue depth, and frame drops are not yet inputs to the adaptive
policy. The host `AdaptiveMediaPolicy` selects a bounded profile and uses
hysteresis: downgrade quickly (two consecutive poor samples) and upgrade slowly
(four consecutive good samples on macOS; five on Android), with neutral samples
resetting the counters so boundary jitter does not oscillate. On the host,
non-finite loss/RTT, a zero
bitrate estimate, and a missing RTT signal are treated as conservative
(constrained or good) rather than promoting quality. The Android
`AdaptiveVideoPolicy` mirrors the same fast-drop/slow-rise shape on the client
transport side, but it treats a missing zero RTT as healthy and does not apply
the host's non-finite or out-of-range loss guards, so those host edge-case
guarantees do not extend to Android.

The host applies an adaptive profile through the Protocol v1 video
configuration transaction rather than mutating VideoToolbox directly:

1. `InternetProductSession.beginAdaptiveProfileRequest` builds an
   `InternetAdaptiveVideoPlan` from the user baseline and the selected profile,
   clamping width, height, frame rate, and bitrate to the user-configured
   baseline upper bound.
2. The host applies the proposed configuration to the live encoder/capture
   first, then the session sends a `VideoConfig` with a bumped `config_epoch`.
   All outbound media stays gated until the client acknowledges.
3. The client validates that `config_epoch` strictly increases, rejects
   concurrent video-configuration transactions, and either accepts (updating
   its decoder configuration and frame assembler) or rejects with a reason.
4. On `VideoConfigResult` acceptance the host commits the new configuration,
   requests a keyframe, and resumes streaming. On rejection the host attempts
   to roll back to the last acknowledged configuration; a host-apply, ACK, or
   host-rollback timeout fails the session closed, and a failed rollback
   application also fails the session closed.

The user-configured baseline constrains the current policy. Decoder capability,
thermal, and relay-cost caps remain planned inputs and are not wired yet. The
production host composition wires the
`onAdaptiveProfileRequested` callback that applies the selected profile to the
live encoder/capture, but this path is verified only through offline build and
unit/self-tests, not against real capture output.

## Telemetry and privacy

Required dimensions are pseudonymous device/session IDs, build/version, protocol
version, direct/relay route, candidate type, region, recovery reason, adaptation
profile, error code, and quota decision. Metrics include RTT/loss/jitter,
available/target bitrate, FPS, queue depth, drops, ICE restarts, time-to-connect,
relay bytes, allocation count, and estimated cost.

Never log credentials, private/public keys in full, AEAD nonce+ciphertext pairs,
SDP, ICE candidate addresses, screen/input content, QR payloads, or raw IP unless
a user explicitly captures a redacted diagnostic bundle.

## Protocol compatibility

The current implementation extends the existing `vibescreen.protocol.v1` package
additively. Existing field numbers are retained; unsupported peers advertise no
Phase 3 capabilities and must be rejected for Internet mode rather than downgraded
to plaintext. Security-critical semantics are capabilities, not inferred from
field presence.

Wire compatibility is not sufficient evidence of security compatibility. Before
release, an independent review must confirm that no pre-existing v1 field has been
reinterpreted and that presence, size limits, canonical transcript bytes, required
algorithms, identity proof, and session resumption all fail closed. If that cannot
be proved without changing existing semantics, Internet mode moves to a new
`vibescreen.protocol.v2` package and must never downgrade to v1.

Before release, generated Swift/Kotlin types and canonical signing/AEAD encodings
must share golden fixtures for every message, unknown-field behavior, supported
algorithm set, and rejection path. Any incompatible canonicalization or security
semantic change requires a new protocol package/version.

## Implementation status and gates

| Area | Repository evidence | Status / release gate |
| --- | --- | --- |
| Security contract | `contracts/proto/vibescreen/protocol/v1/security.proto`, pairing/session/envelope additions | P-256/HKDF/AES-GCM schema exists; generated/canonical cross-language crypto interoperability and security-semantic review remain gates |
| Pairing and identity | `baseline/MacHost/Sources/Phase3/Security/InternetPairing*`, Android `security/InternetPairing*` | Swift/Kotlin implement the same strict pairing URL/request/acceptance shape, stable platform signing identities, ephemeral P-256 ECDH, signed canonical transcript, one-time/expiry checks, and protected pairing-secret storage. Durable transaction markers span secret writes, authorization/reauthorization and metadata commit; Android markers carry the owning pairing and recover under the global admission gate after authenticated-revocation recovery. A different verified/profile pairing cannot be replaced until its tombstone cleanup has removed binding, profile and old secrets. Upgrade cleanup is owner-aware: an old revocation deletes its pairing secret/identity, but treats a different current profile/binding as superseding state and durably retires those steps without cross-deletion. The local UI scans the offer QR and exchanges the request/acceptance as operator-copied strict JSON; automatic authenticated authority exchange and real cross-language pairing remain unproved |
| Security core | `packages/security/` and platform security directories | Go implementation, restart snapshots, attack tests and vectors exist. macOS state is peer-scoped, keeps a Keychain-backed revoked-identity epoch floor per stable device ID, and persists signed targeted tombstones plus restart-safe secret-cleanup progress. Both platforms reserve the common authority epoch before first use. Cross-language product-session and real platform crash-boundary evidence remain gates |
| macOS product session | `baseline/MacHost/Sources/Phase3/ProductSession/`, `AppDelegate.swift`, `SettingsWindow.swift`, stasel WebRTC `150.0.0` | Internet mode is separated from the legacy TCP server; capture/HEVC, Protocol v1 control/media, protected DataChannels, touch injection, direct/forced-TURN selection, Keychain credentials, and actionable state UI are wired. Synthetic local direct/relay product sessions and the narrower 2026-08-05 Nubia local synthetic-media interop record at commit `597518f948075e396352bc353afcec01a30303f3` exist; that historical result must not be extrapolated to the current worktree. Real ScreenCaptureKit device streaming, visible Mac input effects, public Internet, and handoff remain gates |
| Android product session | `MainActivity.kt`, `InternetSessionProfileStore.kt`, Android Internet packages, `io.github.webrtc-sdk:android:144.7559.09` | Internet UI scans the pairing offer, completes the copied request/acceptance flow, imports a strict host-signed short-lived lease, selects direct/forced TURN, drives Protocol v1 video/touch and decoder state, and exposes connect/disconnect/revoke/error/recovery. Lease verification precedes persistence/high-watermark changes; durable session/identity epochs reject stale ciphers and permit monotonic reauthorization after revoke. A fresh-session request or terminal failure invalidates the old transport owner, so late route/connected callbacks cannot restore touch or heartbeat. Credential, pairing and revocation cleanup retain restart-safe retry state. Tokens and pairing/session secrets are AndroidKeyStore-wrapped; sensitive dialogs disable screenshots/autofill, and release cleartext is disabled. The historical Nubia P0110 run is dated 2026-08-05 and bound only to commit `597518f948075e396352bc353afcec01a30303f3`; it covers local UI, direct/forced-coturn Android↔Mac product interop and application AEAD with synthetic Protocol v1 media. It is not current-worktree evidence and must not be extrapolated to later commits, real screen capture, public Internet, rotation, handoff, or soak |
| Existing LAN security | `WirelessAuth.swift`, `AuthHandshake.kt`, `StreamingServer.swift`, `StreamClient.kt`, LAN secure-record adapters | 32-byte bearer token admission followed by per-session AES-256-GCM application records for current macOS/Android peers. Explicit legacy fallback remains plaintext and must be separately reported; trusted LAN is still private-network only and not Internet E2EE |
| Relay control/data plane | `services/relay/`, `deploy/phase3/` | Short-term credential control plane and pinned coturn Compose data plane exist. REST usernames map all sessions/expiries for one device to one coturn allocation-quota principal, and production peer ACLs deny private, CGNAT, link-local, ULA and other internal ranges. New credentials and usage events are rejected after a persisted revoke, and issuance/revoke are serialized. Existing coturn allocations are not terminated by this control-plane action; public deployment, authoritative byte usage, active-allocation disconnect, and multi-node state remain gates |
| Signaling | `services/signaling/` plus Swift/Kotlin clients and `services/authority/` | Runnable single-instance in-memory routing, explicit local/production-authority modes, fail-closed authority admission and per-request authorization, device-revocation rejection, issuer-only invalidation, and real two-process PostgreSQL tests exist. It remains a one-offer router; Mac/Android automatic profile issuance, shared multi-instance routing, relay/coturn authority integration, and active transport disconnect remain gates |
| Rotation/revocation/replay | Protocol, Go core, platform security and product-session directories | Record replay and old-epoch rejection plus peer-scoped signed local revocation have unit/self-test coverage. Android and macOS retain durable retry state for local secret cleanup; macOS prevents one device's revoke history from overwriting another's epoch floor. End-to-end revocation propagation to the peer, signaling and active TURN allocation; rotation interoperability; and real reconnect injection remain gates |
| Adaptive video | `AdaptiveMediaPolicy` (macOS) / `AdaptiveVideoPolicy` (Android), `InternetProductSession` video-config transaction, `InternetAdaptiveVideoPlan` baseline clamp | Fast-drop/slow-rise hysteresis with jitter reset, even dimensions without upscaling, user-baseline upper bounds, latest-proposal-wins queuing, rotation serialization, stale owner/generation rejection, retry after local or peer rejection, host apply encoder/capture + media gate → `VideoConfig` ACK → keyframe/resume, reject rollback, and host-apply/ACK/rollback-timeout fail-closed are implemented and unit/self-tested. The production encoder/capture-application callback (`onAdaptiveProfileRequested`) is wired, but verified only through offline build and unit/self-tests, not real capture output. Real ScreenCaptureKit→Android decoder continuity, public Internet, real remote TURN, real network fluctuation, handoff, and soak remain unproved |
| Network simulation | `scripts/phase3/network_profile.py`, `tests/phase3/` | Deterministic contract simulation only; explicitly not OS-level impairment, ICE, or TURN evidence |
| Android Internet evidence | [TEST.md](TEST.md), `evidence/android-product-interop.json`, `evidence/2026-08-05-nubia-p0110-internet/` | Prior record remains withdrawn. The reachable-source record is a historical 2026-08-05 result for commit `597518f948075e396352bc353afcec01a30303f3` only. It covers local Android UI plus direct/forced-coturn synthetic product-session interoperability on Nubia P0110, is not evidence for the current worktree, and cannot be extrapolated beyond that dated source/device combination |

### Open implementation findings

These are release blockers, not accepted architecture:

- The strict Swift/Kotlin pairing formats and canonical inputs are implemented
  independently. A shared hard-coded known-answer value now pins the bound
  product-session context, but full pairing transcript/wire fixtures and a real QR
  request/acceptance round trip are still required. Do not infer full
  interoperability from same-language tests.
- macOS M150 loopback, direct signaling and forced local coturn transport E2E
  pass, including application AES-GCM. Those legacy adapter checks do not by
  themselves prove the new Protocol v1 product session. The separate product
  slice now proves Protocol v1 negotiation, touch/control and keyframe/delta media
  over both direct and forced local TURN with a synthetic peer. The new device
  run additionally proves Android UI and M150-to-Android-M144 interoperability,
  but still does not start ScreenCaptureKit or send real display content. The
  macOS XCTest suite for the 2026-08-06 main verification snapshot passed in
  GitHub Actions
  [run 31084214883](https://github.com/TaoSama/vibe-screen/actions/runs/31084214883)
  at main commit `4c2e908fe31af4c187684991301e163371444eab` (202/202 tests);
  that later CI result is not retroactive evidence for the device
  artifact's source commit.
- Recovery now fails closed into a fresh-session request instead of sending a
  second offer, but the local development UI requires manually supplied authority
  credentials and epoch. Do not claim automatic network-handoff recovery until a
  real Mac/Android run proves new signaling tokens, PeerConnection, record keys,
  epoch advance, and rejection of old records.
- Authority-backed signaling still performs remote authorization for every
  message publish and poll, and serializes creates through one global
  `authorityCreateMu` to prevent orphan admissions at local capacity. These are
  fail-closed correctness choices, not evidence of multi-instance throughput.
  Signaling and authority require NTP clock synchronization, and their maximum
  session TTL settings must agree; expiry validation is not relaxed for skew.
- The authority enforces one epoch floor per device ID, while the Mac lease
  issuer advances pairing-scoped durable epochs. Automatic product issuance
  must reconcile these scopes before it can replace the explicit manual profile
  flow.
- The macOS and Android local-development flows deliberately require copied
  pairing request/acceptance and imported session-authority profiles. This is an
  operable integration surface, not a production pairing/session issuer.
- Product revocation is not one cross-service transaction. macOS persists its
  peer-scoped signed tombstone and stops/deletes local session material; Android
  first commits a durable pending-revocation admission barrier before releasing
  the product session, then atomically promotes it to a tombstone. A failed
  promotion leaves the pending record for startup retry and blocks new leases;
  process reservations, durable pending/tombstone/cleanup state, lease import,
  and the final pairing secret/authorization/metadata commit share one global
  admission transaction. An already-open pairing dialog therefore cannot commit
  after revocation wins the transaction, including when the pending record names
  a different pairing.
  If even the pending commit fails, the process retains a quarantined session
  owner and disables new import/connect while quiescing UI-side resources. This
  last fail-stop boundary cannot survive an operating-system forced process kill
  when durable storage itself is unavailable. Android UI otherwise removes its
  local profile/secrets; signaling invalidation and relay
  revocation are separate authority APIs; an existing coturn allocation requires
  a separate data-plane disconnect. End-to-end signed propagation and reconnect
  rejection remain gates.
- The Go secure-channel nonce is derived from channel and sequence. Product
  integration must persist or replace session/key epoch before reuse after crash;
  the standalone package alone cannot guarantee lifecycle uniqueness.
- Relay session requests remain authenticated by a trusted control-plane bearer,
  not a device possession proof. Coturn now authoritatively enforces the stable
  per-device concurrent-allocation boundary, but byte/session usage remains a
  non-authoritative ledger without a trusted TURN collector, and the rate
  limiter/store are process-local. Usage ingestion,
  metrics scraping, credential issuance, and administration now use distinct
  tokens; the ledger atomically replaces and directory-syncs its state file.
  Admin revocation blocks new credentials and later usage events but cannot
  terminate an already-issued TURN allocation.
  Authoritative coturn accounting, cryptographic signaling binding, multi-instance
  storage, container-engine execution of the pinned image, and public reachability
  remain pending.
- The adaptive video policy and the Protocol v1 `VideoConfig`
  acknowledge/rollback transaction are implemented and unit-tested on both host
  and client, including even dimensions without upscaling, the user-baseline
  upper bound, fast-drop/slow-rise hysteresis, latest-proposal-wins queuing,
  rotation serialization, stale owner/generation rejection, retry after local
  or peer rejection, host encoder/capture application before `VideoConfig`,
  media gating until the client ACK, rejection rollback, and
  host-apply/ACK/rollback-timeout fail-closed. The production host composition wires the
  `onAdaptiveProfileRequested` callback that applies the selected profile to the
  live encoder/capture, but this path is verified only through offline build and
  unit/self-tests, not real capture output. USB and LAN transports are
  intentionally excluded and keep manual client-driven presets.
- Android release now bundles the fixed wrapper/WebRTC licenses, PATENTS,
  metadata, and publisher-supplied combined third-party notice bundle. Dependency
  audit is a release prerequisite; signed release/AAB alignment still requires
  configured signing and bundletool verification.

## Normative references

- [WebRTC 1.0](https://www.w3.org/TR/webrtc/)
- [RFC 8445: ICE](https://www.rfc-editor.org/rfc/rfc8445)
- [RFC 8489: STUN](https://www.rfc-editor.org/rfc/rfc8489)
- [RFC 8656: TURN](https://www.rfc-editor.org/rfc/rfc8656)
- [RFC 8827: WebRTC Security Architecture](https://www.rfc-editor.org/rfc/rfc8827)
- [RFC 5116: AEAD interface requirements](https://www.rfc-editor.org/rfc/rfc5116)

These standards inform interoperability and security requirements; they are not
third-party code dependencies.
