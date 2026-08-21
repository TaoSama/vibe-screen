# Wake-on-LAN blocked acceptance runbook

Use this runbook when hardware is available to turn the offline wake-host
authorization work into real Wake-on-LAN evidence.

## Preconditions

- Mac supports Wake for network access and is connected to power.
- The target network forwards local broadcast WOL frames to the Mac NIC.
- The Host build is identity-signed and has required TCC permissions before the
  sleep attempt.
- The client device is already paired through the Phase 3 identity flow. If an
  Android handset is used, record it as nubia P0110 / pacific / Android 16 /
  SDK 36 only when the serial is EP0110PZ0B9110300B.

## Evidence to collect

1. Host app revision and code signature identity.
2. Paired host and device identity ids, with public keys redacted or hashed.
3. Wake request log showing request id, host id, device id, key id, issued time,
   expiry time, session epoch, nonce hash, and authorization result.
4. Network evidence that one WOL magic packet was emitted only after proof
   verification.
5. Mac sleep timestamp and successful wake timestamp.
6. Negative checks for unpaired device, expired proof, reused nonce, and proof
   signed for a different session id or epoch.

## Blocked status for 2026-08-21

This worktree has no real sleeping Mac plus WOL-capable network acceptance run.
Do not close the Phase 5 WOL gate from the offline tests alone.
