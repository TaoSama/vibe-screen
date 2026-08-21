# 2026-08-21 QR pairing public-Internet blocked record

## Scope

This record belongs to branch `codex/phase3-qr-pairing-flow`. It covers the
offline QR pairing verifier and local session-lease fail-closed checks added for
Phase 3. It does not cover production account/session authority issuance and does
not change the release gates for public Internet mode.

The work deliberately stays outside `services/authority` and
`services/signaling` production issuer paths. PR #200 owns the account/session
authority profile issuance service boundary; this branch only verifies local QR
one-time credential handling, strict profile expiry, replay rejection, and paired
host/device binding.

## Offline coverage

- Android rejects QR payloads unless they use the canonical
  `vibescreen://pair?v=1&o=` envelope and base64url payload before credential
  material is decoded.
- Android consumes a scanned offer object exactly once.
- macOS consumes a one-time offer on first redemption attempt, including a failed
  bootstrap MAC attempt, so replaying the original request fails closed.
- Android refuses a signed session lease when the lease signature does not verify
  against the paired host identity.
- macOS unsigned local lease input now requires a bounded `expires_at`, and the
  local issuer rewrites it to the issuer TTL before signing.
- Existing shared pairing fixtures remain the cross-language offline source for
  canonical request, acceptance, transcript, derived context, and key identifiers.

## Blocked gates

The following evidence is unavailable in this environment and remains blocked:

- public TLS signaling or Authority deployment;
- production account/session authority profile issuance environment;
- real Android camera QR scan and device-to-host request/acceptance exchange;
- public Internet NAT traversal and real remote TURN route;
- ScreenCaptureKit-to-Android decoded video;
- real network handoff, revocation propagation, latency, and soak.

Local loopback, forced local coturn, synthetic Protocol v1 media, and explicit
legacy plaintext/LAN fallback must not be counted as public-Internet E2EE or QR
device-scan evidence.

## Result

Blocked for production/public-Internet acceptance. Use this directory only as
offline fail-closed evidence for the QR pairing verifier slice.
