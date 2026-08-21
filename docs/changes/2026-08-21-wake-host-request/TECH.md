# Wake Host Request security boundary

## Scope

This change tightens the Phase 5 wake-host request path without claiming real
sleep/wake hardware acceptance. It covers the Protocol v1 request shape, the
Mac Host authorization boundary, replay protection, and the Android client
request API. The Wake-on-LAN sender remains a transport helper that only emits a
standard magic packet after authorization has already succeeded.

## Design

WakeHostRequest keeps the existing additive Protocol v1 fields: request id,
target MAC address, optional SecureOn password, host id, device id, key id,
issued/expires timestamps, nonce, and signature. The session-scoped envelope
provides session_id and session_epoch; the Host folds those values into the
signed proof transcript rather than duplicating them in the payload.

The signed transcript domain is vibescreen/wake-host-request/v1. Its parts are
ordered as request id, target MAC, SecureOn password, host id, device id, key
id, issued time, expiry time, nonce, session id, and session epoch. The Host
verifies the signature with the pinned paired device identity public key from
the Phase 3 pairing binding. A request signed for one active session therefore
cannot be replayed into another session epoch.

PairingBoundWakeHostAuthorizer validates the request before any packet sender
runs:

- host_id must match the persisted paired host identity.
- device_id and key_id must match the persisted paired peer identity.
- nonce must be at least 16 bytes and unused for this device/key/session tuple.
- issued/expires timestamps must be present, currently valid, and bounded to a
  maximum five-minute proof lifetime with five minutes of accepted clock skew.
- the ECDSA P-256 signature must verify over the wake transcript.

Nonce storage is process-local and keyed by device id, key id, session id,
session epoch, and nonce. This is sufficient for the current session replay
boundary because a new Host process creates a new Protocol v1 session id/epoch.
Durable nonce storage would only be needed if future behavior allowed reusing a
session id/epoch across process restart.

The production AppDelegate only enables wake when existing Internet pairing
metadata, persisted host/peer identity bindings, a non-revoked pairing state,
and the local host identity are all readable and mutually consistent. Any
missing or inconsistent state returns DenyWakeHostAuthorizer, so
CAPABILITY_WAKE_HOST is not advertised.

The Android client now has an explicit WakeHostProofFactory that uses the same
domain-separated transcript and an InternetPairingSigner. The legacy public
request path remains fail-closed when no proof is provided, so unsigned wake
requests are not sent from the client API.

## Open Integration

This change does not prove a sleeping Mac can be woken on a real network. It
also does not wire a UI-visible wake button to a persisted Android identity
signer. The client-side building block exists, but product code still needs to
provide the paired signer and current session details before wake can be exposed
as a user-facing control.
