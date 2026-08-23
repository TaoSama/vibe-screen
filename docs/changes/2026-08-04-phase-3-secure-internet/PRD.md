# Phase 3: secure Internet access

Status: runnable development-preview slice; not production-ready
Owner: Vibe Screen core team  
Started: 2026-08-04

## Goal

Let an explicitly authorized device use a Mac display and send input across
untrusted networks without trusting the signaling or TURN relay with screen
content, input, or long-lived device credentials.

Phase 3 is complete only when a real WebRTC implementation, deployed signaling
and TURN services, application-layer end-to-end encryption, device lifecycle,
network recovery, adaptive media, operator controls, and Android device evidence
all agree. Protocol declarations, policy classes, fake engines, local unit tests,
or a successful APK build are necessary evidence but are not completion.

## Current status

The repository currently contains:

- versioned Protocol v1 messages for identity, pairing proofs, encrypted
  control/media packets, key rotation, revocation, and replay metadata;
- pinned macOS M150 and Android M144 WebRTC binary adapters plus transport-policy
  ports for separate control, media, audio-record, and bulk-record paths, ICE
  restart, bounded media/audio queues, relay-byte accounting, and adaptive video;
- a standalone Go security package implementing ECDSA-P256 identity, ECDH-P256/HKDF
  session derivation, AES-GCM secure channels, replay windows, rotation, and
  revocation, with unit tests;
- a standalone Go relay control service for short-lived coturn credentials,
  persisted usage quotas, metrics, and cost estimates;
- a runnable Go signaling service with local memory and production PostgreSQL
  routing backends plus authenticated Swift/Kotlin HTTP signaling clients;
- macOS/Android platform security lifecycle code and deterministic policy/network
  simulation;
- macOS and Android product-session composition, manual pairing/profile import,
  protected Protocol v1 control/media DataChannels, and direct/forced-TURN UI;
- a pinned coturn Compose data-plane definition. The recorded local
  forced-relay verification used the host-installed coturn 4.16.0 binary; it
  does not prove execution of the pinned container image.

Those entries describe current code capabilities. The real-device evidence is
separately bound to one historical record: on 2026-08-05, source commit
`597518f948075e396352bc353afcec01a30303f3` completed a controlled local direct
and forced-coturn product-session pass on `Nubia P0110 / pacific / Android 16`
using the macOS M150 and Android M144 adapters, application AES-256-GCM,
Protocol v1 control, authenticated touch records, and synthetic media. That
record proves only the dated source/device combination and must not be
extrapolated to this working tree or later commits. It is not public-Internet,
real ScreenCaptureKit content, visible Mac input, carrier/CGNAT, automatic
handoff, latency, or stability evidence. The services remain single-node
development implementations. Authority now exposes an admin/operator session
profile issuance primitive for already registered devices, but Mac/Android
automatic invocation of that path, cross-service revocation propagation,
authoritative coturn byte accounting, and a production deployment remain open.
Trusted-LAN remains separate from Phase 3 Internet
transport: current macOS/Android peers protect the token-admitted TCP session
with per-session application records, while explicit legacy fallback remains
plaintext and is not Phase 3 security.

As of 2026-08-06, main commit
`4c2e908fe31af4c187684991301e163371444eab` had passed Phase 0
[run 31084214883](https://github.com/TaoSama/vibe-screen/actions/runs/31084214883),
iOS engineering
[run 31084214830](https://github.com/TaoSama/vibe-screen/actions/runs/31084214830),
and HarmonyOS portable
[run 31084214856](https://github.com/TaoSama/vibe-screen/actions/runs/31084214856).
Those CI results are offline evidence for that dated commit only and do not
close any public-Internet or platform real-device gate.

See [TECH.md](TECH.md#implementation-status-and-gates) for the precise boundary.

## Target user outcomes (planned)

1. A user pairs once with a short-lived QR offer and can recognize both endpoints
   before granting screen and input access.
2. A remembered device reconnects over the Internet without rescanning while its
   authorization and keys remain valid.
3. Direct P2P is preferred. If NAT traversal fails, TURN relay is automatic and
   visible without weakening application-layer encryption.
4. Wi-Fi/cellular/VPN changes recover automatically; stale media and input from
   the prior session epoch are rejected.
5. Video quality degrades quickly under congestion and recovers conservatively,
   without building a stale-frame queue.
6. A user can revoke a device and rotate keys. Revocation takes effect for new
   connections and terminates an active session within the documented bound.
7. Errors identify whether the problem is pairing, authorization, signaling,
   NAT traversal, relay quota, network quality, codec, or permissions.

## Planned completion scope

### Connectivity

- replaceable WebRTC engine adapters on host and Android;
- authenticated signaling carrying only offers, answers, candidates, and opaque
  routing identifiers;
- ICE with configured STUN and short-lived TURN credentials;
- direct-first routing with TURN fallback and an explicit relay-only diagnostic
  mode;
- reliable ordered control channel and independent unordered, zero-retransmit
  media channel;
- ICE restart and session resumption after validated network changes.

### Security

- per-install ECDSA-P256 identity and ECDH-P256 ephemeral key agreement;
- one-time, expiring pairing offers bound to transcript and endpoint identities;
- application-layer AES-256-GCM for both control and encoded media;
- distinct keys and sequence spaces per direction, channel, session epoch, and
  key epoch;
- nonce uniqueness, replay window, transcript downgrade protection, rotation,
  revocation, and secure local key storage;
- relay and signaling services never receive application traffic keys.

Algorithm identifiers describe the intended Protocol v1 suite; shipping them is
conditional on implementation review and interoperability tests. No custom
cryptographic primitive may be introduced.

### Resilience and adaptation

- bounded exponential recovery and ICE restart on path changes;
- latest-frame media backpressure and keyframe recovery;
- bitrate, resolution, and FPS profiles driven by WebRTC statistics with
  hysteresis and user-visible floors;
- explicit `config_epoch` acknowledgment before switching decode parameters;
- reconnect telemetry that distinguishes direct, relay, signaling, and local
  permission failures.

### Relay operations

- short-lived TURN credentials, per-device/session quotas, allocation limits,
  rate limits, regional routing, and abuse response;
- metrics for allocations, relay bytes, authentication failures, denial reasons,
  connection route, ICE restart, and spend estimates;
- logs exclude SDP secrets, TURN passwords, IP addresses by default, pairing
  credentials, public-key fingerprints beyond a safe prefix, input, and media.

## Non-goals

- making a public, unauthenticated Mac endpoint discoverable;
- allowing the signaling or relay service to decrypt screen or input data;
- replacing WebRTC congestion control with a project-specific transport;
- audio, clipboard, file transfer, multiple clients, managed-device enrollment,
  or account recovery;
- treating WebRTC DTLS/SRTP alone as the product's relay-independent E2EE claim;
- silently routing trusted-LAN mode or explicit plaintext legacy fallback through
  the Internet.

## Target acceptance criteria

### Functional

- Android and macOS use a real, audited WebRTC adapter with no fake engine in the
  release composition root.
- A direct candidate succeeds when reachable; symmetric-NAT simulation falls
  back to authenticated TURN; relay loss triggers bounded recovery.
- Control remains reliable and ordered. Media remains independently bounded and
  stale frames never delay current input/control.
- Wi-Fi to cellular and cellular to Wi-Fi changes resume with a new session epoch
  and a decodable keyframe without user re-pairing.
- Adaptation changes bitrate, resolution, and FPS through acknowledged protocol
  configuration and avoids oscillation under a boundary trace.

### Security

- both peers authenticate the complete pairing/session transcript and reject an
  identity, algorithm, capability, or session downgrade;
- ciphertext or authenticated headers modified in transit fail closed;
- duplicate, too-old, wrong-channel, wrong-session, wrong-epoch, and wrong-key
  packets are rejected before application dispatch;
- rotation is monotonic, survives restart, allows only the documented overlap,
  and cannot be rolled back; revocation disconnects the active device and blocks
  reconnect on every route;
- long-lived private keys are non-exportable where platform facilities permit;
  logs, crash reports, evidence, and relay metrics contain no secrets or content;
- the [threat-model exit criteria](THREAT_MODEL.md#security-exit-criteria) pass
  independent review.

### Performance and operations

- healthy direct Internet paths target 80–150 ms glass-to-glass; all latency
  claims use an external camera, not cross-device clocks;
- recovery is measured for path change, transient loss, TURN failover, signaling
  reconnect, and process restart; target p95 is five seconds unless the test plan
  records and approves a stricter value;
- every TURN allocation is attributable to a pseudonymous account/device/session
  dimension, quota enforcement is tested, and spend alerts are actionable;
- a two-hour mixed direct/relay/network-change soak shows bounded queues, bounded
  memory, no nonce reuse, and no steadily increasing latency.

### Required device evidence

The target Xiaomi 13 (2211133C) at `$ADB_ENDPOINT` must be connected with ADB, identified,
installed, paired, streamed across a genuine Internet/TURN path, exercised for
touch and keyboard, disconnected/reconnected, switched between networks, and
soaked. Commands, device properties, APK/version hashes, host/client revision,
relay route evidence, structured logs, and timestamps must be archived using the
[TEST evidence template](TEST.md#android-internet-evidence-template).

## Release gate

Until every acceptance item is backed by evidence, documentation and UI must
describe Phase 3 as a development-preview Internet product slice, not a stable
secure-Internet release. The implemented application record layer may be named
precisely, but it must not be used to imply public-path, real-capture, handoff,
latency, or stability proof.
