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

The runnable Android baseline now enforces its first concrete module boundary:
`baseline/AndroidClient/transport` is a platform-neutral JVM module that owns
TCP connection streams, candidate promotion, output shutdown, and exactly-once
resource closure. The application module depends on that port while retaining
USB/LAN endpoint selection, trusted-LAN authentication, protocol upgrade,
session epochs, retry policy, and product callbacks. A module check normalizes
and rejects UI, Android platform, Protobuf, product-session, or protocol source
references and rejects production dependency declarations or resolved modules
outside Kotlin's runtime/compiler support. Source references to compiler-support
annotations remain forbidden; only the fixed transitive artifact in the resolved
graph is exempt. The live-resolution task declares its source, dependency, graph,
and classpath inputs and explicitly opts out of configuration caching rather than
reusing a stale dependency verdict. The transport module owns negative boundary
fixtures plus the concurrency and resource-lifecycle contract tests.

This is intentionally a partial extraction. `StreamClient` still composes local
transport with legacy/Protocol v1 session behavior, and `MainActivity` still
coordinates local and Internet product sessions. Focused Android Protocol v1
owners gate side effects on the active session object plus connection
generation. `FileTransferProductOwner` owns the Android file-transfer product
state, user-decision callback port, staging lifecycle, stale-offer cleanup, and
duplicate-transfer rejection behind the session boundary. The WakeHost product
owner now owns request lifecycle, result callback delivery, authorization-secret
handling, and packet-sender admission behind those gates; already accepted
completion writes may drain while new side effects fail closed after termination
admission closes. `RendererOwner` gates viewport/layout/render target/frame
admission for the current renderer boundary. This is offline/module evidence
only: sleeping-Mac wake, router/NIC WOL behavior, Host signing/TCC readiness,
and retained product logs remain blocked by the WakeHost current-base hardware
gate. Broader protocol/session ownership, decoder ownership beyond lifecycle
admission, renderer ownership beyond the current boundary, and UI/product
session ownership therefore remain to be enforced by additional module
boundaries before Phase 0 module ownership can be called complete.

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

### Baseline application integration

The runnable macOS and Android baseline uses an explicit connection-level
upgrade rather than guessing whether arbitrary bytes are Protobuf. The Android
client first sends legacy-safe byte `0x0d`; a supporting host replies with
`0x0d 0x01`, after which that connection is permanently Protocol v1. A timeout
or a first legacy host byte selects the inherited adapter without losing that
byte. An old client never sends the offer, so a new host retains the inherited
startup path. Protocol negotiation failures after a successful upgrade send a
`ProtocolError` and close instead of downgrading silently.

Protocol v1 TCP frames are `[channel: uint8][payload_length: uint32 big-endian]
[payload]`, with control channel `1` and video channel `2`. Control payloads are
serialized `Envelope` messages. Video payloads are a Protobuf-varint header
length, `MediaPacketHeader`, and the exact Annex-B bytes declared by
`payload_length`. A frame is capped at 16 MiB. The existing host latest-frame
queue remains the media policy; control messages never enter that eviction
queue.

The main-session flow is `ClientHello -> HostHello -> SessionAccepted ->
ListDisplays -> StartDisplay -> VideoConfig -> VideoConfigResult`. Media remains
blocked until the client accepts the configuration. Touch and heartbeat use
control envelopes, host epochs are propagated into decoder frames, and stale
session/config/stream/frame identifiers fail closed. The production baseline
advertises only capabilities actually connected to product behavior. Keyboard,
pointer, controller, and peripheral inputs can leave the Android client or reach
the Host only after upgrading into a Protocol v1 main session and negotiating
the matching capability; the explicit legacy fallback stays touch-compatible
only and does not grow keyboard or native-pointer wire types. Keyboard and
scroll input are verified on device through Protocol v1. Native pointer
move/click is wired through the same negotiated pointer path, but still requires
physical Android HID-mouse evidence before its gate can close. Telemetry is
emitted by local reliability reporting, not negotiated as a production Protocol
v1 peer capability.

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
