# vibe-screen

> **Development status:** the Phase 0 macOS/Android baseline has passed its
> recorded 30-minute device acceptance run, but this remains a development
> preview rather than a stable release. The runnable application is still
> named **Telemachus**. Matching macOS and Android builds now upgrade the main
> USB/LAN session to Protocol v1 while retaining an explicit legacy fallback;
> the cross-platform offline gates pass, but Protocol v1 real-device acceptance
> is still open. Do not treat roadmap items below as shipped features.

Vibe Screen is building a low-latency Mac display and input terminal for
Android, HarmonyOS, and iOS. Today this repository contains a runnable native
macOS/Android baseline, versioned protocol contracts, reliability work, and
platform scaffolding under active development.

## Current capabilities

| Capability | Current status |
| --- | --- |
| macOS host + Android client | Builds and runs from source |
| USB transport | ADB reverse on TCP port `54321`; real-device stream verified |
| Video | ScreenCaptureKit/CGDisplayStream, VideoToolbox HEVC/H.264, MediaCodec decode |
| Touch | Android touch forwarding to macOS Accessibility/CGEvent verified |
| Recovery | Client and ADB TCP reconnect paths verified on the recorded test device |
| LAN | Experimental trusted-network mode; authenticated but not encrypted |
| Protocol v1 | Baseline host/client main-session integration and cross-platform offline gates pass; real-device acceptance pending |
| HarmonyOS/iOS/Internet | In development; not part of the current runnable baseline |

## Quick start

The shortest supported development path is USB mode:

1. Install the prerequisites and build both applications by following
   [Getting started](docs/getting-started.md).
2. Grant the macOS host Screen Recording permission. Grant Accessibility if
   touch control is required.
3. Enable Android developer options and USB debugging, then authorize the Mac.
4. Start the macOS host, configure `adb reverse tcp:54321 tcp:54321`, and
   launch the Android client with automatic USB connection enabled.
5. Confirm that Android reports an active stream and that touch moves the Mac
   pointer. See [Testing](docs/testing.md) for evidence-grade checks.

For errors, use [Troubleshooting](docs/troubleshooting.md). Security-sensitive
limitations are summarized in [Security](SECURITY.md).

## System requirements

- macOS 13 or newer; Apple silicon is locally exercised. Other Mac hardware
  does not yet have a published compatibility matrix.
- Full Xcode is required for XCTest and a complete verification run. SwiftPM
  can build the executable with compatible Command Line Tools, but that is not
  equivalent to full validation.
- Android 8.0 / API 26 or newer; JDK 17, Android SDK Platform 34, Build Tools
  34.0.0, and ADB are required to build and install the current client.
- Go 1.25.12 is used to run the pinned Buf v1.72.0 protocol checks.
- The first build requires network access for Gradle, Maven, and Go modules.

## Docs Structure

This project keeps its working knowledge under `docs/`:

```text
docs/
├── index.md              # Docs entry point and navigation
├── changes/              # One dir per change: yyyy-mm-dd-${change-name}/
│                         #   holds PRD.md, TECH.md, etc., created on demand
├── cookbook/index.md     # Reusable how-to recipes and patterns
├── pitfall/index.md      # Known traps and what to avoid
└── runbook/index.md      # Operational procedures and playbooks
```

Each change lives in its own dated folder under `docs/changes/`, named
`yyyy-mm-dd-${change-name}`. Inside, add only the documents the change needs
(`PRD.md` for product requirements, `TECH.md` for the technical design, and so
on). Keep durable knowledge flowing into `cookbook`, `pitfall`, and `runbook`.

## Workflow Skills

- `/go` — take an idea from requirements to a tested change: clarify scope,
  pick the build skills, implement the smallest complete change, and verify
  while building.
- `/ship` — take a finished change from diff to merged PR: simplify, verify,
  design-check, then commit, push, and babysit the PR.

Typical loop: scope and build with `/go`, then hand the tested diff to `/ship`.

## Product Vision

Vibe Screen turns Android, HarmonyOS, and iOS devices into low-latency displays
and input terminals for a Mac. The product is designed for a complete cross-
platform destination from the start and delivered in phases without throwaway
protocols or platform-specific architecture.

The completed product supports:

- Virtual extended displays, display mirroring, and headless Mac mini use.
- USB, local-network, and secure Internet connections.
- Touch, keyboard, mouse, stylus, controller, and peripheral input forwarding.
- HiDPI, portrait and landscape modes, adaptive resolution, and 30–120 FPS.
- Display selection, window migration, automatic reconnection, and recovery.
- End-to-end encryption, per-device authorization, and device revocation.
- Native Android, HarmonyOS NEXT, and iOS clients.

Development starts with an existing Xiaomi 12. Huawei MatePad Mini is the
primary target device for the HarmonyOS product experience.

## Architecture

### macOS host

The host is a native Swift application organized around stable module
boundaries:

- Display management creates virtual displays, configures HiDPI modes, mirrors
  existing displays, and restores windows after disconnection.
- ScreenCaptureKit captures a selected display, with a compatibility fallback
  where required.
- VideoToolbox provides hardware HEVC and H.264 encoding, with AV1 added when
  supported by host and client hardware.
- CGEvent and Accessibility provide the macOS input adapter. The runnable
  legacy session currently wires touch-derived pointer gestures only;
  keyboard, native mouse, stylus, and shortcut transport remain pending.
- Window management moves the current window or application between physical
  and virtual displays and supports headless startup.

Virtual displays currently depend on private `CGVirtualDisplay` APIs. The host
therefore also supports capturing an existing physical display and mirroring a
main display, and documents a dummy-display fallback for incompatible macOS
versions.

### Clients

- Android uses Kotlin, Compose, and MediaCodec.
- HarmonyOS NEXT uses ArkTS, ArkUI, and native hardware decoding APIs.
- iOS uses SwiftUI and VideoToolbox.
- KMP may share protocol models, connection state, configuration, and business
  rules between Android and iOS. Rendering and input remain native.
- HarmonyOS implements the same versioned protocol independently rather than
  depending on unsupported KMP platform integration.

### Protocol and transport

A versioned, capability-negotiated protocol separates product behavior from
transport. Protobuf schemas define pairing, display negotiation, video
settings, input, telemetry, heartbeat, reconnection, and errors.

Transport implementations are replaceable:

- USB uses ADB reverse and a low-latency local connection.
- Trusted LAN uses direct QUIC or WebRTC connectivity and device discovery.
- Internet access uses WebRTC P2P with STUN and falls back to TURN relay only
  when direct traversal fails.
- Control events use a reliable ordered channel while media favors current
  frames and never accumulates an unbounded queue.

Pairing uses one-time QR credentials, per-device keys, encrypted sessions,
replay protection, and explicit revocation. Relay servers forward encrypted
traffic and never terminate screen-content encryption.

## Display and Input Experience

At connection time the user can create a virtual extended display, mirror the
main or another display, attach to an existing virtual display, or enter
headless-primary-display mode.

The client can select a display, move the current window or application onto
the client display, return windows to the Mac, rotate the viewport, and change
quality, frame rate, and scaling. On disconnect, stranded windows are restored
to the primary Mac display.

Input support grows from taps, long presses, dragging, right click, scrolling,
pinch gestures, keyboard, and shortcuts to external mouse and keyboard, stylus
pressure and tilt, controllers, and customizable actions. Coordinate mapping
distinguishes device pixels, encoded-video pixels, macOS logical coordinates,
HiDPI scale, letterboxing, rotation, and safe areas.

## Open-source Baseline

- [SideScreen](https://github.com/tranvuongquocdat/SideScreen) is the primary
  MIT-licensed engineering baseline for the macOS host, Android client,
  virtual display, codecs, USB/LAN transport, and touch pipeline.
- [Telemachus](https://github.com/aaditagrawal/telemachus) supplies applicable
  MIT-licensed USB-first reliability, bounded queues, stale-frame recovery,
  telemetry, automatic reconnection, and codec fallback improvements.
- [node-mac-virtual-display](https://github.com/enfp-dev-studio/node-mac-virtual-display)
  is a non-code design reference for virtual-display identity, display
  lifecycle, and HiDPI configuration; no source was copied.
- Sunshine and Moonlight inform low-latency media and input design; Weylus
  informs touch and stylus mapping; RustDesk informs NAT traversal and relay
  operations. These are non-code design references only. No GPL/AGPL source is
  copied into this repository. Exact repositories, immutable revisions,
  licenses, and usage are recorded in [THIRD_PARTY.md](THIRD_PARTY.md).

## Delivery Plan

### Phase 0 — Sustainable baseline

**Current status: baseline acceptance passed on the recorded Nubia P0110 test
device using the legacy compatibility path, and Protocol v1 main-session
offline gates pass. Protocol v1 device interoperability, Xiaomi 12 acceptance,
full Xcode/XCTest, and two-hour leak testing remain open gates.**

Implementation status and evidence are tracked in the
[Phase 0 change docs](docs/changes/2026-08-04-phase-0-baseline/PRD.md).

- Fork and build SideScreen as the initial codebase.
- Evaluate and port the relevant Telemachus reliability improvements.
- Build the Mac host and Android client and run them on the Xiaomi 12.
- Establish versioned protocol schemas, transport interfaces, module ownership,
  automated tests, telemetry, and performance benchmarks.

The output is a maintainable product mainline rather than a disposable demo.

### Phase 1 — Complete local Android experience

**macOS host status:** display-source selection, stable existing-display
identity/fallback, experimental virtual extension/mirroring, HiDPI
configuration, window migration/recovery, validated touch-derived pointer
handling, permission onboarding, login startup, and bounded unattended
listener recovery are implemented. Pure display/input geometry, identity, and
startup policies are covered by host self-tests; system integration is not.
Private `CGVirtualDisplay` creation/capture, true mirroring, real CGEvent/AX
behavior, login-item approval, and headless reboot still require gated macOS
integration evidence. The legacy
session has no keyboard/native-mouse transport entry point, and the two-hour
device soak remains owned by the coordinated Phase 0 run.

- Deliver USB and LAN connectivity.
- Support virtual extension, mirroring, display selection, HiDPI, rotation, and
  adaptive video configuration.
- Complete touch, keyboard, mouse, and peripheral input.
- Add window migration, disconnect recovery, automatic reconnect, permission
  onboarding, and actionable errors.
- Validate sustained operation on the Xiaomi 12.

Initial targets are stable 1920×1080 or 1920×1200 at 60 FPS, sub-50 ms USB
glass-to-glass latency, sub-80 ms on a healthy LAN, sub-50 ms P95 input latency,
reconnection within three seconds, and no latency or memory growth over a
two-hour run.

### Phase 2 — Tablet productization

- Test current small Android tablets and Huawei MatePad Mini.
- Optimize the interface for 8–9 inch displays and portrait/landscape use.
- Add stylus, hardware keyboard, stand-mounted, and all-day use cases.
- Complete login startup, headless Mac mini operation, device memory, and
  unattended recovery.
- Run eight-hour stability, thermal, power, and reconnect tests.

### Phase 3 — Secure Internet access

**Current status: runnable development-preview product slice and UI; not a
stable Internet release.** The macOS and Android apps expose manual pairing,
short-lived session-profile import, direct/forced-TURN selection, product-session
state and recovery errors. The repository also includes authenticated signaling,
a coturn credential/quota control plane and pinned Compose data plane, and
production libwebrtc adapters. Control uses a reliable ordered DataChannel;
media uses an unordered zero-retransmit channel with bounded latest-frame policy.
Protocol v1 AES-256-GCM records protect both channels above WebRTC so a TURN
relay handles only ciphertext.

The macOS M150 adapter has completed real local offer/answer, ICE and
bidirectional DataChannel tests through both direct and forced coturn relay
candidate pairs. Its application record layer is wired to the Keychain-backed
identity/session lifecycle. The Android M144 adapter, AndroidKeyStore lifecycle,
REST signaling client, product-session UI and encrypted DataChannel
instrumentation now have one clean-commit Nubia P0110 device pass through direct
and forced local coturn using synthetic Protocol v1 media. This is not real
display-capture evidence.
The existing trusted-LAN path is still a separate plaintext mode and must not be
presented as Internet E2EE.

Reproduce the local Mac integration checks with:

```bash
cd baseline/MacHost
swift build -c release
.build/release/Telemachus --phase3-internet-self-test
.build/release/Telemachus --phase3-webrtc-loopback-self-test
cd ../..
python3 scripts/phase3_webrtc/run_local_e2e.py --mode direct --slice product
python3 scripts/phase3_webrtc/run_local_e2e.py --mode relay --slice product --skip-build
```

Start/configure signaling through [`services/signaling`](services/signaling/README.md)
and the coturn stack through [`deploy/phase3`](deploy/phase3/README.md). Both
services require deployment TLS, secret management, monitoring and limits
described in their runbooks; the example local profile is loopback-only.

See the [Phase 3 requirements](docs/changes/2026-08-04-phase-3-secure-internet/PRD.md),
[technical status](docs/changes/2026-08-04-phase-3-secure-internet/TECH.md),
[threat model](docs/changes/2026-08-04-phase-3-secure-internet/THREAT_MODEL.md),
[test plan](docs/changes/2026-08-04-phase-3-secure-internet/TEST.md), and
[relay operations](docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md).
The previous curated Android interop pass remains withdrawn because its source
commit and raw evidence were unavailable. A new reachable-source record retains
raw host/device/UI, service and per-ADB lease-gate evidence with a privacy scan.
Automatic account/session-authority issuance, real
encoded ScreenCaptureKit output through the device, automatic fresh-session
recovery after network handoff, public NAT/TURN deployment, cross-service
revocation propagation and soak remain release gates rather than shipped
features. Signaling and relay stores are currently single-node implementations,
and coturn usage is not yet an authoritative input to the control-plane
daily-byte ledger.

The target is roughly 80–150 ms on healthy Internet paths; relay distance and
network quality may increase it.

### Phase 4 — HarmonyOS NEXT

- Native ArkTS/ArkUI source and an independent Protocol v1 product-session core
  live in [`apps/harmony`](apps/harmony/README.md). Portable gates cover the
  real DevEco project layout, legacy-to-v1 upgrade, channel framing, formal
  control/media fixtures, display/video negotiation, strict session epochs,
  bounded media queues, and input encoding. ArkUI now wires TCP, XComponent,
  AVCodec, Asset Store, foreground suspension, and bounded fresh reconnect in
  source. No DevEco SDK was available for this record, so the repository does
  not claim ArkTS compilation, a HAP, signing, installation, hardware decode,
  secure pairing, host interoperability, or real-device behavior.
- The [Phase 4 verification record](docs/changes/2026-08-04-phase-4-harmony/TEST.md)
  tracks the remaining DevEco, host-interoperability, and MatePad Mini gates.
- HarmonyOS device acceptance must follow the
  [MatePad Mini runbook](docs/runbook/harmony-matepad-mini.md); Android results
  are never treated as HarmonyOS evidence.

### Phase 5 — iOS and advanced capabilities

- A native SwiftUI + VideoToolbox iPhone/iPad foundation now lives in
  [`apps/ios`](apps/ios/README.md): generated Protocol v1 bindings, capability
  negotiation, multi-display routing, H.264/HEVC decode, PCM audio, explicit
  clipboard, bounded verified files, epoch filtering, and native input are
  implemented and core-self-tested.
- The [Phase 5 design](docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md)
  carries additive Protocol v1 fields and client implementations for multiple
  clients/displays, HDR-to-SDR fallback, gesture-to-action mapping,
  Wake-on-LAN, and deny-wins managed configuration.
- The unsigned app has built successfully with the iOS Simulator SDK in CI.
  Simulator test execution, unsigned device archive, signing, iPhone/iPad
  installation, host interoperability, host-side advanced adapters,
  AVAudioEngine playback, HDR output, and all advanced real-device behavior
  remain separate gates; see the
  [evidence record](docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md).

## Device Strategy

The Xiaomi 12 validates decoding, protocol behavior, input, networking, and
performance before hardware is purchased. Final tablet selection emphasizes
an 8–9 inch high-density 90/120 Hz panel, Wi-Fi 6 or newer, stable low-latency
HEVC decoding, USB data support, peripherals and stylus, and acceptable thermal
and power behavior under sustained decoding.

## Engineering Principles

- Every phase extends the final architecture; no temporary protocol becomes a
  hidden dependency.
- Media, transport, protocol, display, input, and platform UI remain separate.
- Prefer the newest frame to preserving stale frame history.
- Treat disconnect and permission failure as normal product states.
- Measure glass-to-glass latency externally; do not infer it from unsynchronized
  device clocks.
- Preserve upstream attribution and verify every dependency's license before
  incorporating code.

## Build, testing, and project policies

- [Getting started and source builds](docs/getting-started.md)
- [Testing and real-device acceptance](docs/testing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture and change documentation](docs/index.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy and current security boundary](SECURITY.md)
- [Third-party sources and attribution](THIRD_PARTY.md)

Original Vibe Screen work is available under the repository-level
[MIT License](LICENSE). SideScreen/Telemachus-derived application code retains
its original MIT copyright and license notices under `baseline/` and
`third_party/telemachus/`; other dependencies retain the terms documented in
[THIRD_PARTY.md](THIRD_PARTY.md) and their bundled license files.
