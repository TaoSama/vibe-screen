# Phase 5 technical design

## Dependency direction

```text
SwiftUI app -> session orchestration -> generated Protocol v1
                                  \-> TCP transport adapter
             -> VideoToolbox decoder -> native CoreVideo renderer
             -> native gesture input -> Protocol v1 input
```

`VibeScreenProtocol` owns generated messages only. `VibeScreenCore` owns
session/stream resources, epochs, framing, PCM jitter, clipboard/file
validation, color fallback, gestures, policy, and WOL bytes.
`VibeScreenVideo` owns Annex-B adaptation and
`VTDecompressionSession`. The Xcode application owns SwiftUI/UIKit and maps
native user intent into core calls. Protocol and session modules do not import
UIKit, SwiftUI, or VideoToolbox.

## Trusted-LAN transport adapter

For the baseline MacHost on TCP `54321`, the client first sends authenticated
`SSWA` admission using the pairing token and validates the `SSWR` result. It
then sends the legacy upgrade marker `0D`, requires the `0D01` acknowledgement,
and switches the same connection to the Protocol v1 framed main session below.
Neither admission nor the upgrade marker is treated as an application message.
Malformed/truncated admission responses, rejected authentication, or an
invalid upgrade acknowledgement fail the connection before ClientHello.
Startup and frame sends have bounded timeouts and explicit cancellation; a
new connection cannot leave an older startup continuation suspended. Host
control envelopes must keep Protocol v1, strictly increasing message IDs, and
the negotiated session ID/epoch. Stale or cross-session control fails closed.
The pairing URL carries a 32-byte bearer token and is connection input only;
the iOS UI does not persist it and requires the user to paste it again for each
connection.

Each TCP frame is `channel: uint8`, `payload_length: uint32 big-endian`, then
exactly `payload_length` bytes. Channels are control `1`, video `2`, audio `3`,
and bulk transfer `4`. Control payload is a serialized Protocol v1 `Envelope`.
Video payload is a varint-delimited `MediaPacketHeader` followed by the exact
payload length declared in that header. Payloads larger than 16 MiB are
rejected before their body is buffered.

This adapter preserves logical channel identity; QUIC or WebRTC can replace it
without changing session/product messages. The current iOS adapter is
development-only plaintext and works with the MacHost only through explicit
legacy fallback; it must never be presented as secure Internet transport or as
evidence for the macOS/Android secure-record LAN path.

## Protocol v1 backward-compatible advanced negotiation

Advanced work remains in `vibescreen.protocol.v1` and only appends fields,
enum values, messages, and `Envelope.oneof` branches. The frozen
`fixtures/v1.binpb` baseline is unchanged. Capabilities `13...22` now allocate
audio, clipboard, files, HDR, color, multi-display, multi-client, host actions,
wake, and managed configuration. `advanced.proto` owns resource limits, color,
PCM audio, clipboard/file transfer, action, wake, and effective-policy messages.

Negotiation rules:

- a feature activates only when both Hello messages advertise it;
- `SessionAccepted.negotiated_capabilities` makes the intersection explicit;
  its absence means legacy single-stream SDR;
- unknown capabilities and fields are ignored, but a required unsupported
  capability is explicitly rejected with `UNSUPPORTED_CAPABILITY`;
- new scalar fields use proto3 `optional` when absence differs from zero;
- new payloads are sent only after negotiation; old readers safely preserve
  their Phase 0/5A behavior;
- every connection keeps its own `session_id` and monotonically increasing
  `session_epoch`; epochs are never global across clients.

## Advanced resource and message boundaries

- **Multiple clients/displays:** host advertises maximum clients, virtual
  displays, and streams. Start-display and video-config results bind an
  allocated `stream_id`; input gets an optional display/stream target. Missing
  targets retain the legacy active-stream meaning.
- **Audio:** independent `AudioConfig` result and `AudioPacketHeader`; never
  reuse video codec or allow audio backlog to block control/video.
- **Clipboard:** offer/request/chunk messages carry change ID, origin, MIME,
  size, and digest. Origin/change IDs prevent bidirectional feedback loops.
- **File transfer:** offer/accept/progress/cancel on control; data on bulk with
  transfer ID, offset, total length, and SHA-256. Paths are never trusted.
- **HDR/color:** video negotiation carries bit depth, primaries, transfer,
  matrix, and range as color-description fields, all guarded by `config_epoch`.
  `CAPABILITY_COLOR_MANAGEMENT` proves description negotiation and fallback only;
  HDR output requires `CAPABILITY_HDR_VIDEO`, an explicit decode profile, and
  retained HDR/EDR hardware evidence. Unsupported Main10/HDR is explicitly
  renegotiated to SDR.
- **Custom gestures:** mappings stay on-device. The host exposes a capability-
  gated action catalog/invocation API; UI gesture definitions never enter the
  protocol.
- **Wake:** only an already paired device may request wake with replay-safe
  proof. The macOS and Android USB/LAN clients share the same canonical
  HMAC-SHA256 proof over request ID, target MAC, host/device identity, key ID,
  authorization window, and nonce; wireless pairing tokens are the current
  shared secret source, while USB/default sessions remain deny-only. A request
  that passes the proof, replay, device-identity, and broadcast-target gates is
  converted to a standard UDP Wake-on-LAN magic packet. Wake-on-LAN remains
  transport behavior, not authentication. #199 owns the current-base evidence
  gate for this area after being rebased onto the merged #225 baseline, and
  sleeping-host/router/firmware behavior is still a real-device acceptance
  gate.
- **Managed devices:** Apple MDM configuration is read locally. The protocol
  carries product restrictions/results, not vendor-specific MDM payloads.

## Implemented client mechanics

- `ControlOutbox` is the only owner of outbound main-session message IDs. Its
  MainActor enqueue operation performs owner validation, ID allocation,
  envelope construction/encoding, and FIFO insertion synchronously, while one
  drain awaits TCP completion at a time. Connection/session replacement drops
  pending old-owner work and late completion cannot mutate the replacement.
- TCP callbacks carry an unforgeable connection owner through the MainActor
  delivery point. Session and decoder owners are separately unforgeable; the
  final pixel-buffer publication rechecks the exact session, decoder, stream,
  and config epoch, including when numeric protocol identifiers are reused.
- `VideoMediaGate` is per stream. Starting a config immediately blocks media;
  only completion of the matching positive `VideoConfigResult` send activates
  it. Protocol validation happens before that state change: stream/config IDs
  and bitrate must be nonzero, dimensions must each be `16...8192`, FPS must be
  `1...240`, rotation must be `0/90/180/270`, codec/color enums must be known,
  and the requested dimensions, FPS, bit depth, and transfer function must fit
  one advertised decode capability. Invalid configs leave the active epoch and
  decoder intact. A successfully installed newer config resets that stream's
  frame watermark to zero. Admission then strictly requires the current
  session epoch, nonzero bound stream, config epoch, codec,
  `fragment_count=1`, `fragment_index=0`, nonempty
  payload, and a strictly increasing nonzero frame ID. Rejected packets never
  reach VideoToolbox.
- Heartbeats register the Ping sequence and message ID before awaiting its send
  completion, validate exact Pong correlation, and fail the owner-scoped
  session after three expired intervals. Rotation clears pending deadlines and
  rejects late old-owner Pong delivery.
- `MultiDisplaySessionRegistry` isolates clients by `session_id + epoch`,
  enforces client/stream limits, rejects duplicate display/stream bindings, and
  releases old-epoch resources. The iOS model maintains a decoder per stream
  and targets touch at the selected binding.
- PCM S16LE audio validates format and exact frame bytes, rejects old session
  or config epochs, reorders a bounded packet window, and feeds a bounded
  `AVAudioPlayerNode` schedule through playback-only `AVAudioSession`.
- Clipboard data is read or written only inside explicit button handlers.
  Change IDs suppress loops; MIME, byte limit, and SHA-256 are checked before
  system pasteboard writes.
- Incoming files use hidden unique staging paths, safe basename validation,
  sequential offsets, negotiated chunk/aggregate/concurrency limits,
  per-chunk and final SHA-256, idempotent cancellation, and cleanup. Outgoing
  files stream from a security-scoped document URL rather than loading whole
  files into memory.
- macOS and Android now implement the same bounded single-file transfer domain
  for the production Protocol v1 USB/LAN TCP session. The transport adapter
  exposes logical channel `4` as bulk without assuming any WebRTC DataChannel.
  Control carries offer/accept/progress/cancel/complete; bulk chunks advance one
  chunk per accept/progress acknowledgement so writes remain bounded by the
  existing transport FIFO. Receivers default to reject until an application
  callback grants explicit approval, sanitize the advertised basename before any
  staging path is created, merge managed policy deny-wins, validate session
  epoch, offset, final flag, per-chunk SHA-256, and final SHA-256, and clean
  staging files on cancel, digest mismatch, disk error, or disconnect.
- The macOS Host session layer now owns a transport-neutral display router for
  Protocol v1 clients. Routes are keyed by `session_id` plus `session_epoch`;
  stale lower epochs cannot re-register while a newer route is active. Each
  client gets bounded display-to-`stream_id` bindings, over-cap clients/streams
  fail closed with `RESOURCE_EXHAUSTED`, and touch, pointer, scroll, key,
  controller, and host-action targets must match the session-owned binding.
  Routes are released on peer errors, disconnect notices, connection
  replacement, and server stop.
  Production `StreamingServer` still configures `max_clients = 1`,
  `max_virtual_displays = 1`, and one video stream per client until the
  transport, capture, virtual-display, and UI ownership are split into true
  concurrent client contexts.
- The current renderer advertises 8-bit SDR only. Unsupported Main10/PQ/HLG
  requests produce a structured SDR fallback with a larger `config_epoch`.
- Gesture mappings are local Codable state and may invoke only catalogued host
  action IDs. Managed policy is parsed fail-closed and merged deny-wins. WOL
  produces the standard 102-byte packet only after local HMAC authorization,
  nonce replay, device-identity, and broadcast-target checks pass. The
  current-base closure gate remains blocked without real sleeping Mac and WOL
  network evidence.

## Host and security TODO

The minimal MacHost compatibility boundary composes its existing authenticated
port `54321` admission/upgrade with the Protocol v1 session for iOS. The real
two-process loopback uses the production iOS Core control outbox and covers
Hello/capability negotiation, display list/start,
video configuration acknowledgement and media framing, heartbeat, targeted
touch, protocol error, and disconnect. The Host now provides the offline-tested
per-client route registry, stream/display allocation, negotiated client/stream
resource limits, input-target isolation, and route cleanup needed before the
transport can admit more than one concurrent Protocol v1 client. It still does
not prove advanced host runtime behavior. A compatible advanced host still must
provide multi-connection transport ownership, parallel capture/display pipelines,
PCM capture, advanced control handlers, WebRTC bulk streaming, color retry, and
an authenticated wake helper. `SecureChannel` now allocates audio `3` and bulk
`4`; the Android and macOS Internet record layers now derive independent
directional keys, durable nonce counters, and replay windows for all four
channels. Shared fixed vectors prove offline record interoperability only. The
macOS and Android Internet product sessions now expose raw audio/bulk
DataChannel record hooks with owner-scoped admission and bounded backlog
behavior. Audio capture/playback, clipboard/file-transfer product flows over
these channels, public-network E2E, and the client's plaintext trusted-LAN
implementation remain separate gates and are not evidence of the
macOS/Android secure-record LAN path.

## Rendering and color

VideoToolbox creates hardware-capable H.264 or HEVC decompression sessions from
SPS/PPS or VPS/SPS/PPS. CoreVideo pixel buffers retain platform color
attachments. The current renderer uses Core Image for correctness and aspect
fit. A Metal zero-copy renderer is a future optimization and requires measured
latency, color, power, and HDR comparison before replacement.
