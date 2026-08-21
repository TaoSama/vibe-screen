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
after the platform decoder configuration resolves and opens input only after
the result is written. Negotiated capabilities must be a subset of both offers;
touch, pointer/scroll, keyboard, and stylus (base pressure/tilt and extended
tool kind, barrel buttons, contact/proximity state) are locally gated before
encoding. The production Harmony client advertises only CAPABILITY_STYLUS and
not CAPABILITY_STYLUS_EXTENDED until DevEco/API-checker/HAP/MatePad evidence
exists; a contacting pen can fall back to touch for peers without stylus, while
eraser, proximity/hover, and barrel buttons are suppressed when the extended
capability is not negotiated. Old epoch and already-seen media frames are dropped; wrong
stream/config and unsupported fragmentation are protocol failures.

Every outbound control uses one FIFO writer. It assigns and encodes the next
message ID at dequeue time, allowing an asynchronous decoder configuration to
finish without overtaking heartbeat or input traffic. Response correlation is
tracked for hello, display selection, video configuration, and Pong. Only one
Ping may be outstanding; a missing matching Pong causes a retryable reconnect.
The control backlog has a hard bound and fails into recovery rather than
accumulating unlimited stale input under socket backpressure. Protocol
responses use the critical FIFO; all input events share a secondary FIFO so
Pong and VideoConfigResult cannot be starved without reordering a gesture's
begin/change/end lifecycle. Handshake,
display/configuration, and first-frame progress each have generation-bound
watchdogs; initial first-frame timeouts retry keyframe requests before reconnect.
The capacity-one decoder ingress preserves reference-chain decodability:
keyframes cannot be replaced by deltas, a delta gap/overflow/push failure enters
wait-keyframe, and AVCodec must accept the keyframe before deltas resume.

The independent protobuf codec supports packed/unpacked repeated enums and
unknown-field skipping. It exactly reproduces both the historical Harmony hello
vector and the formal rich ClientHello/touch fixtures, and decodes the formal
host/session/display/video/media fixtures. Empty protobuf messages are emitted
as zero-length oneof values rather than omitted.

## Platform seams

`HarmonyTransport` owns socket generation, upgrade timeout, logical channel
dispatch, and stale callback suppression. Each socket generation has one close
lease: parse failure, timeout, socket error/close, controller close, and connect
supersede race to claim it, and only the winner detaches, closes, and emits at
most one disconnect notification. `HarmonySessionController` owns the
single active product session, heartbeat timer, decoder, reconnect timer,
surface identity, input target, and UI status. Transport, controller, and
decoder each use operation generations; cleanup synchronously detaches captured
resources before awaiting them, so an old continuation cannot close or confirm
a newer session. A fully streaming session that negotiated `SESSION_RESUME` can
export one immutable in-memory snapshot. The replacement writer continues after
the assigned message-ID high-water and sends ResumeSessionRequest. A result must
correlate, retain the exact session ID, and advance both payload and envelope
epoch. Rejection or malformed metadata closes the connection rather than falling
through to ClientHello on the same transport. Accepted recovery re-enters display
selection and decoder configuration before input or media reopen. The current
Mac Host still requires ClientHello first, so this portable state machine does
not establish resume interoperability.

Transport close plus decoder stop/release are all attempted even if a sibling
operation fails. Aggregated cleanup errors remain visible in status diagnostics
but do not suppress an otherwise safe retryable reconnect.

`HarmonyVideoDecoder` keeps input buffers until a latest frame is available,
writes Annex-B payloads, renders output buffers to the XComponent surface, and
reports the first rendered output before the page claims streaming. Once a
candidate is registered, configure/surface/prepare/start run transactionally;
any stage failure owner-safely detaches and best-effort stops/releases it, with
the primary and cleanup failures aggregated. The candidate owns a lifecycle
lease recording its current stage, in-flight operation, start invocation,
cancellation, and the single cleanup promise. Supersede/release atomically
detach that lease, wait for its active platform call to settle, and never run
cleanup concurrently with configuration. All contenders observe the same
cleanup result; a start that may have taken effect is stopped exactly once
before one release, and conditional clearing prevents an old continuation from
touching a replacement. The transition owner retains the detached cleanup
promise even while no candidate is globally active. A third configure/release
therefore joins that barrier instead of bypassing it, and a replacement cannot
be installed until cleanup settles. A candidate-creation lease is installed
before calling the native decoder factory. If ownership changes while creation
is pending, cleanup waits for that exact promise, performs one uninitialized
release, and propagates factory/release failure to configure, release, and all
later barrier waiters; no later native create starts early. The exact
commercial HarmonyOS SDK AVCodecKit declarations are not available in the
portable environment; DevEco compilation and device behavior remain mandatory.

ArkUI forwards all changed touch points (including Up/Cancel), normalized to
the real component bounds and negotiated rotation. Keyboard text is mapped to
a conservative USB HID subset with modifier bits; pointer buttons use a bit
mask. Stylus events travel through TouchEvent; the portable core encodes both
the base stylus fields (position, pressure, tilt) and the extended fields
(tool kind, barrel buttons, contact/proximity state) under capability gating.
The portable session accepts one matching stylus sequence at a time, matching
the Host's pointer/tool/contact lifecycle. A stylus control remains pending
until the control writer reports a successful send; resume snapshots and
background release completion fail closed while any accepted stylus control is
still unwritten.
Wheel/trackpad axis delivery and the complete physical-key map remain gates
rather than claims. Protocol v1 now defines `CAPABILITY_CONTROLLER = 26` and a
lifecycle-scoped `ControllerEvent` wire contract, and the Harmony portable
protocol model now mirrors `Capability.CONTROLLER = 26`. The production source
advertises that capability, encodes `ControllerEvent`, waits for accepted
`InputAck` before admitting controller state, validates lifecycle bounds, and
sends all-zero neutral `DISCONNECTED` releases before active controller teardown
or resume. The platform controller route is still a source boundary rather than
a device result: DevEco/API-checker, HAP, Host interoperability, and MatePad
evidence for that path remain absent, so controller-specific input remains a
device acceptance gate rather than a shipped claim.

## Pairing, privacy, and upgrades

Asset Store calls use the API 12 `Map<Tag, Value>` shape. A random stable client
identifier and a versioned host/port/offer record are stored. Address-link
credentials are never persisted. A separate alias stores a versioned security
record containing pinned host identity, a verified 32-byte credential, session
key metadata and durable control-replay high-water, or a credential-free
revocation tombstone. Corrupt or unknown records fail closed.

The portable pairing client implements protobuf PairingOffer/PairingRequest/
PairingResult fields, fixed algorithm/size/expiry checks, length-prefixed
domain-separated transcripts, bootstrap MAC, host-proof verification,
ECDH/HKDF credential-key derivation, AES-GCM credential opening, and unconditional
single-use cleanup. Credential installation checks its immutable generation
before and after persistence. Replay high-water is persisted before admission;
revocation advances the generation and persists its tombstone before subsequent
authorization can succeed.

This core is not reached by the trusted-LAN address importer. A HUKS-backed
non-exportable key/cryptography provider, controller/UI exchange, authenticated
record layer, and compatible Mac Host remain required. Existing TCP stays
plaintext, and unauthenticated DeviceRevoked is deliberately not admitted.

Alias operations are serialized. Existing records use `asset.update`; missing
records use `asset.add`, so an update failure never deletes the prior host or
identity. Client identity creation treats an add conflict as another creator's
win and reloads that record. A validated bare identity from the earlier
development format is atomically wrapped in the version-1 JSON record without
changing its identifier. These platform calls still require DevEco and device
verification.

The application declares only the Internet permission; it does not declare
network-information or background-running permissions without corresponding
runtime behavior. Data handling and record deletion are documented in
`apps/harmony/PRIVACY.md`; bundle/signing/version migration policy lives in
`apps/harmony/UPGRADE.md`.

The static project validator checks the real AppScope/entry/Hvigor graph,
resource/ability wiring, version consistency, native-only dependency boundary,
permission boundary, method-scoped production imports/calls, packaged license
resources, and that HAP targets call real OHPM/Hvigor commands. JSON5 is parsed
rather than searched as text. TypeScript-compatible ArkTS sources and the
non-declarative ArkUI page shell must have no portable parse diagnostics;
negative fixtures retain misleading dead-code identifiers both outside and
inside target methods. Critical gates must use the expected early-return or
fail-closed control-flow shape, and constant-false, short-circuited, or directly
post-return calls are rejected. Each capability guard must precede and dominate
all protected sends in its straight-line method; late-but-reachable guards are
negative-tested. Direct return/throw and supported constant if/else termination
also make all following calls unreachable; unrecognized control-flow shapes
fail the conservative critical-guard checks. Portable core tests prove
negotiated input and bounded-queue behavior. This is deliberately limited
syntax/control-flow evidence, not a general reachability proof, the DevEco ArkTS API/type checker,
the full declarative ArkUI parser, or a HAP substitute.
