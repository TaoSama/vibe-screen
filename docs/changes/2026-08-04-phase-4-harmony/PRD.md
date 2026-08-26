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
- touch, keyboard, pointer, scroll, and stylus (base pressure/tilt and
  extended eraser/barrel/proximity under capability gating) reach the Mac;
- install, upgrade, permission, troubleshooting, and MatePad Mini runbooks exist;
- a MatePad Mini passes the full device matrix in `TEST.md`.

## Current evidence boundary

Portable checks now prove the independent codec and session sequence through
VideoConfig, transport upgrade/channel framing, media fixture parsing, stale
epoch filtering, bounded queues, input envelope encoding, reconnect policy,
resume result success/failure handling, post-resume old-epoch control/media
rejection, host-restart fresh-session fallback, and the expected DevEco project
file graph. A Host interop preflight/manifest verifier now records the exact
external evidence required for HostHello/session/display/video/control/media,
background/foreground, Wi-Fi loss/restore, bounded reconnect, host restart, and
old-epoch rejection. ArkUI/platform sources connect those seams, but they have
not been compiled by DevEco. None of the acceptance criteria requiring a HAP,
Harmony SDK behavior, Mac interoperability, signing, secure pairing, or a device
is complete.

## Explicit contract gaps

Protocol v1 now defines the additive CAPABILITY_STYLUS_EXTENDED (tool kind,
barrel buttons, contact/proximity state) on top of base CAPABILITY_STYLUS
(position, pressure, tilt). The Harmony portable core encodes both under
capability gating, but the production client advertises only
CAPABILITY_STYLUS and not CAPABILITY_STYLUS_EXTENDED until DevEco/API-checker/
HAP/MatePad evidence exists. A contacting pen can fall back to touch when the
peer lacks stylus support; eraser, proximity/hover, and barrel buttons cannot
be losslessly downgraded and are suppressed when the extended capability is not
negotiated. Protocol v1 now defines `CAPABILITY_CONTROLLER = 26` and a
lifecycle-scoped `ControllerEvent` wire contract, and the Harmony portable
protocol model now mirrors `Capability.CONTROLLER = 26`. The production source
advertises that capability, encodes `ControllerEvent`, waits for accepted
`InputAck` before admitting controller state, validates lifecycle bounds, and
sends all-zero neutral `DISCONNECTED` releases before active controller teardown
or resume. This closes the portable source contract only. No DevEco/API-checker,
HAP, Host interoperability, or MatePad evidence exists for this path, so
controller-specific input remains a device acceptance gate rather than a shipped
claim.

Physical keyboards and mice use the existing key/pointer messages. Wheel axis
delivery still needs DevEco/device confirmation before it is advertised as
accepted behavior. Address-link import is not secure pairing: Pairing proof,
credential issue/revoke, and replay protection remain separate gates.
