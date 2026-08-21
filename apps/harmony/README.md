# Vibe Screen for HarmonyOS NEXT

Native ArkTS/ArkUI tablet client. It implements Vibe Screen Protocol v1
independently and has no Kotlin Multiplatform or Android runtime dependency.

The source now contains the product-session wiring that can be completed
without a device: legacy-to-v1 upgrade, channel-aware TCP framing, host/session
negotiation, display selection, video configuration, media epoch filtering,
XComponent/AVCodec handoff, heartbeat, bounded reconnect, and ArkUI touch,
keyboard, pointer, and stylus entry points. The portable core supports the shared
Protocol v1 base stylus (position, pressure, tilt) and extended stylus
(tool kind, barrel buttons, contact/proximity state) encoding and capability
gating. This is still a development preview. The portable core also implements
fail-closed ResumeSessionResult,
single-use PairingOffer/Request/Result processing, and durable credential,
control-replay, and revocation state. No DevEco SDK was available for this
record, so ArkTS compilation, HAP output, platform API behavior, and device
interoperability are not claimed.

## Requirements

- DevEco Studio with HarmonyOS NEXT SDK API 12 or newer;
- DevEco-managed OHPM and Hvigor 5.0.2 command-line tools;
- Node.js 20+ and pnpm 9+ for portable checks;
- a HarmonyOS NEXT tablet for install, hardware decode, input, and lifecycle tests;
- a Protocol v1 Mac host.

The repository does not redistribute the proprietary HarmonyOS SDK or signing
credentials. Install them through DevEco Studio and use a certificate owned by
your developer account.

## Portable checks

```bash
cd apps/harmony
pnpm install --frozen-lockfile
pnpm run verify
make doctor
```

`pnpm run verify` checks the real project layout, type-checks only the portable
core, parses TypeScript-compatible production ArkTS plus the non-declarative
ArkUI page shell, verifies method-scoped production imports/calls and the
expected early-return/fail-closed shape for critical guards, and runs
golden/unit tests against the shared Protocol v1 fixtures. It rejects explicit
constant-false, short-circuit, and directly post-return dead paths but is not a
general control-flow proof; capability guards must also precede every protected
send in their straight-line platform method. It does not run the ArkTS API/type checker, parse
the complete declarative ArkUI builder grammar, invoke DevEco, or produce a
HAP. `make doctor` reports whether OHPM and Hvigor are available.

## DevEco build and test

Import `apps/harmony` in DevEco Studio, install/synchronize the API 12+ SDK, and
select **entry > default > debug > Build HAP**. In a configured CLI shell:

```bash
cd apps/harmony
make build-debug
make build-release
```

The Host resume interop evidence gate is separate from the portable source
checks and from producing a HAP. For a local readiness bundle that remains
blocked until DevEco, HDC, a signed HAP, a HarmonyOS NEXT MatePad Mini, and a
resume-capable Host run are available:

```bash
make harmony-host-interop-preflight EVIDENCE_DIR=/path/to/redacted/evidence
```

For a real acceptance package, fill `harmony-host-interop.json` from the raw
HarmonyOS device and Host logs, then run:

```bash
make harmony-host-interop-gate EVIDENCE_DIR=/path/to/redacted/evidence
```

`build-debug` and `build-release` call real `ohpm install` and Hvigor
`assembleHap`; there is no Node packaging substitute. A release profile and
signing certificate must be configured locally. `make release` accepts exactly
one signed release HAP, copies it to `dist/0.1.0/`, and writes `SHA256SUMS`. The
build must be repeated from a clean checkout in DevEco before any release claim.
The HAP raw resources carry the repository MIT license and Harmony runtime
notice; `make release` also copies the root license/notices beside the HAP and
includes them in the checksum manifest.

## Run in trusted-LAN development mode

1. Start the Protocol v1 Mac host on TCP port `54321`.
2. Paste its host address and connect, or import a `vibescreen://` link to fill
   the address. The one-time credential in that link is never persisted.
3. The client offers `0x0d`, requires `0x0d 0x01`, then negotiates the display
   and H.264/HEVC configuration before accepting media.
4. Backgrounding closes the connection and decoder. If a fully streaming
   session negotiated `SESSION_RESUME`, foregrounding makes one generation-bound
   resume attempt with continuous message IDs; otherwise it establishes a fresh
   bounded-backoff session. The app does not claim to bypass HarmonyOS
   background limits.

This mode is authenticated neither by the imported link nor by the current
Harmony controller and is not encrypted. Use it only on a trusted LAN. The
portable security core validates PairingOffer/PairingRequest/PairingResult,
consumes every offer once even on failure, and can persist either a verified
credential or a revocation tombstone. The production Harmony cryptography
provider, controller/UI exchange, record layer, and compatible Mac host remain
integration gates; the UI does not present address import as secure pairing.

## Architecture

- `core/protocol`: dependency-free Protocol v1 codec with formal golden vectors;
- `core/session`: product negotiation, message/epoch validation, and backoff;
- `core/transport`: streaming upgrade parser and control/video framing;
- `core/media`: media packet parser and capacity-one latest-frame queue;
- `core/input`: letterbox/rotation mapping and USB HID helpers;
- `platform`: TCP, Asset Store, AVCodec, lifecycle, and session controller seams;
- `pages`: adaptive tablet connection and streaming surface.

Control messages are protobuf envelopes on channel 1. Channel 2 carries a
varint-delimited `MediaPacketHeader` plus Annex-B media. Old session epochs are
dropped, cross-stream/config media is rejected, and pending encoded media never
exceeds one frame. A single FIFO writer assigns message IDs only when dequeuing
and serializes every control send. A `VideoConfigResult(accepted=true)` is
queued only after the decoder configuration promise succeeds, and input opens
only after that result is written. Heartbeats allow one outstanding Ping and
force a retryable reconnect after the matching Pong deadline. The writer has a
hard backlog bound and lets protocol responses overtake the input-event FIFO;
input begin/change/end ordering remains intact, and overflow
fails into fresh recovery instead of retaining unlimited stale input.
Session-progress and first-frame watchdogs
cover peers that stop before heartbeat becomes available.

The decoder ingress starts in wait-keyframe state. A queued keyframe cannot be
replaced by a delta frame; losing any dependent delta clears the bounded queue,
drops later deltas, and asks the host for a new keyframe. Recovery completes
only when AVCodec accepts the keyframe input buffer.

Decoder initialization is transactional after candidate registration:
configure, surface binding, prepare, and start failures owner-safely detach and
best-effort stop/release while preserving cleanup diagnostics. Each decoder
instance carries its own lifecycle lease. Supersede/release requests wait for
the current platform operation to settle, share one cleanup promise, and use
stop-before-release whenever start may have taken effect; an old continuation
cannot clear its replacement. A transition owner retains detached cleanup as a
barrier, so later configure/release calls cannot start or return while that
resource is still live. The placeholder candidate is installed before native
decoder creation begins, so the same barrier also covers a pending
`createVideoDecoderByMime()` and exposes creation or uninitialized-release
failure to every waiter. Transport parse, timeout, socket,
controller-close, and supersede paths compete for one lease; only its winning
close owner may detach, close, and notify.

## Permissions and privacy

- `INTERNET`: direct TCP connection to the selected Mac.

No background-running permission is declared. The stable client identifier and
trusted-LAN host record use HarmonyOS Asset Store. The address-import credential
is held only while parsing and is not written to disk. A distinct versioned
Asset Store alias can hold a verified device credential, session-key metadata,
the durable accepted-control high-water, or a credential-free revocation
tombstone; address import never authorizes that record. See [PRIVACY.md](PRIVACY.md)
for data handling and [UPGRADE.md](UPGRADE.md) for install/migration policy.

## Known gates

Some gates are implementation gaps, not merely missing lab time. The HUKS
cryptography provider, secure-pairing controller/UI integration, authenticated
transport record layer, and Mac Host resume interoperability must exist before
MatePad evidence can close the corresponding security and resume gates. The
portable checks below only keep the source boundaries honest while that work is
incomplete.

- DevEco clean sync, ArkTS/API checker, debug/release HAP, and signature proof;
- confirmation of the commercial SDK AVCodecKit declarations and buffer APIs;
- Asset Store CRUD, XComponent surface, and H.264/HEVC hardware decode on device;
- HUKS-backed P-256/HMAC/HKDF/AES-GCM provider, secure-pairing controller/UI,
  authenticated record layer, QR camera import, and Mac interoperability;
- wheel/trackpad axis delivery and a complete physical-key USB HID map;
- Mac Host resume registry/first-message support and resume interoperability;
- controller-specific input on-device confirmation, extended stylus (eraser,
  barrel buttons, proximity/hover) on-device confirmation, audio, and Internet
  transport;
- Mac interoperability and the complete MatePad Mini acceptance/soak matrix.

Protocol v1 now defines `CAPABILITY_CONTROLLER = 26` and a lifecycle-scoped
`ControllerEvent` wire contract, and the Harmony portable protocol model now
mirrors `Capability.CONTROLLER = 26`. The production source advertises that
capability, encodes `ControllerEvent`, waits for accepted `InputAck` before
sending state, validates lifecycle bounds, and sends all-zero neutral
`DISCONNECTED` releases before active controller teardown or resume. This is a
portable/source gate only: ArkTS/API-checker, HAP, Host interoperability, and
MatePad evidence remain absent, so controller-specific input still needs device
acceptance.
Wheel-specific semantics likewise cannot be claimed from encoder code alone.
The shared Protocol v1 stylus schema now defines base CAPABILITY_STYLUS and the
additive CAPABILITY_STYLUS_EXTENDED (tool kind, barrel buttons,
contact/proximity state);
the Harmony portable core encodes both under capability gating, but the
production client advertises only CAPABILITY_STYLUS and not
CAPABILITY_STYLUS_EXTENDED until DevEco/API-checker/HAP/MatePad evidence
exists. A contacting pen can fall back to touch when the peer lacks stylus
support; eraser, proximity/hover, and barrel buttons cannot be losslessly
downgraded and are suppressed when the extended capability is not negotiated.

See the [device runbook](../../docs/runbook/harmony-matepad-mini.md) and
[Phase 4 verification record](../../docs/changes/2026-08-04-phase-4-harmony/TEST.md).
