# Security threat model

## Assets and trust boundary

Protected assets are screen pixels, input events, long-lived device
authorization, identity private keys, session traffic keys, and relay access.
The trusted endpoints are the paired Mac host and client device. Signaling,
STUN, TURN, local routers, ISPs, and relay operators are untrusted and may
observe, reorder, duplicate, delay, modify, or drop packets.

The relay receives routing metadata and ciphertext only. Media metadata and
encoded pixels are inside `EncryptedMediaPacket.ciphertext`; the relay never
terminates Vibe Screen content encryption or receives endpoint traffic keys.

## Attacker capabilities

The design considers:

- active network interception and signaling substitution;
- theft or replay of a previously observed record, session ID, or revocation;
- cross-channel and cross-direction reflection;
- concurrent attempts to consume a QR pairing offer;
- a malicious or compromised relay attempting to inspect or alter content;
- a previously authorized device connecting after rotation or revocation;
- malformed keys, oversized messages, unknown enum values, and state-machine
  abuse at the protocol boundary.

## Security properties

- The 256-bit QR bootstrap secret authenticates a pairing transcript without
  crossing the network. ECDSA proves possession of both endpoint identity keys;
  ephemeral ECDH provides fresh session secrecy.
- HKDF binds both identities, both ephemeral keys, the challenge, offer ID, and
  bootstrap secret. Host/device and control/media keys are distinct.
- AES-GCM authenticates ciphertext and the complete routing/security header.
  A deterministic 96-bit nonce is unique within each direction/channel key:
  32-bit channel plus 64-bit strictly increasing sequence.
- Control records require a sequence strictly greater than the last accepted
  sequence, preventing authenticated delivery reordering from changing action
  order. Media alone uses a 64-record receive window for limited network
  reordering. Authentication succeeds before either sequence state is
  committed, preventing forged packets from burning sequence IDs.
- Identity rotation is signed by both the current and next key over a
  transcript that includes the authority/host peer identity. Used rotation
  nonces are retained in memory and in the validated persistent snapshot.
  Signed revocation uses one authority-global monotonically increasing sequence
  across all devices and removes authorization permanently; key loss requires
  explicit fresh pairing rather than unsigned recovery.

## Operational controls outside this module

- Private keys must be non-exportable where platform keystores allow it.
- QR offers must expire quickly, be redacted from diagnostics, and be removed
  from display after success. The host must persist offer consumption before
  acknowledging success if pairing spans process boundaries.
- The complete authority keyring snapshot must be durably and atomically
  committed before acknowledging rotation or revocation. Running multiple
  writers requires a storage transaction or single-writer service around the
  in-process keyring; independently restored processes do not coordinate.
- TURN credentials must be short-lived, scoped to device/session/audience, rate
  limited, quota constrained, and invalidated on revocation. Relay metrics must
  exclude plaintext, credentials, keys, and stable identifiers where possible.
- WebRTC signaling must bind the negotiated DTLS certificate fingerprint and
  capability/SDP transcript to endpoint identity before media is accepted.
- Implementations must cap proto frame, field, repeated-item, and ciphertext
  sizes before allocation and close abusive connections without expensive
  retries.

## Known limitations and unproved properties

- This module is a reference core, not a FIPS-validated cryptographic module.
- Process memory can expose Go private keys and session keys; production clients
  need native keystore-backed signers and explicit key lifetime management.
- The current core does not implement WebRTC signaling/DTLS fingerprint
  binding, TURN credential issuance, process-persistent offer transactions,
  traffic-key update ACK/grace windows, or active-session termination. Those
  integrations must preserve the transcript and record invariants above.
- P-256, HKDF, and AES-GCM interoperate conceptually with macOS and Android API
  26 system providers, but cross-language Swift/Kotlin vectors and Android
  hardware-backed key tests are still required.
- Endpoint compromise, screen capture by an authorized endpoint, traffic
  analysis, denial of service, and a compromised host authorization database
  are outside the confidentiality guarantee.
