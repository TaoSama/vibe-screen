# Phase 3 technical design

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
5. Exchange signaling messages over authenticated HTTPS/WebSocket. Authenticate
   the remote identity independently of the signaling channel.
6. Gather ICE candidates, prefer direct connectivity, and use short-lived TURN
   credentials only when needed.
7. Open two negotiated channels:
   - `vibescreen.control.v1`: ordered, reliable;
   - `vibescreen.media.v1`: unordered, `maxRetransmits = 0`.
8. Authenticate the session transcript, establish a new `session_epoch`, then
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
single-instance in-memory service; restart invalidates all sessions.

The current WebRTC adapters send a second offer for ICE restart, while the service
rejects a second offer. Production recovery therefore requires one explicit
versioned design: either negotiation generations in one session, or atomic issue
of a fresh signaling session/token/PeerConnection and larger session epoch. Until
that is implemented and tested across both clients, network-handoff recovery is
not complete.

## TURN and ICE

- STUN discovers candidates; it is not an authentication or confidentiality
  boundary.
- TURN uses TLS where supported and time-limited REST-style credentials issued
  only after session authorization.
- Direct is preferred, but the selected route is telemetry, not a security mode:
  both direct and relay carry identical application ciphertext.
- Relay-only exists for diagnostics and restrictive networks, never to bypass
  device authorization.
- Allocation lifetime, peer permissions, bandwidth, concurrent allocations, and
  bytes per session are bounded server-side. Client byte counters are advisory.

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

The current policy code covers bounded media and fail-closed application record
encryption. Fresh-session identity/key renewal across ICE recovery and product
stream/session composition remain pending.

## Adaptive media

The WebRTC adapter reports monotonic samples for available outgoing bitrate,
loss, RTT, jitter, route, encode/decode queue, and frame drops. Policy chooses a
bounded profile and uses hysteresis: downgrade quickly, upgrade slowly. The host
proposes a `VideoConfig` with a new `config_epoch`; the client acknowledges before
the host changes codec geometry. A rejection selects a lower compatible profile.

Transport policy may request a profile but does not mutate VideoToolbox or
MediaCodec directly. User caps, decoder capabilities, thermal signals, and
relay-cost caps constrain the policy.

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
| Security core | `packages/security/` | Go implementation, restart snapshots, attack tests and vectors exist; Swift/Kotlin platform lifecycle code exists, but cross-language product-session interoperability remains unproved |
| macOS Internet transport | `baseline/MacHost/Sources/Phase3/InternetTransport/`, stasel WebRTC `150.0.0` | Real M150 adapter, REST signaling, Keychain session factory and Protocol v1 record layer pass direct and forced local TURN E2E; capture/encoder/input/UI and Android interop remain gates |
| Android Internet transport | `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/`, `io.github.webrtc-sdk:android:144.7559.09` | Real M144 PeerConnection/DataChannel adapter, strict REST client and an AndroidKeyStore-backed factory that atomically loads paired secrets into the AES-GCM record layer build; instrumentation APK builds but cannot run during device freeze; main UI wiring pending |
| Existing LAN security | `WirelessAuth.swift`, `AuthHandshake.kt`, `StreamingServer.swift`, `StreamClient.kt` | 32-byte bearer token over plaintext TCP; trusted LAN only, not E2EE |
| Relay control/data plane | `services/relay/`, `deploy/phase3/` | Short-term credential control plane and pinned coturn Compose data plane exist; real local credential/allocation/ChannelBind and forced-relay libwebrtc E2E pass. Public deployment, trusted usage collector and multi-node state remain gates |
| Signaling | `services/signaling/` plus Swift/Kotlin clients | Runnable single-instance service and real-process tests exist; one-offer state conflicts with adapter ICE restart, no durable/multi-instance authority or revocation feed |
| Identity/rotation/revocation/replay | Protocol, Go core, platform security directories | Implementations and unit/self-tests exist; product composition, cross-language vectors, atomic platform crash consistency, and active-session revocation remain gates |
| Adaptive video | policy types and unit tests | Policy foundation only; encoder/config acknowledgment integration pending |
| Network simulation | `scripts/phase3/network_profile.py`, `tests/phase3/` | Deterministic contract simulation only; explicitly not OS-level impairment, ICE, or TURN evidence |
| Android Internet evidence | none at documentation creation time | Must complete [TEST.md](TEST.md) device matrix |

### Open implementation findings

These are release blockers, not accepted architecture:

- Android's real engine still has open lifecycle/concurrency, pending-media order,
  inbound-size, route-reporting, stats/adaptation, and signaling retry/strict-DTO
  findings. Credentials are redacted by current `toString` tests, but all logging
  and crash paths still require device validation.
- macOS M150 local loopback, direct signaling and forced local coturn E2E pass,
  including application AES-GCM. XCTest has not executed because full
  Xcode/XCTest is unavailable. M150-to-Android-M144 interoperability, app
  integration, public TURN, and signed packaging remain gates.
- Both adapters' ICE restart behavior is incompatible with the current signaling
  one-offer state machine; do not claim network-handoff recovery.
- The Go secure-channel nonce is derived from channel and sequence. Product
  integration must persist or replace session/key epoch before reuse after crash;
  the standalone package alone cannot guarantee lifecycle uniqueness.
- Relay session requests remain authenticated by a trusted control-plane bearer,
  not a device possession proof. Usage/quota enforcement relies on a trusted TURN
  collector, and the rate limiter/store are process-local. Usage ingestion,
  metrics scraping, credential issuance, and administration now use distinct
  tokens; the ledger atomically replaces and directory-syncs its state file.
  Admin revocation blocks
  new credentials but cannot terminate an already-issued TURN allocation.
  Authoritative coturn accounting, cryptographic signaling binding, multi-instance
  storage, container-engine execution of the pinned image, and public reachability
  remain pending.
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
