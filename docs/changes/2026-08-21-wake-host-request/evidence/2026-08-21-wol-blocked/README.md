# 2026-08-21 Wake-on-LAN blocked evidence

## Result

BLOCKED for real-device Wake-on-LAN acceptance. No sleeping Mac on a verified
WOL-capable network was exercised from this worktree, and no physical wake
claim is made.

## Offline evidence completed

- Protocol v1 rejects wake requests before Host helper dispatch unless
  CAPABILITY_WAKE_HOST was negotiated, media is streaming, host_id matches the
  active Host, and paired proof fields are present.
- Mac Host authorization verifies the paired device identity, short validity
  window, session-bound proof transcript, and per-session nonce replay cache
  before building or sending a WOL packet.
- Android request APIs fail closed without proof and include a shared transcript
  proof factory for a future paired identity signer integration.

## Remaining external blockers

- Real Mac sleep/wake hardware and network broadcast acceptance.
- Identity-signed installed Host run with required local permissions.
- Product UI integration that supplies the Android paired identity signer to
  WakeHostProofFactory.
