# Phase 3 threat model

## Assets

- screen frames, input events, display/window state, and session metadata;
- device and host signing keys, traffic keys, pairing credentials, TURN
  credentials, revocation state, and replay counters;
- user authorization decisions and endpoint identity;
- service availability, relay budget, telemetry integrity, and user privacy.

## Trust boundaries

The Mac host and authorized client application are trusted only after local
platform integrity and peer authentication checks. The Internet, DNS, local
network, signaling service, STUN service, TURN service, observability stack, and
other local processes are potentially hostile. Apple/Android platform key stores
are trusted within their documented guarantees; a rooted device or fully
compromised endpoint is outside the confidentiality guarantee.

The relay is an availability and metadata processor, never a content-security
endpoint. WebRTC hop encryption is defense in depth; application AEAD is the E2EE
boundary.

## Adversaries

- passive and active on-path attackers;
- malicious or compromised signaling/relay operators;
- Internet scanners and credential-stuffing/billing-abuse actors;
- a previously authorized but now revoked device;
- a local process attempting to connect to an exposed listener;
- an attacker with a copied QR, replayed packet, old key, crash dump, log bundle,
  or restored application backup;
- a peer sending malformed, oversized, reordered, or resource-exhausting data.

## Threats and required controls

| Threat | Required prevention/detection | Required verification |
| --- | --- | --- |
| Pairing MITM / QR theft | short expiry, single redemption, random challenge, signed canonical transcript, both identities displayed | mutate every transcript field; redeem twice; use after expiry |
| Algorithm/capability downgrade | signed protocol range, algorithms, capabilities, and roles; Internet mode never falls back to plaintext | strip/reorder offers and required capabilities |
| Signaling impersonation | authenticated service plus independent peer identity proof | substitute SDP/candidates/peer ID |
| Signaling token retained after revoke | issuer-only idempotent invalidation destroys both role tokens, queued payloads, and active long polls | invalidate during offer/answer/candidate polling; retry invalidation; reuse both role tokens |
| Relay content inspection | application AEAD over control and full media header+payload; traffic keys never sent to service | TURN capture contains no known plaintext or codec/frame header |
| Packet tampering | header as AEAD AAD, fail closed before dispatch | flip every header/ciphertext class |
| Replay/reordering | per-channel/direction/key-epoch sliding window and monotonic control delivery | duplicate, too-old, reordered, cross-channel, cross-session vectors |
| Nonce reuse after crash | durable monotonic epoch/counter or fresh key before reuse | crash at persistence boundaries and compare all observed nonces |
| Old-session injection | authenticated `session_epoch`; stale media/input dropped | reconnect and inject prior control/media/input |
| Rotation rollback | current-key authorization, monotonic persisted epoch, bounded overlap | reordered/duplicate/old-key rotations and restart |
| Revoked-device reconnect | durable signed tombstone, active disconnect, signaling/TURN credential invalidation | direct and relay reconnect before/after service restart |
| Credential extraction | Keychain/Keystore protection, backup exclusion, redacted logs/evidence | backup/restore, log/crash/evidence scan |
| Memory/backlog exhaustion | strict envelope/frame/candidate/channel/allocation caps; latest-frame media queue | oversized/flood/fuzz and sustained slow consumer |
| Relay cost abuse | short-lived scoped credentials, auth rate limits, quotas, concurrent allocation and byte caps, alerts | quota/rate/concurrency tests and billing drill |
| ICE/SDP privacy leak | minimal retention, access control, redaction, no routine raw candidate logging | telemetry/log inventory and deletion test |
| Network-switch hijack | re-authenticated resume, new session epoch/keys, peer identity pin | adversarial candidate during ICE restart |
| Malicious input | explicit device authorization, focus/permission policy, rate limit, emergency disconnect | flood, revoked input, background/locked-host cases |
| Signaling-generation confusion | bind SDP/candidates to a monotonic negotiation generation or replace the entire short-lived signaling session | second offer, old ufrag candidate, restart race, cross-generation injection |
| Configuration-secret disclosure | credential-bearing configuration types permanently redact string/debug output; logs and errors use structured safe fields | seed TURN/signaling secrets and scan logcat, crash, exception, and diagnostic output |
| WebRTC binary supply-chain compromise | exact tag/revision/artifact digest, signature/checksum verification, full upstream license/SBOM inventory, release audit gate | mutate artifact/metadata, clean dependency resolve, final APK/XCFramework inventory |
| Native lifecycle race | single-owner executor/state machine and callback generation; dispose cannot race send/SDP/ICE/cipher | concurrent start/close/send/restart/callback stress under sanitizers/race tooling |

## Denial-of-service posture

The system does not promise availability against a network-scale attack. It does
promise bounded local memory/CPU, bounded relay allocation/spend, finite recovery,
and actionable denial telemetry. Authentication and cheap structural validation
occur before expensive cryptography, decoding, or display work where safe.
Unauthenticated error responses are small and rate-limited to avoid amplification.

The current signaling invalidation endpoint is an authority operation, not a
device-signed revocation feed. The relay control plane persistently rejects new
credentials and all later usage events for a revoked device, but coturn allocation
termination is a separate data-plane action. Those distinctions are security
boundaries: a local tombstone, signaling invalidation, relay credential denial,
and allocation disconnect must not be reported as one atomic operation until a
cross-service test proves it.

## Privacy posture

Operational services necessarily observe coarse connection metadata. Default
telemetry is pseudonymous and excludes content, raw candidate/IP data, credentials,
and stable cross-install advertising identifiers. Diagnostic collection is
explicit, time-bounded, locally previewable, and redacted before upload.

## Residual risks

- compromised endpoints can capture plaintext before encryption or after decode;
- traffic analysis can reveal timing, volume, likely interaction, and route even
  when content is encrypted;
- private `CGVirtualDisplay` use has platform compatibility risk unrelated to
  Internet cryptography;
- TURN compromise can deny service, consume quota, or expose metadata;
- the current signaling issuer and relay client bearers are service authority
  credentials rather than proof that a paired device possesses its signing key;
- signaling invalidation cannot itself stop a direct PeerConnection, and relay
  revocation cannot itself terminate an already-issued coturn allocation;
- WebRTC community binaries are not official Google mobile distributions and
  carry a large transitive native-code/license supply chain;
- macOS M150 and Android M144 are different WebRTC generations until real-device
  interoperability is proved;
- a user can authorize the wrong device if identity confirmation UX is unclear;
- cryptographic schema design is not evidence of a correct implementation;
- the shared Swift/Kotlin bound-context known-answer value does not prove the full
  pairing transcript or wire bytes interoperate; a real cross-language pairing
  fixture/run remains required.

## Security exit criteria

Release requires:

1. independent review of protocol transcript, KDF, nonce construction, replay
   window, rotation/revocation transactions, and platform key storage;
2. interoperable known-answer vectors in Swift and Kotlin;
3. fuzzing and negative tests for parsers, signaling, encrypted packets, and
   state machines under sanitizers where available;
4. packet capture proving no plaintext content/credentials across direct and TURN
   paths;
5. Android device tests for pairing, stream/input, network change, replay,
   rotation, revocation, reinstall/backup behavior, and soak;
6. relay quota, rate limit, credential expiry, deletion, alert, and incident drills;
7. no unresolved critical/high security finding and documented ownership/date for
   accepted lower-severity risk.

None of these criteria is currently claimed complete by this document.
