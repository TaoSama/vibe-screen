# 2026-08-23 QR pairing current-base blocked record

## Scope

This record belongs to branch `codex/phase3-pairing-flow`, rebased for the
current `origin/main` line. It covers the offline QR/manual pairing verifier and
local session-lease fail-closed checks added for Phase 3. It does not cover
Mac/Android automatic invocation of Authority session-profile issuance and does
not change the release gates for public Internet mode.

The work does not deploy or exercise `services/authority` or `services/signaling`
in a production network. It verifies local one-time QR credential handling,
strict profile expiry, replay rejection, unsigned Authority lease schema, and
paired host/device binding on source-level and fixture paths only.

## Offline coverage

- Android rejects QR payloads unless they use the canonical
  `vibescreen://pair?v=1&o=` envelope and base64url payload before credential
  material is decoded.
- Android consumes a scanned offer object exactly once.
- Android refuses a signed session lease when the lease signature does not verify
  against the paired host identity.
- Authority emits the unsigned Android lease fields required by the Mac issuer and
  Android profile contract, including bounded `expires_at` for admission.
- macOS reserves the exact Authority-supplied `session_epoch` and rejects stale
  epochs at or below the durable high-water mark.
- Existing shared pairing fixtures remain the cross-language offline source for
  canonical request, acceptance, transcript, derived context, and key
  identifiers.

The local Command Line Tools environment could not compile XCTest, so this
record does not count the macOS XCTest cases for first-attempt offer consumption
or unsigned-lease `expires_at` rewriting as locally executed evidence. Those
source-level cases require an Xcode-capable test run before they can be cited as
executed macOS XCTest coverage.

## Blocked gates

The following evidence is unavailable in this environment and remains blocked:

- public TLS signaling or Authority deployment;
- Mac/Android automatic invocation of Authority session-profile issuance;
- real Android camera QR scan and device-to-host request/acceptance exchange;
- public Internet NAT traversal and real remote TURN route;
- ScreenCaptureKit-to-Android decoded video;
- real network handoff, revocation propagation, latency, and soak.

Local loopback, forced local coturn, synthetic Protocol v1 media, explicit
legacy plaintext fallback, and local source-level parser tests must not be
counted as public-Internet E2EE or real QR device-scan evidence.

## Result

Blocked for production/public-Internet acceptance. Use this directory only as
offline fail-closed evidence for the QR/manual pairing verifier slice.
