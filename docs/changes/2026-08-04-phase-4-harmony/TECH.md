# Phase 4 technical design

The native project lives in `apps/harmony/` and depends only on HarmonyOS NEXT
platform APIs. Framework-independent `.ts` modules are compiled and tested on
the hosted runner; `.ets` platform and UI modules require the DevEco SDK.

```text
ArkUI page -> HarmonySessionController -> ProductSession -> Protocol v1 codec
     |                 |                       |
 input events      TCP channel 1          epoch/message validation
 XComponent        TCP channel 2 -> media parser -> latest frame -> AVCodec
 Ability lifecycle -> close/suspend -> bounded fresh reconnect
 Asset Store -> stable client id + versioned trusted-LAN host record
```

## Transport and session

TCP begins in legacy mode. The client sends `0x0d`, accepts a split or coalesced
`0x0d 0x01` acknowledgement, then switches to five-byte Protocol v1 framing:
channel plus big-endian payload length. Control and video remain distinct and
are limited to 16 MiB. Invalid acknowledgement, channel, length, protobuf,
message order, session identity, or cross-stream media fails closed.

`ProductSession` drives HostHello, SessionAccepted, list/start display,
VideoConfig, heartbeat, and VideoConfigResult. It sends video acceptance only
after the platform decoder configuration resolves. Old epoch and already-seen
media frames are dropped; wrong stream/config and unsupported fragmentation are
protocol failures. The pending encoded queue holds one frame.

The independent protobuf codec supports packed/unpacked repeated enums and
unknown-field skipping. It exactly reproduces both the historical Harmony hello
vector and the formal rich ClientHello/touch fixtures, and decodes the formal
host/session/display/video/media fixtures. Empty protobuf messages are emitted
as zero-length oneof values rather than omitted.

## Platform seams

`HarmonyTransport` owns socket generation, upgrade timeout, logical channel
dispatch, and stale callback suppression. `HarmonySessionController` owns the
single active product session, heartbeat timer, decoder, reconnect timer,
surface identity, input target, and UI status. Transport, controller, and
decoder each use operation generations; cleanup synchronously detaches captured
resources before awaiting them, so an old continuation cannot close or confirm
a newer session. Backgrounding closes transport
and decode resources; foregrounding creates a fresh v1 session with capped
jittered backoff. Protocol resume-result handling remains open and therefore is
not advertised.

`HarmonyVideoDecoder` keeps input buffers until a latest frame is available,
writes Annex-B payloads, renders output buffers to the XComponent surface, and
reports the first rendered output before the page claims streaming. The exact
commercial HarmonyOS SDK AVCodecKit declarations are not available in the
portable environment; DevEco compilation and device behavior remain mandatory.

ArkUI forwards all changed touch points (including Up/Cancel), normalized to
the real component bounds and negotiated rotation. Keyboard text is mapped to
a conservative USB HID subset with modifier bits; pointer buttons use a bit
mask. Stylus pressure travels through TouchEvent. Wheel/trackpad axis delivery,
the complete physical-key map, controller events, and stylus tilt/azimuth remain
gates rather than claims.

## Pairing, privacy, and upgrades

Asset Store calls use the API 12 `Map<Tag, Value>` shape. A random stable client
identifier and a versioned host/port/offer record are stored. Address-link
credentials are never persisted. This is not the cryptographic PairingRequest
proof exchange and does not authenticate plaintext trusted-LAN transport.
Secure pairing must be completed jointly with a compatible host.

The application declares only the Internet permission; it does not declare
network-information or background-running permissions without corresponding
runtime behavior. Data handling and record deletion are documented in
`apps/harmony/PRIVACY.md`; bundle/signing/version migration policy lives in
`apps/harmony/UPGRADE.md`.

The static project validator checks the real AppScope/entry/Hvigor graph,
resource/ability wiring, version consistency, native-only dependency boundary,
permission boundary, and that HAP targets call real OHPM/Hvigor commands. It is
explicitly not an ArkTS compiler or HAP substitute.
