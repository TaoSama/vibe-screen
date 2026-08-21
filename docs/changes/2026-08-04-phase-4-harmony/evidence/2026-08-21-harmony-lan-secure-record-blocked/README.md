# HarmonyOS trusted-LAN secure-record gate - BLOCKED

Date: 2026-08-21
Branch: `codex/harmonyos-auth-records`

## Intended gate

Close the Phase 4 HarmonyOS trusted-LAN authenticated transport gap by proving
that a HarmonyOS NEXT client can pair with the Mac Host, negotiate non-legacy
AES-256-GCM application records, carry Protocol v1 control and media inside
those records, and reject nonce reuse, replay, wrong keys, stale epochs, wrong
channels, and tampering before any payload dispatch.

## Result

The real-device gate remains blocked. This worktree does not have a DevEco /
HarmonyOS SDK command-line environment, a signed Harmony HAP, a HUKS-backed
cryptography provider wired into the production client, a HarmonyOS MatePad
device session, or Host interoperability logs for the Harmony socket path. The
production `HarmonyTransport` path therefore still uses the explicit plaintext
Protocol v1 TCP upgrade and must not be presented as encrypted LAN evidence.

The committed source adds only a portable contract verifier:

- `apps/harmony/entry/src/main/ets/core/security/ChannelRecordSecurity.ts`
  mirrors the macOS/Android record format and replay rules behind injected
  SHA-256/HKDF/AES-256-GCM primitives.
- `apps/harmony/tests/channel-record-security.test.mjs` uses Node crypto to
  verify Harmony against `contracts/fixtures/security/v1/channel-records.json`,
  the same fixture used by the macOS Host and Android client tests.

## Local source checks

```text
cd apps/harmony && pnpm run verify
  PASS: 36 semantic project files; 125/125 portable tests
```

The passing verifier covers byte-for-byte key derivation, record sealing/opening,
nonce validation, replay rejection, wrong-key rejection, stale session epoch
rejection, channel relabel rejection, tamper rejection, closed-session rejection,
and explicit legacy plaintext fallback labeling.

## Why this does not close the gate

- No DevEco ArkTS/API checker ran.
- No debug or signed release HAP was produced.
- No HUKS-backed P-256/HMAC/HKDF/AES-GCM provider was exercised.
- No HarmonyOS device installed or ran the client.
- No Mac Host saw a Harmony secure-record negotiation or encrypted record.
- No real control/media stream, reconnect, latency, or soak evidence exists for
  HarmonyOS trusted LAN.
- Android Nubia P0110 / pacific evidence remains Android evidence only and is
  not a HarmonyOS substitute.

## Next runbook

Follow `docs/runbook/harmony-matepad-mini.md` after DevEco, signing, a MatePad
Mini, and a compatible Mac Host are available. The accepted evidence must show
non-legacy encrypted negotiation markers, trusted_lan_encrypted=true,
trusted_lan_legacy_plaintext=false, and fail-closed probe results for nonce
reuse, replay, wrong key, stale epoch, wrong channel, and tamper.
