# Phase 0 technical design

## Baseline strategy

`baseline/` contains the pinned Telemachus snapshot because it is an
MIT-licensed SideScreen derivative that already carries several reliability
changes. Keeping it intact provides a known vertical slice while new contracts
are established. It is a transition source tree, not the final ownership
model.

Changes proceed in this order:

1. protect current behavior with characterization tests;
2. adapt the legacy byte protocol behind a transport adapter;
3. integrate Protocol v1 negotiation and golden fixtures;
4. extract one responsibility at a time behind the ports below;
5. remove the legacy protocol only after mixed-version behavior is tested.

## Target dependency direction

```text
platform UI -> session orchestration -> protocol + ports
                                      -> telemetry

macOS adapters:  display -> capture -> encoder -> transport
Android adapters: transport -> decoder -> renderer
                  input producer -> transport -> macOS input adapter
```

Protocol, session rules, and telemetry may not import ScreenCaptureKit,
VideoToolbox, MediaCodec, ADB, Network.framework, UI frameworks, or concrete
transport implementations.

## Module ownership

| Module | Owns | Must not own |
| --- | --- | --- |
| Display | enumeration, virtual lifecycle, display modes | capture, encoding, network |
| Capture | frame acquisition and capture metadata | codec selection, retry |
| Encoder | codec configuration, keyframes, encoded frames | connection lifecycle |
| Transport | bytes, logical channels, connection state | product session semantics |
| Session | negotiation, state machine, epochs, cleanup | platform APIs |
| Input | coordinate transforms and Mac event injection | client gesture UI |
| Telemetry | structured metrics/events | business-control decisions |
| Decoder | MediaCodec lifecycle and decode recovery | host policy |
| Renderer | presentation, rotation, letterboxing | protocol and network |

The intended extraction destinations are `apps/macos/Packages/*` and Android
feature modules under `apps/android/`. They are created only as code is moved;
empty scaffolding would claim boundaries without enforcing them.

## Protocol v1

The schemas under `contracts/proto/vibescreen/protocol/v1/` are the source of
truth. The control channel uses a length-delimited `Envelope` and media uses a
separate logical channel with `MediaPacketHeader` followed by its payload.

Every envelope carries:

- a negotiated protocol version;
- monotonic message and correlation IDs;
- opaque session ID and monotonically increasing session epoch;
- sender-local monotonic timestamp for ordering and local duration only;
- exactly one payload.

Compatibility rules:

- field numbers and enum values are never reused;
- removed fields are reserved before deletion;
- receivers ignore unknown fields but reject unsupported required capability;
- host-to-client behavior is sent only after capability negotiation;
- reconnect increments `session_epoch`; adapters drop older media and input;
- codec fallback is an explicit `VideoConfig` / `VideoConfigResult` exchange.

## Transport and backpressure

Control is reliable and ordered. Media is logically independent and optimized
for the newest decodable frame. Phase 0 may multiplex both over TCP, but the
framer must preserve channel identity so QUIC/WebRTC can replace it later.

The host send path has a configurable capacity of at most two encoded frames.
When a slow consumer invalidates inter-frame dependencies, it discards the
backlog, increments a drop counter, and schedules a keyframe. No queue may grow
with stream duration.

## Security boundary

The inherited LAN bearer token and plaintext TCP are development-only. Pairing
messages reserve the final identity flow, but Phase 0 does not claim Internet
security. USB trust currently inherits ADB authorization and must be called out
in UI and tests rather than described as end-to-end device authentication.

## Architecture decisions

- Use Protobuf independently from Swift and Kotlin; defer KMP.
- Retain the physical-display path because `CGVirtualDisplay` is private.
- Preserve Annex-B codec behavior during characterization; codec containers
  are an adapter detail, not an application-layer message definition.
- Migrate Android UI incrementally after session/media/input responsibilities
  leave `MainActivity`, rather than combining UI and protocol rewrites.
