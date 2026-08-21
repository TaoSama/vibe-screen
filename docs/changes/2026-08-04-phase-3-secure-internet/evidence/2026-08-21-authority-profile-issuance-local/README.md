# 2026-08-21 Authority profile issuance local evidence

## Scope

This record covers the local source-level implementation of Phase 3 Authority
session-profile issuance in this worktree. The new Authority endpoint performs
admin-authorized account ensure, host/client device registration, signaling
session admission, and unsigned Android lease construction in one PostgreSQL
transaction. The paired Mac remains responsible for validating local pairing
state and signing the lease with its Keychain identity before Android import.

This is not public Internet or real-device evidence. No ADB command was run for
this record.

## Commands

The validation commands for this record are listed in `commands.txt`. Results
were captured from the local shell on 2026-08-21 Asia/Shanghai.

## Passed

- `services/authority`: Go unit/package tests passed, including profile issuance
  auto-registration, idempotency, unsigned lease field set, strict token scope,
  revoked/suspended/stale-epoch fail-closed paths, and invalid contract
  rejection. PostgreSQL integration tests are present but skipped without a test
  database URL.
- `services/signaling`: Go package tests passed. The authority process
  integration test includes the profile issuance path and direct-unregistered
  signaling denial, but skips locally without database URLs.
- `tests/phase3`: Python static contract discovery passed and checks that the
  Authority unsigned lease fields match the macOS unsigned decoder and remain a
  strict subset of Android's signed profile fields.
- `baseline/MacHost`: release build passed.
- `git diff --check`: passed.

## Blocked / not claimed

- Swift XCTest execution is blocked in this local command-line environment by
  `error: no such module 'XCTest'`.
- No public TLS ingress was deployed.
- No Mac/Android automatic endpoint invocation was exercised.
- No real Android UI profile import was exercised.
- No real ScreenCaptureKit media or visible Mac input path was exercised.
- No public TURN route, NAT traversal, carrier path, packet capture, latency,
  handoff, active PeerConnection/TURN disconnect, or soak evidence was produced.
- No Android device command was run; this record does not mention or relabel any
  device acceptance result.
