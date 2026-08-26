# Phase 0: sustainable baseline

Status: in progress  
Owner: Vibe Screen core team  
Started: 2026-08-04

## Goal

Turn the upstream macOS/Android vertical slice into a traceable, testable base
that later phases can extend without inheriting an implicit wire protocol or
platform-specific architecture.

Phase 0 is complete only when the imported code, protocol contract, module
boundaries, reliability behavior, and Xiaomi 13 (2211133C) evidence all agree. A local
build alone is not completion.
The stable-release aggregate owner is
[`../2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json`](../2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json);
README status must not move from development preview to complete/stable until
that manifest evaluates to `can_mark_phase0_stable_release=true` with
`make phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1`.

## Scope

The first slice supports one Mac host, one Xiaomi 13 (2211133C), one display stream, and
USB as the mandatory transport. LAN may remain a buildable loopback path.

It must demonstrate:

1. explicit protocol-version and capability negotiation;
2. physical or virtual display capture and H.264/HEVC hardware decode;
3. single-touch tap/drag and keyboard input returning to the Mac;
4. a bounded latest-frame queue with observable drops;
5. disconnect, automatic reconnect, and rejection of an old session epoch;
6. machine-readable stream, queue, codec, and reconnect telemetry.

## Non-goals

- Phase 1's 60 FPS, sub-50 ms, and two-hour stability targets;
- Internet transport, TURN, production E2EE, or unattended device identity;
- HarmonyOS, iOS, audio, clipboard, file transfer, HDR, or multiple clients;
- a Compose rewrite before the inherited Android behavior is characterized;
- KMP before shared business rules justify its lifecycle cost.

## Acceptance criteria

- Upstream sources and licenses are pinned to immutable commit SHAs.
- `buf lint` and `buf build` pass for Protocol v1.
- Android unit tests and debug APK build pass from a clean checkout.
- macOS release build and unit tests pass with full Xcode selected.
- On Xiaomi 13 (2211133C), USB streams 1080p30 for 30 minutes without crash, deadlock,
  unbounded queue depth, or steadily increasing latency/memory.
- HEVC rejection selects H.264 explicitly; it never silently changes codec.
- A USB disconnect reconnects and no frame from the prior `session_epoch` is
  rendered afterward.
- Raw telemetry and external-camera latency samples are archived with toolchain
  versions and exact host/client commit.

## Environment gates

The initial audit found Swift 6.3.1, JDK 17, Android SDK/ADB, and no connected
Android device. The selected developer directory is Command Line Tools rather
than full Xcode, so XCTest is unavailable. `protoc` and `buf` are also absent.
These are recorded blockers, not waived acceptance criteria.
