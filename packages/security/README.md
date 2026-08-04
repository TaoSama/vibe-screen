# Vibe Screen security core

This module is the platform-independent reference implementation for Protocol
v1 device identity, pairing, encrypted records, key rotation, revocation, and
replay protection. It intentionally has no dependency on WebRTC, TURN, UI, or
platform keystores.

## Cryptographic profile

- Identity signatures: ECDSA P-256 with SHA-256. Public keys use the 65-byte
  SEC 1 uncompressed form; signatures use ASN.1 DER.
- Ephemeral agreement: ECDH P-256. Identity keys are never used for ECDH.
- Key derivation: HKDF-SHA-256, salted by the 256-bit QR bootstrap secret.
- Records and issued credentials: AES-256-GCM.
- Four traffic keys are derived for host/device and control/media. Each tuple
  has an independent sequence space. The authenticated header binds protocol,
  session, epoch, key, channel, sender role, sequence, and deterministic nonce.
- Authenticated control records are accepted only with a sequence greater than
  every previously accepted record. Media records use a bounded 64-record
  replay window so limited packet reordering cannot reorder control actions.
- Identity rotation signatures bind the authority/host identity, current
  device identity, next device identity, activation time, and nonce. Successful
  nonces are remembered per authority and cannot be reused after restart when
  the complete keyring snapshot is restored.

The QR bootstrap secret is local input to `NewDevicePairingSession`; it is not
sent in `PairingRequest`. The request carries an HMAC over the signed transcript
instead. A host pairing session atomically accepts at most one valid request.

## Integration requirements

- Store private identity keys in Keychain/Android Keystore. Never serialize
  `Identity` into protocol messages, logs, backups, or telemetry.
- Deliver the complete `PairingOffer`, including its bootstrap secret, only by
  the QR out-of-band path. Network signaling may expose the offer ID and public
  fields but not `one_time_credential`.
- For Internet transport, require all four security capabilities and the
  algorithms in `security.proto`; never downgrade to the legacy bearer token.
- Create distinct sender and receiver `SecureChannelState` values for each
  role/channel. Reconnect increments the session epoch and creates new keys.
- Persist `Keyring.Snapshot()` transactionally before acknowledging a rotation
  or revocation. Restore it with `NewKeyringFromState`; the snapshot includes
  active keys, final revocations, used rotation-nonce hashes, and the single
  authority-global revocation sequence. Revocation must also close active
  sessions and invalidate relay credentials.
- Apply protocol message size limits before allocating attacker-controlled
  fields. Reject unknown algorithms, zero epochs/sequences, invalid key sizes,
  and unsupported capabilities.

See [THREAT_MODEL.md](THREAT_MODEL.md) for the security boundary and known
limitations.

## Verification

```bash
go test ./...
go test -race ./...
go vet ./...
```

Tests cover successful pairing, expired/wrong/reused offers, concurrent offer
consumption, credential encryption, traffic-key separation, header/ciphertext
tampering, replay and reordering, old session epochs, two-party key rotation,
authority-bound rotation, in-memory and restored nonce reuse, signed global
revocation ordering, concurrent state races, and final revocation state.

## Provenance and dependencies

No source code was copied from any external project. Runtime code uses only the
Go standard library.

| Source | Immutable version | License | Use | Copied code |
| --- | --- | --- | --- | --- |
| Go standard library, `https://go.googlesource.com/go` | `go1.24.13` | BSD-3-Clause | `crypto/ecdsa`, `ecdh`, `hkdf`, `aes`, `cipher`, `hmac`, `sha256`, `rand` and synchronization primitives | No |
| SideScreen, `https://github.com/tranvuongquocdat/SideScreen` | `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | Existing project context was audited; this module does not derive from it | No |
| Telemachus, `https://github.com/aaditagrawal/telemachus` | `a5dd1298870846d749175812f936ceebfd8b6b69` | MIT | Existing project context was audited; this module does not derive from it | No |

Go's license is distributed with the Go toolchain. SideScreen and Telemachus
license/notice inventory remains under the repository `third_party/` tree; this
module adds no vendored dependency or copied copyright material.
