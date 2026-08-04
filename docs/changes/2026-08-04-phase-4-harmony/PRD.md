# Phase 4: HarmonyOS NEXT client

Status: implemented, device verification blocked  
Owner: HarmonyOS client

## Goal

Provide a native ArkTS/ArkUI client that implements Vibe Screen Protocol v1
without KMP and keeps protocol, session, transport, decode, rendering, and input
responsibilities separate.

## Acceptance criteria

- clean DevEco project builds a signed HAP from documented commands;
- Protocol v1 hello, resume, heartbeat, video negotiation, and all representable
  input events interoperate with the Mac host;
- H.264 and HEVC use Harmony hardware decode into an ArkUI surface;
- old-session media is rejected and the media backlog never exceeds one frame;
- foreground/background transitions and disconnects resume with bounded backoff;
- touch, keyboard, pointer, scroll, and stylus pressure reach the Mac;
- install, upgrade, permission, troubleshooting, and MatePad Mini runbooks exist;
- a MatePad Mini passes the full device matrix in `TEST.md`.

## Explicit contract gaps

Protocol v1 has no stylus tilt/azimuth fields and no controller/peripheral event
message. Implementing those without a contract would create a temporary wire
protocol, so this client does not do so. They require additive schema changes
and cross-platform golden fixtures.

