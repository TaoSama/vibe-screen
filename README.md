# vibe-screen

> **Development status:** the Phase 0 macOS/Android streaming subset has passed
> recorded device acceptance runs on a Xiaomi 13 (model 2211133C, codename
> fuxi), but Phase 0 remains in progress and this is a development preview rather
> than a stable release.
> The runnable application, macOS SwiftPM product, and packaged executable now
> use **Vibe Screen**. Internal source-module and compatibility identifiers may
> retain the historical **Telemachus** identity. Matching macOS and
> Android builds now upgrade the main USB/LAN session to Protocol v1 while
> retaining an explicit legacy fallback. Protocol v1 is now exercised on device
> (display selection/switch, HiDPI capture, keyboard/scroll input,
> auto-reconnect) and the cross-platform offline gates pass. Protocol v1
> clipboard forwarding is implemented for explicit Android/macOS text transfers
> and covered by offline gates, but real Android ClipboardManager <-> macOS
> NSPasteboard USB/LAN E2E evidence remains open. A two-hour soak has run with a
> stable stream, but the host resident-memory no-growth gate (tracked in
> [the Host RSS investigation](docs/changes/2026-08-10-host-rss-growth/TECH.md))
> and a native-pointer HID confirmation remain open. Do not treat roadmap items
> below as shipped features.

Vibe Screen is building a low-latency Mac display and input terminal for
Android, HarmonyOS, and iOS. Today this repository contains a runnable native
macOS/Android baseline, versioned protocol contracts, reliability work, and
platform scaffolding under active development.

## Current capabilities

| Capability | Current status |
| --- | --- |
| macOS host + Android client | Builds and runs from source |
| macOS Host compatibility | Compatibility matrix gate is open. Apple silicon has local exercise, historical device evidence, and published blocked `macos-hardware-compatibility-gate` summaries for Mac16,8 current-base readiness; no passing row exists because stable signing/TCC, source-bound Host provenance, full macOS checks, and runtime stream/input/reconnect evidence are missing. Intel Macs, additional Apple silicon models, macOS builds, and display topologies still need exact-row passing evidence before support claims |
| USB transport | ADB reverse on TCP port `54321`; real-device stream verified |
| Video | ScreenCaptureKit/CGDisplayStream, VideoToolbox HEVC/H.264 encoding, and Android MediaCodec HEVC/H.264 decode. AV1 is a later-phase/backlog codec, not a current Host/device stream codec: Protocol v1 only reserves CODEC_AV1, the current Host does not advertise AV1, Android does not offer AV1 in product sessions, and no AV1 real-stream Host/device acceptance is recorded; see the [AV1 codec capability gate](docs/changes/2026-08-21-av1-codec-capability/TEST.md) record |
| Audio | Protocol v1 USB/LAN now wires a capability-gated PCM S16LE microphone-capture path from the macOS Host to Android `AudioTrack`, with offline Host/Android protocol, packetization, playback, and LAN secure-record tests. This is not system-output capture. The 2026-08-30 Nubia P0110/pacific current-base refresh remains blocked because the installed Host is not a current-source stable-signed Microphone/TCC-ready bundle, no Host listener was observed, and retained logs show no `CAPABILITY_AUDIO`, accepted `AudioConfig`, channel `3`, `AudioTrack` write, or playback-confirmation evidence |
| Display | Physical-display selection, private-API HiDPI virtual extended display (4000x2400 physical / 2000x1200 logical), in-place display switching, and screen mirroring (with graceful fallback to direct main-display capture) verified on device |
| Touch | Android touch forwarding to macOS Accessibility/CGEvent verified. Tap, long-press right-click, long-press drag, two-finger scroll, and pinch reached the real Host path in an opt-in Xiaomi 13 acceptance run; that run exposed a shared-CGEventSource modifier leak, now fixed with an isolated synthetic-modifier source and focused test coverage. The Xiaomi 13/fuxi fixed-binary rerun is still blocked by Accessibility authorization for that exact Host binary. A stable-signed fixed-binary rerun has passed on the Nubia P0110/pacific Android 16 substitute, closing only the general Android substitute rerun gate and keeping the device identity distinct from Xiaomi 13/fuxi evidence; physical-finger/manual UX remains a separate gate |
| Input (keyboard/mouse/peripheral) | Touch, touch-derived pointer, keyboard, and mouse-wheel scroll forwarding to macOS CGEvent verified on device; native mouse pointer move/click is wired end to end but pending a physical-HID-mouse confirmation. Protocol v1 stylus pressure, signed two-axis tilt, eraser, two barrel buttons, and hover are independently capability-gated across USB, LAN, and Internet, with old-peer touch fallback and mixed finger/stylus routing. The latest Nubia P0110/pacific stylus preflight exposes pressure/tilt-capable `goodix_stylus_input` hardware but remains blocked because no physical drawing, stable signed/TCC-ready Host evidence, Host stylus injection excerpt, or visible macOS drawing-app output was captured. Controller protocol models, Android mapping/state, Android production event forwarding, Host state machines, and Mac virtual-gamepad injection are offline-tested; controller runtime acceptance still requires a physical Android controller plus an identity-signed Host build with the approved virtual HID entitlement, observed Host availability, visible Mac-side controller response, and neutral release on disconnect; see the [controller runtime acceptance gate](docs/changes/2026-08-19-controller-runtime-acceptance/TEST.md). A generic peripheral-input admission framework is defined offline and fails closed for unsupported kinds; it does not claim support for any concrete peripheral hardware. Physical-stylus drawing-app confirmation, controller runtime acceptance, and other peripherals remain open |
| Clipboard | Protocol v1 text clipboard forwarding is wired for Android <-> macOS with explicit send/get/overwrite actions, strict UTF-8 `text/plain`, SHA-256/origin/session-epoch validation, deny-wins managed-policy gating, and a 1 MiB negotiated size ceiling. Android JVM tests, Protocol v1 fixtures, and the Mac Protocol v1 self-test pass on current main. The 2026-08-27 Nubia P0110 current-base attempt adds a fail-closed clipboard E2E gate and local Android ClipboardManager smoke evidence, but real Android ClipboardManager <-> macOS NSPasteboard USB/LAN E2E remains open because Host readiness and real transport prerequisites are blocked and no bidirectional product transfer record exists |
| File transfer | Protocol v1 includes a bounded single-file transfer path for Android/macOS USB/LAN sessions with explicit sender action, receiver approval, safe basenames, negotiated limits, chunk ordering, session-epoch checks, SHA-256 verification, deny-wins policy handling, and cancel/disconnect cleanup covered by offline and Android smoke tests. A dedicated fail-closed Phase 0 gate now tracks real Android/macOS product E2E readiness; the 2026-08-29 Nubia P0110 current-base record keeps it blocked because Host readiness is not satisfied and no bidirectional product transfer evidence exists |
| Recovery | Client and ADB TCP reconnect paths verified on the recorded test device |
| LAN | Experimental trusted-network mode; current macOS/Android peers negotiate per-session AES-256-GCM application records with nonce/replay protection for control and media. Old peers require an explicit plaintext legacy fallback and must not be reported as encrypted. Current-worktree real-device LAN stream/reconnect evidence remains open; the 2026-08-29 Nubia P0110/pacific preflight was still blocked by device Wi-Fi association/route and Host stable-signing prerequisites |
| Protocol v1 | Host/client main-session verified on device: capability negotiation, display list/selection, stable physical/virtual round trips, HiDPI capture, keyboard/scroll input, auto-reconnect, client-driven video preferences, and client-invoked focused-window migration/return. Window return and disconnect recovery restore the original Mac frame. Quality/FPS/bitrate changes and AUTO reset renegotiate in place on the Xiaomi 13 with a bumped config epoch, no host restart, and no transport teardown. Clipboard and file transfer are implemented and offline-tested, but their real device/system service or product E2E gates are still open. Cross-platform offline gates pass. A two-hour soak has run with a stable stream, but the [host RSS no-growth gate](docs/changes/2026-08-10-host-rss-growth/TECH.md) and native-pointer HID confirmation remain open |
| iOS trusted LAN | Core client interoperates with the baseline MacHost in a real two-process localhost loopback using the secure-record path by default; the loopback harness asks the Host to bind port `0` and passes the selected localhost port to the client. Explicit plaintext legacy fallback is regression-tested separately. This is readiness evidence only: Simulator UI, signed iPhone/iPad device acceptance, and real-network LAN acceptance remain gated |
| HarmonyOS/Internet | In development; not part of the current runnable baseline. HarmonyOS has a portable authenticated-record contract verifier aligned with the macOS/Android AES-256-GCM record format, nonce/replay rules, session epochs, and explicit legacy-fallback semantics, but the production Harmony TCP path is still plaintext until HUKS, DevEco/HAP, Host interoperability, and MatePad evidence exist |

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

- macOS 13 or newer is the source/runtime floor. Apple silicon is locally
  exercised, but the published macOS Host compatibility matrix remains open
  until rows pass the
  [macOS Host compatibility gate](docs/runbook/macos-host-compatibility.md).
  Intel Macs, additional Apple silicon model families, specific macOS builds,
  built-in/external/multi-display, dummy/headless, and Screen Sharing display
  setups must each be recorded as exact evidence rows before they are claimed as
  supported.
- Full Xcode is required for XCTest and a complete verification run. SwiftPM
  can build the executable with compatible Command Line Tools, but that is not
  equivalent to full validation.
- Android 8.0 / API 26 or newer; JDK 17, Android SDK Platform 34, Build Tools
  34.0.0, and ADB are required to build and install the current client.
- Verified Android devices: Xiaomi 13 (model 2211133C, codename fuxi) is the
  primary named evidence source; Nubia P0110 (codename pacific, Android 16 /
  API 36) is an acceptable substitute for general Android acceptance. Both are Android
  handsets, but evidence must always record the exact manufacturer, model,
  codename, and OS version of the device that produced it, and Nubia P0110
  results must not be relabeled as Xiaomi 13/fuxi evidence.
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

## Product Vision (planned)

Vibe Screen turns Android, HarmonyOS, and iOS devices into low-latency displays
and input terminals for a Mac. The product is designed for a complete cross-
platform destination from the start and delivered in phases without throwaway
protocols or platform-specific architecture.

The target product is planned to support the following outcomes. This list is
the roadmap destination, not a statement that each item is shipped today:

- Virtual extended displays, display mirroring, and headless Mac mini use.
- USB, local-network, and secure Internet connections.
- Touch, keyboard, mouse, stylus, controller, and peripheral input forwarding.
- HiDPI, portrait and landscape modes, adaptive resolution, and 30–120 FPS.
- Display selection, window migration, automatic reconnection, and recovery.
- End-to-end encryption, per-device authorization, and device revocation.
- Native Android, HarmonyOS NEXT, and iOS clients.

Current Android real-device evidence comes from a Xiaomi 13 (model 2211133C,
codename fuxi) running Android 16 over USB, plus evidence from a Nubia
P0110/pacific on the same Android version. The connected Nubia P0110/pacific
may be used as an Android-device substitute for general USB/LAN streaming,
protocol, UI, decoder, and reconnect acceptance work; evidence still records the exact
manufacturer, model, codename, and OS version, and hardware-specific claims
remain tied to the device that produced them. On the Xiaomi 13 the streaming
baseline is verified: stable ~60 FPS, hardware HEVC decode at roughly 6 ms,
touch-to-pointer control, reconnect recovery, and Protocol v1
display-selection negotiation. On 2026-08-08 physical<->virtual display
switching was also verified on device through the client display dropdown with
no session teardown. A two-hour soak (2026-08-09) then held a stable stream
(240 samples, mean 59.94 FPS) with stable client memory, but host resident
memory grew about 18.3 MB, so the two-hour no-growth gate stays open.
Huawei MatePad Mini is the primary planned target device for the HarmonyOS product experience; no
HarmonyOS device result is implied here.

## Target Architecture (planned)

This section describes the intended end-state architecture. Implemented and
verified subsets, plus their open gates, are listed under Delivery Plan below.

### macOS host

The host is a native Swift application organized around stable module
boundaries:

- Display management creates virtual displays, configures HiDPI modes, mirrors
  existing displays, and restores windows after disconnection.
- ScreenCaptureKit captures a selected display, with a compatibility fallback
  where required.
- VideoToolbox provides hardware HEVC and H.264 encoding. AV1 remains planned:
  Protocol v1 reserves CODEC_AV1 for a future AV1-capable Host, but today the
  Host has no AV1 encoder/packaging path, never advertises AV1, and offline
  admission tests only verify fail-closed fallback to H.264/HEVC. No AV1
  real-stream device acceptance is recorded.
- CGEvent and Accessibility provide the macOS keyboard, pointer, touch-derived
  gesture, and stylus input adapters. Protocol v1 wires keyboard, native
  pointer/scroll, pen and eraser pressure/tilt, barrel buttons, hover/proximity
  state, and Host-side controller event handling. The Protocol v1 contract also
  reserves a generic peripheral-input admission framework that is disabled by
  default and rejects unsupported kinds without reaching native injection. The
  Android client now routes gamepad/joystick key and motion events through the
  production Protocol v1 session when controller capability is negotiated,
  with mapper, session, and protocol behavior covered offline. Host controller
  events feed a virtual gamepad through `IOHIDUserDevice` when an
  identity-signed build has the approved virtual HID entitlement. Physical HID
  mouse, stylus, and controller runtime behavior still require their respective
  device confirmations.
- Window management moves the current window or application between physical
  and virtual displays and supports headless startup.

Virtual displays currently depend on private `CGVirtualDisplay` APIs. The host
therefore also supports capturing an existing physical display and mirroring a
main display, and documents a dummy-display fallback for incompatible macOS
versions.

### Clients

- Android currently uses Kotlin, XML Views/ViewBinding, and MediaCodec;
  Compose remains the target direction for UI work.
- HarmonyOS NEXT uses ArkTS, ArkUI, and native hardware decoding APIs.
- iOS uses SwiftUI and VideoToolbox.
- Android and iOS currently use native Kotlin and Swift implementations backed
  by the same Protocol v1 schemas and a fail-closed shared-model contract under
  [`contracts/shared-models`](contracts/shared-models/v1/manifest.json). KMP
  remains a possible future home for protocol models, connection state,
  configuration, and business rules once shared runtime ownership is justified.
  Rendering and input remain native.
- HarmonyOS implements the same versioned protocol independently rather than
  depending on unsupported KMP platform integration.

### Protocol and transport

A versioned, capability-negotiated protocol separates product behavior from
transport. Protobuf schemas define pairing, display negotiation, video
settings, input, telemetry, heartbeat, reconnection, and errors.

Transport implementations are replaceable:

- USB uses ADB reverse and a low-latency local connection.
- Trusted LAN uses direct local connectivity and device discovery; current
  macOS/Android peers protect the admitted TCP session with per-session
  AES-256-GCM application records, while legacy plaintext fallback is explicit
  and separately reported.
- Internet access uses WebRTC P2P with STUN and falls back to TURN relay only
  when direct traversal fails.
- Control events use a reliable ordered channel while media favors current
  frames and never accumulates an unbounded queue.

Pairing uses one-time QR credentials, per-device keys, encrypted sessions,
replay protection, and explicit revocation. Relay servers forward encrypted
traffic and never terminate screen-content encryption.

## Target Display and Input Experience (planned)

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

- [Telemachus](https://github.com/aaditagrawal/telemachus) is the direct
  MIT-licensed source import for selected macOS and Android application code,
  including its USB-first reliability, bounded queues, stale-frame recovery,
  telemetry, automatic reconnection, and codec fallback work.
- [SideScreen](https://github.com/tranvuongquocdat/SideScreen) is the upstream
  MIT-licensed foundation inherited indirectly through Telemachus for virtual
  display, capture, encoding, ADB/TCP, Android decoding, pairing, and touch.
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

**Current status: baseline acceptance passed on the recorded Nubia P0110/pacific
test device using the legacy compatibility path, and Protocol v1 main-session
offline gates pass. The 2026-08-13 main baseline at commit `244c5a2` passed
GitHub Actions Phase 0
[run 31710918927](https://github.com/TaoSama/vibe-screen/actions/runs/31710918927),
iOS engineering
[run 31710918942](https://github.com/TaoSama/vibe-screen/actions/runs/31710918942),
and HarmonyOS portable
[run 31710918961](https://github.com/TaoSama/vibe-screen/actions/runs/31710918961).
These iOS and HarmonyOS jobs do not constitute real-device evidence. A historical
2026-08-09 Phase 0 run at `c639caa` executed 312 MacHost tests with 1 skipped and
0 failures.
An earlier 2026-08-06 CI run on `4c2e908fe31af4c187684991301e163371444eab`
recorded a 202-test MacHost suite; the count has since grown as tests were
added. Protocol v1 real-device interoperability is now verified on a Xiaomi 13,
but a published macOS Host hardware compatibility matrix, a valid two-hour host
RSS no-growth run, native-pointer HID confirmation, and controller runtime
acceptance remain open gates.**

On 2026-08-08 a Xiaomi 13 (model 2211133C, codename fuxi, Android 16, USB)
recorded the first Xiaomi 13 streaming evidence: a stale-Surface
reconnect-loop fix, then stable 60 FPS with zero dropped frames, hardware HEVC
decode at roughly 6 ms, touch-to-pointer control, reconnect recovery, and a
30-minute soak (mean 59.95 FPS, zero drops). Host resident memory grew over
that 30-minute window. Protocol v1 display-selection negotiation is verified on
device. On 2026-08-08 the physical<->virtual<->physical display switch was
verified end to end on the Xiaomi 13 through the client display dropdown: the
switch renegotiates video in place with a bumped config epoch and no
INVALID_MEDIA_HEADER, INVALID_STATE, or session teardown, dropping only the
expected transient reconfiguration frames before returning to 60 FPS with zero
drops. A subsequent 2026-08-09 two-hour soak held a stable stream (240 samples,
mean 59.94 FPS) with stable client memory, but host RSS grew about 18.3 MB with
a +96.5 KiB/min second-half slope, so the two-hour no-growth gate stays open;
see [docs/changes/2026-08-10-host-rss-growth/TECH.md](docs/changes/2026-08-10-host-rss-growth/TECH.md)
and the v2 soak evidence at
[docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-09-xiaomi-fuxi-soak2h-v2](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-09-xiaomi-fuxi-soak2h-v2/README.md).
Current-source rerun readiness remains blocked by stable-signing, installed
Host integrity/provenance, TCC, listener, virtual-HID entitlement, and full
Xcode/XCTest prerequisites; see
[docs/changes/2026-08-10-host-rss-growth/evidence/2026-08-29-current-base-host-rss-failclosed-readiness](docs/changes/2026-08-10-host-rss-growth/evidence/2026-08-29-current-base-host-rss-failclosed-readiness/README.md).
The Xiaomi 13 baseline evidence is recorded under
[docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-08-xiaomi12-fuxi-redacted](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-08-xiaomi12-fuxi-redacted/README.md). The display-switch round-trip and offline self-tests are recorded under
[docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-08-fuxi-display-switch](docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-08-fuxi-display-switch/roundtrip-verification.md).

Implementation status and evidence are tracked in the
[Phase 0 change docs](docs/changes/2026-08-04-phase-0-baseline/PRD.md).
The Phase 0 stable-release decision is owned by the aggregate manifest in
[docs/changes/2026-08-22-phase0-stable-release-aggregate](docs/changes/2026-08-22-phase0-stable-release-aggregate/README.md).
Do not use shipped, complete, closed, or stable wording for Phase 0 until
`make phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1` reports
`can_mark_phase0_stable_release=true`.

Android TCP connection ownership is now enforced by a standalone JVM transport
module with dependency-direction and resource-lifecycle contract tests.
`StreamClient` now delegates local product-session lifecycle state, Protocol v1
action dispatch, side-effect owner checks for file-transfer and wake-host flows,
input envelope routing, and media-frame routing to focused boundary owners with
offline contract coverage. This is still not completion of Phase 0 module
ownership: broader protocol/session ownership, full file-transfer and wake-host
product ownership, decoder/renderer ownership, and UI/product session
boundaries are still being extracted.

- Fork and build SideScreen as the initial codebase.
- Evaluate and port the relevant Telemachus reliability improvements.
- Build the Mac host and Android client and complete the Android device
  acceptance gate. Xiaomi 13/fuxi remains a named evidence source, while Nubia
  P0110/pacific and other qualifying Android devices may substitute for
  general Android acceptance when their identity and limits are recorded.
- Establish versioned protocol schemas, transport interfaces, module ownership,
  automated tests, telemetry, and performance benchmarks.

The output is a maintainable product mainline rather than a disposable demo.

### Phase 1 — Complete local Android experience

**macOS host status:** display-source selection, stable existing-display
identity/fallback, on-device-verified virtual extension and HiDPI
configuration, on-device screen mirroring, window migration/recovery, validated
touch-derived pointer
handling, permission onboarding, login startup, and bounded unattended
listener recovery are implemented. Pure display/input geometry, identity, and
startup policies are covered by host self-tests; at main commit `c639caa` on
2026-08-09, the MacHost XCTest suite ran in CI with 312 tests executed, 1
skipped, and 0 failures. System integration is not thereby proved.
Private `CGVirtualDisplay` creation/capture and HiDPI are now verified on
device: switching to the extended display creates a real virtual display that
macOS reports as 4000x2400 physical / 2000x1200 logical (2x Retina) and streams
at 60 FPS with zero drops (see Phase 1). Screen mirroring is verified on
device: because macOS 26.4.1 rejects hardware-mirroring a physical display onto
a virtual display (CGError 1001), mirror mode now degrades gracefully to direct
main-display capture, so the client shows the Mac's main screen at 60 FPS with
zero drops instead of looping unattended recovery (see Phase 1). Login-item
approval and headless reboot still require gated macOS integration evidence;
the shared Host readiness preflight now records login/headless setup blockers,
but those diagnostics do not prove reboot launch, headless capture, Android
rendering, or unattended recovery.
Real CGEvent
injection under Accessibility is now exercised on device for keyboard and
mouse-wheel scroll (see Phase 1). The legacy compatibility session
is intentionally a touch-compatible fallback and has no keyboard/native-mouse
entry point; keyboard and native pointer move/primary click remain Protocol
v1-only capability-gated features, so old peers fail closed instead of receiving
unnegotiated input bytes. Keyboard and scroll are on-device verified through
Protocol v1, while native pointer move/click remain pending a physical HID
mouse. A two-hour device soak has run (2026-08-09) with a stable stream, but the
host RSS no-growth gate is still open (see Phase 0).

Protocol v1 now exposes the Host's fixed `move-window` and `return-windows`
actions through an opt-in Android control-bar menu. On the Xiaomi 13, a focused
TextEdit window moved from `(181,102)` to `(1846,179)` inside the online
2000x1200 virtual display, returned to its exact original frame, and was also
restored automatically after the Android process disconnected. The same pass
fixed catalog/binding arrival order, kept one managed virtual-display identity
stable across physical<->virtual round trips, and prevented cold extended-mode
startup from looping on a benign WindowServer `CGError 1001`. See the
[window-action evidence](docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-10-xiaomi13-window-actions/README.md).

The Android client shows a compact, centered, tap-to-reveal control capsule
that opens a display dropdown menu, opens settings, and disconnects; the
dropdown lists each available display with the active one checked, and the
picker collapses entirely on single-display sessions to avoid mis-taps. The
Xiaomi 13 also verifies the client-local Fit/Fill and Follow Mac/90/180/270
viewport matrix, including inverse touch mapping at the corners and center,
with host rotation fixed at zero. Rotated physical/virtual host-display
acceptance remains separate and now has a focused offline evidence-summary
gate documented in the Phase 1 test record; that gate still requires a fresh
real-device host-rotation pass for physical and virtual displays at
90/180/270 degrees before the acceptance item can close. The current-base owner
record keeps the aggregate gate blocked until retained real-device evidence
satisfies those criteria. The
host advertises its online physical displays plus, when the private
virtual-display API is available, one selectable virtual extended display so a
single-monitor Mac can still offer a second display to switch to; selecting it
switches the capture source in place and renegotiates video with a bumped
config epoch. Beyond in-place display renegotiation, the client can also send
manual video preferences (bitrate/quality/frame-rate) to the host on the active
session and reset them to AUTO, and the host applies them in place; this
client-driven video configuration path is verified on the Xiaomi 13. Smooth,
Balanced, Sharp, and Auto map to the host's LOW, MEDIUM, HIGH, and ULTRALOW
encoder settings. The retained device log proves in-place 2, 5, and 50 Mbps at
60 FPS updates with no host PID change; a client-only restart also preserves
the last applied 50 Mbps / 60 FPS configuration in the new session's first
epoch. Other preset/FPS combinations remain covered by offline protocol and
encoder tests rather than claimed as retained device evidence. The
dropdown-selector capsule's in-place
physical<->virtual<->physical capture switch is now verified on the Xiaomi 13
with no session teardown: two full round-trips held 60 FPS with zero dropped
frames and no client disconnect after a host-side fix that stopped a single
client display request from emitting two StartDisplayResponse frames (the
second of which arrived in the STREAMING state and previously forced an
INVALID_PEER_MESSAGE teardown on the virtual->physical leg). Keyboard and
mouse-wheel scroll input are now verified end to end on the Xiaomi 13: forwarded
keys arrive as correctly mapped host CGEvent key injections (A/B/C and arrow
keys, press/release paired) and a forwarded VSCROLL arrives as a host scroll
injection, which also confirms the host holds Accessibility permission. Native
mouse pointer move and click share the same forwarding path and source check as
the verified scroll but still want one confirmation with a physical HID mouse
attached to the phone, since synthetic adb pointer motion does not deliver as a
hover event.

The generic peripheral-input framework is now defined as a Protocol v1
capability and additive `PeripheralEvent` payload, with Android dispatch and
Host admission boundaries covered by offline tests. Production peers do not
advertise it by default, and the Host returns `InputAck(accepted=false,
rejection_reason="unsupported_peripheral_kind")` for every kind until a
concrete hardware path is implemented and accepted. This does not close any
physical peripheral gate.

An opt-in Xiaomi 13 instrumentation pass also drove the production touch path
for tap, long-press right-click, long-press drag, two-finger scroll, and pinch.
It reproduced a shared-`CGEventSource` bug where pinch's Command modifier leaked
into later ordinary pointer events. Pinch now uses a private synthetic-modifier
event source, preserving legitimate physical modifiers on ordinary pointer
events, with focused isolation coverage. A stable-signed fixed-binary rerun on
the Xiaomi 13/fuxi reached Protocol v1 streaming but remained blocked because
Accessibility was not authorized for that exact Host binary. A later
stable-signed fixed-binary rerun on the Nubia P0110/pacific Android substitute
passed the same opt-in gesture matrix with Host gesture logs and listen-only
macOS event-tap evidence for tap, right click, drag, plain scroll,
Command-modified pinch zoom, and post-pinch plain-tap modifier isolation. That
closes the fixed-binary touch rerun gate only for a general Android substitute;
it does not relabel the result as Xiaomi 13/fuxi evidence, and the
native HID mouse confirmation plus physical-finger/manual UX pass remain
separate. See the
[touch-gesture verification record](docs/changes/2026-08-13-xiaomi13-touch-gestures/TEST.md),
the
[Xiaomi 13 blocked rerun evidence](docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-16-xiaomi13-fuxi-fixed-binary-blocked/README.md),
and the
[P0110 passed rerun evidence](docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-20-p0110-pacific-fixed-binary-rerun/README.md).

Android and MacHost also expose explicit Protocol v1 `text/plain` clipboard
transfer for USB/LAN sessions: each side sends only an offer until the receiver
chooses to fetch, direct content requires an overwrite confirmation, trusted LAN
shows a plaintext-risk confirmation before body transfer, and both peers enforce
the negotiated 1 MiB ceiling plus origin, session epoch, UTF-8 and SHA-256
checks. This path is covered by Android JVM tests, protocol fixtures, MacHost
clipboard XCTest sources, and the Mac Protocol v1 executable self-test; the
MacHost clipboard XCTest run itself is blocked in this local Command Line Tools
environment. The 2026-08-27 Nubia P0110 current-base run records a blocked
`clipboard-e2e-gate` verdict with local Android ClipboardManager smoke passing,
but no bidirectional system-pasteboard product transfer. The real Android
ClipboardManager <-> macOS NSPasteboard USB/LAN E2E gate remains open pending a
signed Host/device run; see the
[clipboard verification record](docs/changes/2026-08-16-android-macos-clipboard/TEST.md)
and the blocked E2E evidence under
[2026-08-27-nubia-p0110-clipboard-e2e-current-base-blocked](docs/changes/2026-08-16-android-macos-clipboard/evidence/2026-08-27-nubia-p0110-clipboard-e2e-current-base-blocked/README.md).

- Deliver USB and LAN connectivity.
- Support virtual extension, mirroring, display selection, HiDPI, rotation, and
  manual video configuration (bitrate/quality/frame-rate presets). Network-driven
  automatic adaptation is a later-phase goal, not part of the Phase 1 USB/LAN path.
- Protocol v1 USB/LAN now has an offline-tested, capability-gated PCM S16LE
  microphone-capture path from macOS Host to Android playback; real-device USB
  and trusted-LAN audio playback evidence remains open. The 2026-08-30 Nubia
  P0110/pacific current-base owner refresh is blocked before audio negotiation:
  the read-only collector retained the exact device identity and existing ADB
  reverse state, but no Host listener was observed, the installed Host bundle
  did not prove current-source stable signing plus Microphone/TCC readiness, and
  retained logs show no `CAPABILITY_AUDIO`, accepted `AudioConfig`, channel `3`
  audio packets, Android `AudioTrack` writes, or playback confirmation.
- Complete touch, keyboard, mouse, and peripheral input.
- Harden window migration/return, disconnect recovery, automatic reconnect,
  permission onboarding, and actionable errors across supported system states.
  The current actionable-error owner matrix is now covered by an offline
  drift gate for Android SessionFailureKind coverage plus macOS Host
  permission/startup/capture states; this is not a replacement for retained
  device evidence across the full state matrix. A current-base P0110/pacific
  owner record now binds the README-facing actionable-error states to a
  fail-closed real-device evidence gate and remains blocked for Screen
  Recording denial, Accessibility denial/limited state, ADB reverse missing,
  USB disconnected, LAN route unavailable, TCP `54321` unavailable, and stale
  epoch/session errors until each state has retained evidence.
- Validate sustained operation on the active Android acceptance device. Xiaomi
  13/fuxi remains a named evidence source, while Nubia P0110/pacific and other
  qualifying Android devices may substitute for general Android
  sustained-operation checks when the evidence records their real identity.

Initial targets are stable 1920×1080 or 1920×1200 at 60 FPS, sub-50 ms USB
glass-to-glass latency, sub-80 ms on a healthy LAN, sub-50 ms P95 input latency,
reconnection within three seconds, and no latency or memory growth over a
two-hour run. USB and LAN glass-to-glass latency gates require external-camera
evidence, while the input-latency gate requires external-camera evidence or a
documented synchronized-clock setup with a reviewable sub-5 ms total error
budget. The gate profiles are `usb-glass-to-glass-sub50`,
`lan-glass-to-glass-sub80`, and `input-p95-sub50`; host and client telemetry
are diagnostic only and cannot close these gates. As of the 2026-08-28 Nubia
P0110/pacific reconnect timing current-base owner record, the formal
`phase1-reconnect-within-3s` summary remains blocked before any disruption
scenario. The P0110 kept the USB reverse mapping, but no Host TCP `54321`
listener was observed. Source-bound stable Host evidence is still blocked by
the missing configured `Vibe Screen Dev` signing identity, failed installed
Host codesign inspection, missing source commit/tree provenance, unverified
read-only TCC authorization, missing virtual-HID entitlement, and unverified
login/headless readiness. That record has `can_close_timing_gate=false`
and does not close the three-second reconnect gate; see
[the current-base blocked reconnect record](docs/changes/2026-08-21-phase1-reconnect-timing/evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked/README.md).
As of the 2026-08-28 Nubia P0110/pacific latency preflight, the toolchain has
formal manifest/checker coverage for external-camera packages and
synchronized-clock input packages,
with profile-specific retained-artifact checks for USB, LAN, and physical-input
claims. No raw camera package, annotated latency samples, or synchronized-clock
proof from a real physical-input run is available in the repository. All three
latency gates therefore remain open; see
[the current-base blocked readiness record](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-28-nubia-p0110-latency-current-base-blocked/README.md).

### Phase 2 — Tablet productization

- Test current small Android tablets and Huawei MatePad Mini.
- Optimize the interface for 8–9 inch displays and portrait/landscape use.
- Validate physical stylus and hardware-keyboard workflows, then add
  stand-mounted and all-day use cases.
- Complete login startup, headless Mac mini operation, device memory, and
  unattended recovery.
- Run eight-hour stability, thermal, power, and reconnect tests.

The Android settings surface now includes a responsive sustained-use status for
battery level, charging state, power-saver mode, and platform thermal severity.
Observation is owned by the foreground Activity lifecycle, deduplicates updates,
and rejects callbacks after stop; 600dp portrait/landscape layout coverage keeps
the status readable in small-tablet and resized-window configurations. This is an
offline product slice, not thermal or power acceptance: 8–9 inch hardware,
stand-mounted charging, background/foreground recovery, and the eight-hour run
remain device gates. The evidence tooling now includes a Phase 2 tablet
manifest to declare device identity, stand/charging setup, thresholds, memory
sampling, and planned recovery scenarios before a future run; a package-aware
tablet gate; an independent fail-closed device-memory verifier for Android PSS,
Host RSS, charging/full-state, and thermal-status coverage during the 8h soak;
an independent fail-closed device-environment verifier for stand-mounted
charging, controlled thermal-load recovery, and power-source stability; and a
bundle preflight that checks physical 8-9 inch tablet identity,
portrait/landscape UI screenshots, physical stylus, hardware keyboard, recovery,
thermal/power, and eight-hour soak artifacts. The package-aware tablet gate now
requires a passing device-environment summary before it can close. These tools
reject phone substitutes such as Nubia P0110/pacific/Android 16 for formal
tablet acceptance and report missing evidence as blocked or insufficient. A
current-base aggregate owner report now records one owner per open Phase 2
workstream and marks stale or duplicate PRs without closing any child gate. The
login-startup/headless Mac
mini row now has a passive current-base verifier that consumes retained real
macOS evidence for identity signing, TCC, Login Items approval, reboot/login
launch, capturable physical/dummy/headless or Screen Sharing display, bounded
unattended recovery, window restoration, and operator remote-access fallback.
It remains fail-closed until those machine-bound artifacts exist. The
hardware-keyboard workflow has a dedicated current-base owner and a
schema-backed fail-closed summary that requires real external, non-virtual
Android hardware keyboard input, an active selected-display stream, Protocol v1
keyboard and USB HID modifier negotiation, focus/IME boundary evidence, retained
Host key-injection or acknowledgement/CGEvent logs, modifier cleanup, and a
visible Mac result. Stand-mounted charging stability, controlled thermal-load behavior,
power stability, login startup, headless Mac mini acceptance, hardware-keyboard
workflow acceptance, and the physical 8-9 inch tablet run all remain open. The
latest P0110/pacific device-environment readiness record captures the real
device identity and fail-closed battery, power, and thermal snapshots, but it is
not a gate pass because the device is a phone substitute and no stand-mounted
tablet setup, controlled thermal-load recovery, or eight-hour window was
available. The latest P0110/pacific hardware-keyboard current-base readiness
record captures the real device identity and fails closed on current
`origin/main` because no external Android-attached keyboard or stable
signed/TCC-ready Host was available; a Host listener alone is not enough, and
this is not a gate pass. The latest P0110/pacific tablet sustained-use
current-base preflight captures the device as nubia P0110 / pacific / Android
16 / SDK 36 and keeps the Phase 2 tablet gate blocked because the device is an
`android_substitute` phone, APK identity was not supplied for a formal run, no
Host PID or Host telemetry JSONL was provided, no physical 8-9 inch tablet
evidence exists, and no eight-hour soak gate artifact was produced. The current
aggregate owner report consumes that blocked keyboard summary and blocked
tablet preflight, and still reports `can_close_readme_phase2_gates=false`; see
[the P0110 soak preflight](docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-phase2-soak-preflight-current-base/README.md)
and
[the aggregate owner record](docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-phase2-tablet-current-base-owner/README.md).
The latest macOS login-startup/headless current-base record captures a Host
listener and startup defaults on an Apple silicon development Mac, but it fails
closed because the installed Host lacks current-source provenance, read-only TCC
verification is unavailable, Launch at Login remains unverified on the default
non-`sfltool` path, the Virtual HID entitlement is absent, and no reboot/login,
headless display, client-render, bounded recovery, or window-restore artifact
was collected. The retained readiness JSON records
`sfltool_dumpbtm_was_run=false`, and start/end `pgrep -x sfltool || true`
checks were empty. It therefore does not close login startup or headless Mac
mini acceptance; see
[the blocked current-base record](docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-macos-login-headless-current-base-blocked/README.md).
See the [Phase 2 productization slice](docs/changes/2026-08-14-phase-2-tablet-productization/PRD.md)
and the [tablet acceptance runbook](docs/changes/2026-08-14-phase-2-tablet-productization/RUNBOOK.md).

### Phase 3 — Secure Internet access

**Current status: runnable development-preview product slice and UI; not a
stable Internet release.** The macOS and Android apps expose manual pairing,
short-lived session-profile import, direct/forced-TURN selection, product-session
state and recovery errors. The repository also includes authenticated signaling
with explicit memory/PostgreSQL store backends, a coturn credential/quota control
plane and pinned Compose data plane, and production libwebrtc adapters.
Control uses a reliable ordered DataChannel;
media uses an unordered zero-retransmit channel with bounded latest-frame policy.
Protocol v1 AES-256-GCM records protect both channels above WebRTC so a TURN
relay handles only ciphertext.
QR pairing has a current-base offline fail-closed slice: Android accepts only the
canonical `vibescreen://pair?v=1&o=` envelope before decoding one-time material,
macOS consumes an offer on the first redemption attempt even when the request is
invalid, and Android refuses imported leases whose host signature is not bound to
the previously verified pairing identity. The local lease codec also requires a
bounded unsigned `expires_at` compatibility field and rewrites it to the issuer
TTL before signing. The archived local current-base evidence marks the related
macOS XCTest filters blocked where the selected Command Line Tools environment
could not compile XCTest, so those local artifacts must not be treated as an
executed macOS XCTest pass. This does not prove production account/session-
authority profile issuance or a real camera QR pairing round trip.

Main commit `73be8c0` hardens this slice at the source level: the Internet
session lease issuer validates the pairing binding before reading identity
credentials, the durable session epoch advances atomically through a single
pairing-scoped transaction, the cross-process security tests are stabilized
against pipe-buffer deadlocks, and the Android decoder-config publish now fails
closed when it cannot publish. These are offline-verified source changes; the
release gates below are unchanged.
The current worktree adds an admin/operator Authority session-profile issuance
primitive for already registered devices, signaling adoption of those sessions
after successful role authorization, and Mac signing of the exact
Authority-supplied epoch. This is local control-plane evidence only; Mac/Android
automatic profile invocation remains open.
A 2026-08-20 local readiness record at commit `18a6ea70` covers the same
release boundary: protocol checks, Phase 3 security/service/static tests, local
Authority container gating, relay coturn data-plane scripts, and direct plus
forced-local-coturn synthetic product E2E all passed on that source. The
synthetic E2E record is explicitly loopback-only, uses a synthetic Protocol v1
peer, and records no Android UI, real screen capture, or public Internet path;
the release gates below remain unchanged.
The current worktree strengthens the local product E2E media payload from fixed
synthetic strings to real VideoToolbox-generated HEVC keyframe and delta frames
over the production WebRTC media DataChannel, still with a synthetic Protocol
v1 peer and synthetic pixel-buffer input. That check does not start
ScreenCaptureKit or CGDisplayStream and is not Android MediaCodec, visible UI,
or public-Internet evidence.
No current-worktree Phase 3 Internet pass is recorded for real
ScreenCaptureKit/CGDisplayStream output reaching Android MediaCodec on a real
device over a public route; the continuity preflight remains blocked until
public-route, identity-signed Host, Screen Recording, capture, encoder, and
decoder-output evidence are all present. A dedicated current-base child gate now
also requires that continuity result to match clean current `HEAD` and include a
retained Android screenshot or recording with an operator note proving decoded
Mac desktop content is visible in the Android UI; missing UI evidence keeps the
gate blocked.
The current-base advanced DataChannel owner is also fail-closed: it tracks
audio playback, explicit clipboard transfer, and bounded file transfer over the
Internet WebRTC control/audio/bulk DataChannels as product flows. Existing
USB/LAN audio, clipboard, and file-transfer evidence plus raw audio/bulk
Internet channel hook tests remain readiness only; without retained, hashed real
macOS+Android public-Internet product-flow artifacts, this child gate stays
blocked.
The current-base package-level checker
`vibescreen_evidence.phase3_internet_release_gate` now makes the Internet
soak/latency boundary executable: it requires public-path and deployed remote
TURN proof, external-camera direct and relay latency raw samples, a complete
two-hour mixed-route soak, real capture-to-MediaCodec continuity, handoff,
revocation, and packet-capture confidentiality. Missing hardware, signing, TCC,
network, raw samples, or soak artifacts are reported as blocked or insufficient
and do not close the release gate.

The macOS M150 adapter has completed real local offer/answer, ICE and
bidirectional DataChannel tests through both direct and forced coturn relay
candidate pairs. Its application record layer is wired to the Keychain-backed
identity/session lifecycle. A historical, source-bound 2026-08-05 record at
commit `597518f948075e396352bc353afcec01a30303f3` covered one Nubia
P0110/pacific run for the Android M144 adapter, AndroidKeyStore lifecycle, REST
signaling client, product-session UI, and encrypted DataChannel instrumentation
through direct and forced local coturn using synthetic Protocol v1 media. That
record is not current-source evidence, is not the current-base replacement
owner, and must not be extrapolated to the current working tree or later commits.
It is not real ScreenCaptureKit, Android MediaCodec, or display-capture evidence.
The trusted-LAN path is still separate from Internet mode. Its current
macOS/Android peers use application records on the admitted private-network TCP
session, while explicit legacy fallback remains plaintext and must not be
presented as encrypted or as Internet E2EE evidence.
The Android/macOS clipboard implementation currently belongs to the USB/LAN
Protocol v1 session path and has only offline/self-test evidence on current
main; no public-Internet, WebRTC DataChannel, real Android ClipboardManager, or
real macOS NSPasteboard E2E result is claimed for clipboard.

Adaptive video profiles are scoped to the WebRTC Internet transport only; USB and
trusted-LAN sessions keep manual client-driven bitrate/quality/frame-rate presets
and do not run the adaptive policy. The host `AdaptiveMediaPolicy` and Android
`AdaptiveVideoPolicy` use fast-drop/slow-rise hysteresis (downgrade after two
poor samples, upgrade after four or five good samples) with neutral samples
resetting the counters so boundary jitter does not oscillate. The host clamps
every adaptive proposal to the user-configured baseline upper bound, applies it
to the live encoder/capture first, then sends a Protocol v1 `VideoConfig` with a
bumped `config_epoch`; all outbound media stays gated until the client
acknowledges. A client rejection triggers a host rollback to
the last acknowledged configuration; a host-apply, ACK, or host-rollback timeout
fails the session closed. Offline tests also cover even dimensions without
upscaling, latest-proposal-wins queuing, rotation serialization, stale
owner/generation rejection, and retry after local or peer rejection. The
production host composition wires the
encoder/capture application callback, but this path is verified only through
offline build and unit/self-tests, not against real capture output. A dedicated
current-base child gate now exists for retained adaptive-media fluctuation
reports; it stays fail-closed unless the run proves public-Internet WebRTC,
controlled real impairment, fast-drop/slow-rise, bitrate/FPS/config-epoch
changes, `VideoConfig` ACK/keyframe resume, and transport continuity without
static latency fixtures, local loopback, synthetic media, or relabeled device
identity. Not proved:
public Internet, real remote TURN (local loopback and forced local coturn are
not public-Internet or real-deployment evidence), real ScreenCaptureKit-to-Android
device decoder continuity, real network fluctuation, network handoff, and soak.
The repository also includes a fail-closed composition gate for the full Internet
soak boundary. `make phase3-internet-soak-manifest` predeclares the production
TURN, signaling, relay, Authority, TLS, secret-source, remote-peer, artifact, and
handoff inputs. `make phase3-internet-soak-gate` then requires matching public
remote TURN, real media-continuity, network-handoff, revocation-propagation, and
two-hour mixed-route soak reports. Missing deployment material or missing report
families produce `blocked` evidence rather than a pass.

Current Phase 3 release-gate gaps are tracked as explicit open evidence rows:

| Gate | Current missing proof | Minimum acceptable evidence |
| --- | --- | --- |
| Public Internet direct path | No real public-network direct WebRTC candidate pair | A clean-source Mac/Android run over non-local Internet showing a selected `direct(...)` candidate pair and decoded stream |
| Remote TURN relay path | No deployed remote TURN path; local coturn is loopback-only | A forced relay run through a real remote TURN deployment showing selected `relay(...)` candidate pair, service identity, and redacted allocation logs |
| Real capture to Android media | No ScreenCaptureKit/CGDisplayStream frames encoded through Internet WebRTC into Android MediaCodec | Correlated host capture/VideoToolbox counters, Protocol v1 media epochs, Android MediaCodec first output, FPS/drops, and artifact hashes |
| Network handoff recovery | No Wi-Fi/cellular/VPN handoff on the Internet path | Handoff event log with controlled impairment parameters, direct/relay route before and after, ICE restart or fresh session, old-session closure, increased session epoch, stale-epoch rejection, stream pause/resume, and bounded recovery duration |
| Cross-service revocation | Active PeerConnection/TURN allocation termination is not production-proven | Signed revocation evidence showing signaling denial, active session disconnect, TURN allocation disconnect, and direct/relay reconnect rejection |
| Packet-capture confidentiality | No public-path direct/relay packet capture review | Redacted capture notes proving no plaintext media, input, credentials, or full secrets across direct and relay paths |
| External-camera latency | No direct/relay Internet glass-to-glass samples | External-camera method, raw samples, p95 direct/relay results, and error-budget notes |
| Two-hour mixed-route soak | No Internet soak with route changes | Two-hour direct+relay+network-change run with controlled impairment parameters, bounded queue/RSS/latency, nonce-reuse check, relay bytes, thermal/battery, and privacy scan |

Use `scripts/phase3/release_gate_manifest.py --print-matrix` to emit the current
open matrix and `scripts/phase3/release_gate_manifest.py <manifest.json>` to
fail closed on future curated evidence that omits these necessary fields. This
schema is only a preflight for release evidence; passing it still requires human
review of the raw artifacts and does not itself close the Phase 3 release gate.
If prerequisites are missing, use
`scripts/phase3/network_recovery_blocked_evidence.py` to write a blocked
readiness package; its generated manifest is expected to fail the pass verifier.

Reproduce the local Mac integration checks with:

```bash
cd baseline/MacHost
swift build -c release
".build/release/Vibe Screen" --phase3-real-media-self-test
".build/release/Vibe Screen" --phase3-internet-self-test
".build/release/Vibe Screen" --phase3-webrtc-loopback-self-test
cd ../..
python3 scripts/phase3_webrtc/run_local_e2e.py --mode direct --slice product
python3 scripts/phase3_webrtc/run_local_e2e.py --mode relay --slice product --skip-build
```

Start/configure signaling through [`services/signaling`](services/signaling/README.md)
and the coturn stack through [`deploy/phase3`](deploy/phase3/README.md). The
Phase 3 production-shaped Compose profile includes signaling, relay, and coturn
services, but it still requires an external TLS/private-ingress layer, managed
PostgreSQL, secret management, monitoring, and limits described in their
runbooks; the example local profile is loopback-only.
Authority-mode signaling long polls reauthorize in bounded refresh windows so a
revoked role token fails closed before the full client poll timeout. Relay now
sends both credential issuance and non-duplicate usage ingestion through
Authority admission in `production_authority` mode, requires an
`allocation_id`, and persists admitted allocations to a strict local registry
for coturn operator tooling. `scripts/phase3/coturn_reconcile.py` provides a
bounded operator helper that accepts a trusted structured coturn allocation
snapshot, submits it to Authority's reconciliation API, and requires an external
active-allocation disconnect executor for unauthorized, conflicting, or revoked
source allocations. `scripts/phase3/coturn_allocation_exporter.py`,
`scripts/phase3/coturn_reconciliation_loop.py`, and
`scripts/phase3/coturn_disconnect_executor.py` provide the current-base local
product slice for the exporter/reconciliation/executor boundary. The exporter
adapts a reviewed structured collector snapshot into the strict Authority
snapshot shape, the bounded loop persists consecutive missing-allocation state,
and the executor consumes `coturn_reconcile.py`'s active-allocation disconnect
environment to remove an allocation from a machine-readable local state file and
write a non-secret audit record. `scripts/phase3/coturn_cli_control.py` can
export registry-matched coturn CLI sessions and issue loopback
`cs <session-id>` disconnect commands when an operator supplies a precise
registry and CLI connection. These are local contract and operator-slice
artifacts, not a deployed coturn exporter, production scheduler, live coturn
allocation teardown, or proof of public Internet enforcement.
`scripts/phase3/revocation_propagation_verifier.py` adds a fail-closed evidence
contract for the full revocation chain: Authority tombstone, active signaling
session rejection, future and stale TURN credential rejection, active coturn
allocation disconnect, and post-revocation data-plane denial. It returns a
blocked result when live allocation teardown or packet-denial evidence is absent;
it does not close the production gate by itself.

See the [Phase 3 requirements](docs/changes/2026-08-04-phase-3-secure-internet/PRD.md),
[technical status](docs/changes/2026-08-04-phase-3-secure-internet/TECH.md),
[threat model](docs/changes/2026-08-04-phase-3-secure-internet/THREAT_MODEL.md),
[test plan](docs/changes/2026-08-04-phase-3-secure-internet/TEST.md), and
[relay operations](docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md).
The previous curated Android interop pass remains withdrawn because its source
commit and raw evidence were unavailable. The separate 2026-08-05
reachable-source record retains raw host/device/UI, service and per-ADB
lease-gate evidence with a privacy scan, without extending its result to current
code. Current-base replacement is owned by the fail-closed Android interop gate
in the Phase 3 test plan: it must either produce a current-source `blocked`
result or accept fresh current-source P0110 evidence through the requested proof
profile. Dated local readiness evidence is recorded under
[`docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness`](docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness/README.md).
The current-base QR pairing blocked record covers only offline Swift/Kotlin
fixture and fail-closed checks; it records that no production TLS/public-Internet
deployment or real Android camera QR scan was available in this environment.
Current fail-closed Internet soak evidence is recorded under
[`docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-26-internet-soak-current-base-blocked`](docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-26-internet-soak-current-base-blocked/README.md).
Mac/Android automatic invocation of Authority session-profile issuance, real QR
scan request/acceptance, real encoded ScreenCaptureKit output through the
device, automatic fresh-session
recovery after network handoff, public NAT/TURN deployment, cross-service
revocation propagation and soak remain release gates rather than shipped
features. Signaling now has a PostgreSQL-backed routing store with local
cross-instance contract coverage. Signaling and relay stores now use shared
PostgreSQL state for multi-instance correctness paths; signaling long-poll
waiter slots are backed by connection-scoped database leases so a replacement
instance can reclaim a slot after the failed instance loses its PostgreSQL
backend. These do not prove a production multi-replica rollout, cross-replica
rate limiting, load-balancer behavior, or multi-region consistency. Relay credential admission is wired to Authority,
relay non-duplicate usage admission is also checked by Authority, and Authority
can debit accepted coturn usage into the control-plane daily-byte ledger.
The structured coturn exporter, bounded reconciliation loop, and local
active-allocation disconnect executor are now covered as a current-base product
slice, including stale-allocation observation, Authority-reported revoked
allocations, and quota-closed allocation remediation contracts. The coturn CLI
control helper can map registry entries to exact local coturn CLI sessions, but
production deployment of these components, real coturn/provider allocation
termination, and production end-to-end enforcement remain release gates.
A local revocation propagation verifier now fixes the required evidence schema
for Authority audit visibility, signaling long-poll rejection, future and
post-revocation same-allocation relay credential rejection, active allocation disconnect, stale
credential rejection, and post-revocation traffic denial; the current blocked
evidence still lacks the live coturn/data-plane deployment observations.
The script scripts/phase3/production_e2e_enforcement.py is the explicit owner
and evidence contract for closing that final production enforcement gate. It
fails closed when real deployed configuration is absent, when
authority/signaling/coturn policy values diverge, or when local loopback and
synthetic-peer evidence is presented as public production E2E. The current
blocked record is retained under
[2026-08-25-production-e2e-enforcement-current-base-blocked](docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-25-production-e2e-enforcement-current-base-blocked/README.md).

The formal Internet latency gate is `internet-glass-to-glass-sub150` for direct
and relay public-Internet routes. It requires external-camera raw samples plus
public-route provenance; local loopback, forced local coturn, host/client
telemetry, and missing raw samples cannot close it. The target is roughly
80-150 ms on healthy Internet paths; relay distance and network quality may
increase it.

### Phase 4 — HarmonyOS NEXT

- Native ArkTS/ArkUI source and an independent Protocol v1 product-session core
  live in [`apps/harmony`](apps/harmony/README.md). Portable gates cover the
  real DevEco project layout, legacy-to-v1 upgrade, channel framing, formal
  control/media fixtures, display/video negotiation, strict session epochs,
  bounded media queues, input encoding (including shared Protocol v1 base and
  extended stylus encoding and capability gating), fail-closed resume results,
  a portable pairing/credential/replay/revocation core, and a transport-neutral
  authenticated-record verifier that reproduces the macOS/Android AES-256-GCM
  fixture for control, media, audio, and bulk channels. That verifier covers
  directional key derivation, `session_id` hashing, strict session/key epochs,
  channel-bound nonces, replay windows, wrong-key/tamper rejection, and explicit
  legacy plaintext fallback marking. The secure-pairing portable path now
  requires an explicit Harmony HUKS-backed profile before it can emit
  `PairingRequest`, persists only version-2 credential records carrying that
  profile, and rejects legacy records, non-HUKS providers, replayed control
  records, expired pairing results, and revoked credentials fail-closed. ArkUI
  now wires TCP, XComponent, AVCodec, Asset Store, foreground suspension, and
  bounded reconnect in source. The production Harmony TCP path still uses the
  explicit plaintext Protocol v1 upgrade and must not be reported as encrypted
  until the HUKS-backed provider and transport integration pass DevEco, Host,
  and MatePad gates. The portable core encodes both base stylus (position,
  pressure, tilt)
  and the extended stylus fields (tool kind, barrel buttons, contact/proximity
  state) under capability negotiation, but the production Harmony client
  advertises only CAPABILITY_STYLUS and not CAPABILITY_STYLUS_EXTENDED until
  DevEco/API-checker/HAP/MatePad evidence exists. A contacting pen can fall back
  to touch when the peer lacks stylus support; eraser, proximity/hover, and
  barrel buttons cannot be losslessly downgraded and are suppressed when the
  extended capability is not negotiated. The portable Harmony core now also
  advertises CAPABILITY_CONTROLLER, encodes ControllerEvent field 66, waits for
  Host InputAck acceptance before sending controller state, validates lifecycle
  bounds, and releases active controllers through all-zero neutral DISCONNECTED
  events before teardown or resume. No DevEco SDK was available for this
  record, so the repository does not claim ArkTS compilation, a HAP, signing,
  installation, hardware decode, production HUKS API behavior, authenticated
  transport, resume-capable Host interoperability, or real-device behavior.
  The HUKS secure-pairing evidence verifier and blocked manifest are recorded
  under
  [`docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-huks-secure-pairing-blocked`](docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-huks-secure-pairing-blocked/README.md).
  The authenticated-record portable-verifier blocked record is recorded under
  [`docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-harmony-lan-secure-record-blocked`](docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-harmony-lan-secure-record-blocked/README.md).
- The [Phase 4 verification record](docs/changes/2026-08-04-phase-4-harmony/TEST.md)
  tracks the remaining DevEco, host-interoperability, and MatePad Mini gates.
- Gate ownership is explicit while those records are open: the HarmonyOS client
  owns H.264/HEVC hardware-decode readiness and device evidence, with Mac Host
  video negotiation as dependency evidence; the Mac Host and HarmonyOS client
  jointly own resume-capable interoperability, with the Host responsible for
  resume registry/session behavior and HarmonyOS responsible for lifecycle,
  network-recovery, and old-epoch rejection evidence.
- HarmonyOS device acceptance must follow the
  [MatePad Mini runbook](docs/runbook/harmony-matepad-mini.md); Android results
  are never treated as HarmonyOS evidence.
- The read-only `make harmony-readiness EVIDENCE_DIR=...` preflight now records
  DevEco/OHPM/Hvigor/HDC, signed-HAP checksum/signature metadata, Protocol v1
  Host build identity, and MatePad Mini HDC-target readiness into
  `harmony-readiness.json`. It fails closed while any prerequisite is missing
  and is not HAP, installation, streaming, secure-pairing, soak, latency, or
  MatePad Mini acceptance evidence.
- The read-only `make harmony-current-base-gate EVIDENCE_DIR=...` aggregate
  owner gate now binds the Phase 4 README owner surface for DevEco build,
  signed-HAP install, H.264/HEVC hardware decode, HUKS secure pairing,
  authenticated transport, resume-capable Host interoperability, and MatePad
  Mini acceptance to `harmony-readiness.json` plus
  `harmony-device-gates.json`. It reports `blocked` until DevEco, a signed HAP,
  a MatePad Mini target, a Protocol v1 Host build, and every required device
  gate evidence package are all present; Android, portable-only, or blocked
  readiness records cannot close those owner gates. The
  [current-base gate audit](docs/changes/2026-08-04-phase-4-harmony/CURRENT_BASE_AUDIT.md)
  records the open PR owner map and marks this gate as the current-base
  aggregate owner path. The latest current-base rerun remains blocked and is
  archived at
  [2026-08-29-current-base-harmony-blocked](docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-29-current-base-harmony-blocked/README.md).
- `make harmony-matepad-acceptance EVIDENCE_DIR=...` validates the final
  redacted MatePad Mini acceptance package after readiness, strict device-gate,
  and current-base owner manifests are present. Its `--write-blocked` dry run
  can archive missing-device readiness, but blocked output is not real-device
  acceptance evidence and cannot close the HarmonyOS gate.

### Phase 5 — iOS and advanced capabilities

- A native SwiftUI + VideoToolbox iPhone/iPad foundation now lives in
  [`apps/ios`](apps/ios/README.md): generated Protocol v1 bindings, capability
  negotiation, multi-display routing, H.264/HEVC decode, AV1 protocol-enum
  recognition with explicit rejection because no AV1 decoder is implemented,
  PCM audio, explicit
  clipboard, bounded verified files, epoch filtering, native touch plus
  hardware-keyboard/hover-pointer UI, and bounded trusted-LAN reconnect are
  implemented and covered by offline/core self-tests; no iOS device evidence is
  recorded yet.
- The trusted-LAN iOS Core client now uses the secure-record loopback path by
  default to interoperate with the baseline MacHost in a localhost loopback;
  the harness asks the Host to bind port `0` and passes the selected port to
  the iOS client:
  authenticated `SSWA`/`SSWR` admission establishes AES-256-GCM `VSLS`/`VSLR`
  records, and the `0D` upgrade runs inside that record stream into the
  Protocol v1 main session. Hello/capability negotiation, display list/start,
  video-config acknowledgement, media framing, ping/pong, display/stream-targeted
  touch, protocol error, and disconnect are covered by a real two-process
  loopback gate. Explicit plaintext legacy fallback is regression-tested
  separately and must not be reported as encrypted evidence. The loopback is not
  signed app/device, Simulator UI, hardware VideoToolbox, or real-network LAN
  acceptance evidence.
- The iOS app serializes every outbound control envelope through a
  session-owner-scoped FIFO, rejects old connection/decoder deliveries, gates
  each stream on its sent video-config acknowledgement and exact media epochs,
  fragments, and frame sequence, and closes half-open sessions after a bounded
  Pong miss budget.
- The Android and macOS Internet record layers now derive separate directional
  keys, durable nonce counters, and replay domains for control, media, audio,
  and bulk. A shared fixed-vector fixture covers all four AES-256-GCM record
  channels and legacy-compatible key rotation. Audio/bulk WebRTC transport
  channels are now wired into the macOS and Android Internet product sessions
  as raw Protocol v1 records with owner-scoped admission and bounded backlog
  behavior. Audio capture/playback, clipboard/file-transfer product flows over
  those channels, and public-network end-to-end behavior remain unproved and are
  now tracked by a dedicated fail-closed current-base gate.
- The macOS Host and Android client now share a transport-neutral, bounded
  single-file transfer domain over Protocol v1 for the existing USB/LAN TCP
  session. File offers require explicit receiver approval and default to reject;
  both sides enforce safe basenames, deny-wins managed policy and resource
  limits, ordered chunks, per-chunk and final SHA-256, session-epoch checks,
  progress-driven backpressure, and cancel/disconnect cleanup. This is offline
  and self-test evidence only: no Android real-device file-transfer acceptance,
  public-Internet run, or WebRTC bulk DataChannel path is claimed.
- The macOS Host and Android client now wire authenticated Protocol v1
  WakeHostRequest messages to real UDP Wake-on-LAN magic-packet senders. Wake
  remains default-deny, is advertised only when an HMAC authorizer is available,
  and validates key ID, nonce, expiry, signature, session device identity, and
  broadcast target before sending. This is offline and loopback test evidence
  only: sleeping-Mac wake, router broadcast behavior, NIC firmware settings, and
  cross-subnet delivery remain real-device gates. The current-base WakeHost
  evidence owner is #199 after being rebased onto the #225 baseline; it provides
  a fail-closed evidence gate for the latest mainline instead of treating the
  offline magic-packet baseline as a hardware pass.
- Managed configuration now has an offline-verified deny-wins product-policy
  model across macOS Host, Android, and iOS: Protocol v1 carries complete
  restriction results, local parse errors fail closed, allowlists intersect,
  and `DeniedHosts` wins over `AllowedHosts`. This is source/unit/self-test
  evidence only; real Apple MDM profile delivery and managed App Configuration
  injection remain open gates.
- The [Phase 5 design](docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md)
  carries additive Protocol v1 fields and client implementations for multiple
  clients/displays, HDR-to-SDR fallback, gesture-to-action mapping,
  Wake-on-LAN, and deny-wins managed configuration.
- The host-side advanced adapter readiness owner is now the
  `phase5-host-advanced-adapters-gate`. It records the minimum iOS/MacHost
  adapter matrix for multi-client/display allocation, audio, clipboard, file
  transfer, HDR/color, host actions, wake, and managed policy, and verifies
  that unsupported Host adapters stay unadvertised or explicitly policy-gated.
  This is a source/readiness gate only, not iOS device or advanced product-flow
  acceptance.
- The iOS HDR output / EDR rendering gate now has a dedicated fail-closed
  current-base owner, `ios-hdr-edr-gate`, for retained iPhone/iPad HDR evidence.
  The current iOS renderer still advertises SDR only and has no HDR/EDR output
  pass; SDR fallback, Simulator, unsigned archive, Android, and macOS fallback
  evidence remain readiness inputs only.
- The iOS app-signing prerequisite now has its own dedicated fail-closed
  current-base owner, `ios-app-signing-readiness-gate`. The retained blocked
  owner record is
  [2026-08-29-ios-signing-current-base-blocked](docs/changes/2026-08-04-phase-5-ios-advanced/evidence/2026-08-29-ios-signing-current-base-blocked/README.md):
  it requires sanitized Team ID and provisioning profile UUID digests, a unique
  bundle ID, sanitized non-ad-hoc codesign identity digest, physical-device UDID
  hashes, signed-app entitlement relationship checks, signed artifact SHA-256,
  and archive/profile/entitlements artifacts before the
  aggregate signing row can unblock. It still cannot close install, launch,
  VideoToolbox, input, reconnect, audio, HDR, or full iOS device acceptance.
- The read-only `make phase5-multi-client-current-base-gate EVIDENCE_DIR=...`
  owner gate now keeps the planned multiple-clients/displays capability
  fail-closed on current base. It requires retained evidence for two or more
  simultaneous clients, distinct session/display stream ownership, transport
  isolation, Host route binding, input target isolation, a defined capture
  ownership model, and macOS/Android/iOS/Harmony owner status. Single-client
  display selection or display-switch evidence remains separate and cannot
  close this gate.
- The current-base aggregate gate records per-gate owner PRs while it remains
  fail-closed. PR #290 owns the aggregate and device-acceptance validator, #251
  owns iOS hardware VideoToolbox readiness, and #253 owns Host advanced-adapter
  readiness. Passing status under a mismatched owner, Simulator output, unsigned
  archives, MacHost loopback, and Android evidence cannot close those iOS
  hardware or Host-adapter gates.
- The unsigned app has built successfully with the iOS Simulator SDK in CI.
  The iPhone Simulator XCTest and unsigned archive gates pass on the current
  interoperability commit. The hardware VideoToolbox behavior gate now has a
  fail-closed offline owner: `make ios-videotoolbox-readiness` summarizes
  `ios-videotoolbox-observations.json` into a schema-checked readiness result
  that distinguishes Simulator, unsigned archive, physical iPhone, and physical
  iPad records. Simulator and unsigned archive summaries remain blocked by
  construction; closing Phase 5 still requires reviewed passing records from
  both real iPhone and iPad hardware. Signing, iPhone/iPad installation,
  host-side advanced adapters, AVAudioEngine playback,
  HDR output, audio/bulk product flows over Internet DataChannels, native input
  behavior, reconnect behavior, and all advanced real-device behavior remain
  separate device gates. Android results are never treated as iOS evidence; see
  the [evidence record](docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md)
  and [iOS device acceptance runbook](docs/runbook/ios-device-acceptance.md).
- The current owner for the iOS native-input behavior gate is
  `phase5-ios-native-input-behavior`. Its read-only readiness/evidence summary
  is `make ios-native-input-gate EVIDENCE_DIR=...`, which consumes a sanitized
  `ios-native-input-observations.json` from scheduled iPhone and iPad runs. A
  pass requires real signed iOS app sessions, selected display/stream routing,
  touch tap/drag, hardware keyboard press/release plus modifier cleanup, hover
  or pointer accessory movement, Host acknowledgements, and retained iOS/Host
  logs for both device classes. Simulator, Android, and offline test results
  remain readiness-only and
  cannot close this gate.

## Device Strategy

The Android acceptance device can be any currently connected Android handset or
tablet that meets the runtime requirements and is explicitly identified in the
evidence. Xiaomi 13 (model 2211133C, codename fuxi) remains the primary named
evidence source, and Nubia P0110/pacific is an acceptable substitute
for general Android decoding, protocol behavior, input, networking, UI, and
performance validation. When running against the connected P0110, use
`adb -s <device-serial> ...` with the locally attached serial and record the
device as Nubia P0110/pacific Android evidence. Do not relabel one device as another: device-specific
evidence and hardware-gated claims, such as native HID, stylus, thermal, panel,
or SoC decode behavior, remain scoped to the exact device that produced them.
For Phase 3 Android Internet replacement evidence, only a fresh current-source
P0110 run may use that substitute path; historical synthetic-media records do not
close current Android Internet decoding or release gates.
As of 2026-08-10 the Xiaomi 13 has recorded verified streaming, touch, keyboard
and mouse-wheel input, reconnect, a 30-minute soak, display-selection
negotiation, the physical<->virtual<->physical display-switch round-trip, and
HiDPI private-API virtual-display creation/capture (4000x2400 physical / 2000x1200
logical) over USB, plus in-place quality/FPS/bitrate video preferences and
client-invoked focused-window migration/return with disconnect recovery. A
client-local Fit/Fill and four-direction rotation/input matrix is also verified
with host rotation zero; rotated host-display acceptance remains open, with the
recording checklist and offline evidence-summary gate in the Phase 1 test
record and current-base owner tooling. A
2026-08-28 P0110/pacific current-base tooling refresh kept that gate blocked:
the device identity, USB reverse, installed packages, and local TCP `54321`
listener were present, but the Host stable-signing/TCC/source-provenance
preflight was unavailable, so no physical or virtual 90/180/270 display stream
or inverse-touch matrix was claimed. A
post-fix 30-minute preference run completed 60/60 connected samples with no
reconnect or sample error; it is a short regression run, not a replacement for
the formal gate. A 2026-08-09 two-hour soak held a stable stream but left the
host RSS no-growth gate open (about +18.3 MB); stable self-signing now keeps the
host's Screen Recording grant across rebuilds and relaunches.
The viewport/input and window-action records are retained under
[2026-08-10-xiaomi13-viewport-input](docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-10-xiaomi13-viewport-input/README.md)
and
[2026-08-10-xiaomi13-window-actions](docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-10-xiaomi13-window-actions/README.md).
Earlier Android evidence also comes from Nubia
P0110/pacific. The 2026-08-20 P0110/pacific run closed the fixed stable-signed
binary touch-gesture rerun gate for a general Android substitute. Future
P0110/pacific runs may close additional general Android gates only when their
evidence satisfies the same pass criteria. A 2026-08-23 current-base recheck at
`5069404` on the connected P0110 installed the current APK and restored the
`tcp:54321` USB reverse mapping, but it did not prove stream, reconnect,
decoder, or app-lifecycle behavior: the supported stable-signing Host preflight
was blocked by a missing `Vibe Screen Dev` codesigning identity, the ad-hoc
current app did not expose a `54321` listener, and the read-only USB smoke helper
returned `insufficient`. That record is retained under
[2026-08-23-nubia-p0110-usb-current-base](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-23-nubia-p0110-usb-current-base/README.md).
A 2026-08-24 follow-up on the same P0110 observed an already-running
`/Applications/Vibe Screen.app` USB/loopback session at PR head `d2b9698f`: the
Host listened only on `<network-detail>:54321`, ADB reverse provided
`UsbFfs tcp:54321 tcp:54321`, and the read-only USB smoke collector returned
`pass` with current-process `stream_stats`, first output frame, and continuing
decoder counters. That record is retained under
[2026-08-24-p0110-usb-loopback-running-window](docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-24-p0110-usb-loopback-running-window/README.md)
and is USB/loopback evidence only: it does not close trusted-LAN stream or
reconnect, two-hour RSS, external-camera latency, native-pointer HID, stylus,
controller, or long-soak gates. Final tablet
selection emphasizes
an 8–9 inch high-density 90/120 Hz panel, Wi-Fi 6 or newer, stable low-latency
HEVC decoding, USB data support, peripherals and stylus, and acceptable thermal
and power behavior under sustained decoding.

## macOS Host Strategy

Host compatibility claims are evidence-row scoped. A row is accepted only when a
named owner records the implementation path, exact Mac model, CPU architecture,
macOS version and build, display topology, capture backend, VideoToolbox path,
Host build/signing/TCC state, a real Protocol v1 stream, display selection,
physical/current-main capture, virtual-display or fallback behavior, mirror or
fallback behavior, input smoke, reconnect, and retained artifacts, then runs the
`macos-hardware-compatibility-gate` summary. CI `macos-15` build/test output is
source-level evidence only and cannot close a real hardware row by itself.

Until those rows exist, README support language stays limited to the current
source requirements and recorded local exercise. Intel Macs, untested macOS
minor releases, other Apple silicon model families, external-display layouts,
multi-display layouts, dummy/headless setups, and Screen Sharing setups remain
open compatibility gates. The required process and JSON input are documented in
[the macOS Host compatibility runbook](docs/runbook/macos-host-compatibility.md).

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
