# Phase 4: HarmonyOS NEXT client

Status: product source wired; DevEco, host interoperability, and device verification blocked
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
- touch, keyboard, pointer, scroll, extended stylus, and controller state reach the Mac;
- install, upgrade, permission, troubleshooting, and MatePad Mini runbooks exist;
- a MatePad Mini passes the full device matrix in `TEST.md`.

## Current evidence boundary

Portable checks now prove the independent codec and session sequence through
VideoConfig, transport upgrade/channel framing, media fixture parsing, stale
epoch filtering, bounded queues, input envelope encoding, reconnect policy, and
the expected DevEco project file graph. ArkUI/platform sources connect those
seams, but they have not been compiled by DevEco. None of the acceptance
criteria requiring a HAP, Harmony SDK behavior, Mac interoperability, signing,
secure pairing, or a device is complete.

## Advanced-input evidence boundary

The additive Protocol v1 stylus and controller contracts now exist. Harmony's
portable codec matches their cross-platform golden fixtures and its session layer
enforces capability, lifecycle, epoch, full-state, and release rules. This does
not complete ArkUI/native event acquisition or physical-device interoperability;
those still require DevEco and MatePad evidence.

Physical keyboards and mice use the existing key/pointer messages. Wheel axis
delivery still needs DevEco/device confirmation before it is advertised as
accepted behavior. Address-link import is not secure pairing: Pairing proof,
credential issue/revoke, and replay protection remain separate gates.
