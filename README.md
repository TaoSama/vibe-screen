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
> auto-reconnect) and the cross-platform offline gates pass. A two-hour soak has
> run with a stable stream, but the host resident-memory no-growth gate and a
> native-pointer HID confirmation remain open. Do not treat roadmap items below
> as shipped features.

Vibe Screen is building a low-latency Mac display and input terminal for
Android, HarmonyOS, and iOS. Today this repository contains a runnable native
macOS/Android baseline, versioned protocol contracts, reliability work, and
platform scaffolding under active development.

## Current capabilities

| Capability | Current status |
| --- | --- |
| macOS host + Android client | Builds and runs from source |
| USB transport | ADB reverse on TCP port `54321`; real-device stream verified |
| Video | ScreenCaptureKit/CGDisplayStream, VideoToolbox HEVC/H.264, MediaCodec decode. AV1 is protocol-enumerated and fail-closed in offline codec-admission tests, but no AV1 real-stream Host/device acceptance is recorded |
| Display | Physical-display selection, private-API HiDPI virtual extended display (4000x2400 physical / 2000x1200 logical), in-place display switching, and screen mirroring (with graceful fallback to direct main-display capture) verified on device |
| Touch | Android touch forwarding to macOS Accessibility/CGEvent verified. Tap, long-press right-click, long-press drag, two-finger scroll, and pinch reached the real Host path in an opt-in Xiaomi 13 acceptance run; that run exposed a shared-CGEventSource modifier leak, now fixed with an isolated synthetic-modifier source and focused test coverage. A stable-signed fixed-binary rerun has now passed on the Nubia P0110/pacific Android substitute, with the device identity kept distinct from Xiaomi 13/fuxi evidence |
| Input (keyboard/mouse/peripheral) | Touch, touch-derived pointer, keyboard, and mouse-wheel scroll forwarding to macOS CGEvent verified on device; native mouse pointer move/click is wired end to end but pending a physical-HID-mouse confirmation. Protocol v1 stylus pressure, signed two-axis tilt, eraser, two barrel buttons, and hover are independently capability-gated across USB, LAN, and Internet, with old-peer touch fallback and mixed finger/stylus routing. Controller protocol models, Android mapping/state, Android production event forwarding, Host state machines, and Mac virtual-gamepad injection are offline-tested; controller runtime acceptance still requires a physical Android controller plus an identity-signed Host build with the approved virtual HID entitlement, observed Host availability, visible Mac-side controller response, and neutral release on disconnect. Physical-stylus drawing-app confirmation, controller runtime acceptance, and other peripherals remain open |
| Recovery | Client and ADB TCP reconnect paths verified on the recorded test device |
| LAN | Experimental trusted-network mode; current macOS/Android peers negotiate per-session AES-256-GCM application records with nonce/replay protection for control and media. Old peers require an explicit plaintext legacy fallback and must not be reported as encrypted. Current-worktree real-device LAN stream/reconnect evidence remains open; the 2026-08-20 Nubia P0110 preflight was blocked by device Wi-Fi and Host signing prerequisites |
| Protocol v1 | Host/client main-session verified on device: capability negotiation, display list/selection, stable physical/virtual round trips, HiDPI capture, keyboard/scroll input, auto-reconnect, client-driven video preferences, and client-invoked focused-window migration/return. Window return and disconnect recovery restore the original Mac frame. Quality/FPS/bitrate changes and AUTO reset renegotiate in place on the Xiaomi 13 with a bumped config epoch, no host restart, and no transport teardown. Cross-platform offline gates pass. A two-hour soak has run with a stable stream, but the host RSS no-growth gate and native-pointer HID confirmation remain open |
| iOS trusted LAN | Core client interoperates with the baseline MacHost on TCP `54321` only through the explicit plaintext legacy fallback in a real two-process loopback; Simulator UI and device acceptance remain gated |
| HarmonyOS/Internet | In development; not part of the current runnable baseline |

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
- Verified Android devices: Xiaomi 13 (model 2211133C, codename fuxi) is the
  primary named evidence source; Nubia P0110 (codename pacific) is an
  acceptable substitute for general Android acceptance. Both are Android
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
  Protocol v1 reserves CODEC_AV1, and offline admission tests require
  fail-closed or H.264/HEVC fallback unless both peers expose real AV1 support,
  but the current Host does not advertise AV1 and no AV1 real-stream device
  acceptance is recorded.
- CGEvent and Accessibility provide the macOS keyboard, pointer, touch-derived
  gesture, and stylus input adapters. Protocol v1 wires keyboard, native
  pointer/scroll, pen and eraser pressure/tilt, barrel buttons, hover/proximity
  state, and Host-side controller event handling. The Android client now routes
  gamepad/joystick key and motion events through the production Protocol v1
  session when controller capability is negotiated, with mapper, session, and
  protocol behavior covered offline. Host controller events feed a virtual
  gamepad through `IOHIDUserDevice` when an identity-signed build has the
  approved virtual HID entitlement. Physical HID mouse, stylus, and controller
  runtime behavior still require their respective device confirmations.
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
but a valid two-hour host RSS no-growth run, native-pointer HID confirmation,
and controller runtime acceptance remain open gates.**

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
The Xiaomi 13 baseline evidence is recorded under
[docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-08-xiaomi12-fuxi-8a023e3a](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-08-xiaomi12-fuxi-8a023e3a/README.md). The display-switch round-trip and offline self-tests are recorded under
[docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-08-fuxi-display-switch](docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-08-fuxi-display-switch/roundtrip-verification.md).

Implementation status and evidence are tracked in the
[Phase 0 change docs](docs/changes/2026-08-04-phase-0-baseline/PRD.md).

Android TCP connection ownership is now enforced by a standalone JVM transport
module with dependency-direction and resource-lifecycle contract tests. This is
one implemented boundary, not completion of Phase 0 module ownership:
`StreamClient` still combines transport composition with local product-session
behavior, and the remaining protocol, session, media, input, and UI boundaries
are still being extracted.

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
approval and headless reboot still require gated macOS integration evidence.
Real CGEvent
injection under Accessibility is now exercised on device for keyboard and
mouse-wheel scroll (see Phase 1). The legacy compatibility session
still has no keyboard/native-mouse entry point; keyboard and native mouse are
provided only through the Protocol v1 session, where keyboard and scroll are
on-device verified and native pointer move/click remain pending a physical HID
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
real-device host-rotation pass before the acceptance item can close. The
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

An opt-in Xiaomi 13 instrumentation pass also drove the production touch path
for tap, long-press right-click, long-press drag, two-finger scroll, and pinch.
It reproduced a shared-`CGEventSource` bug where pinch's Command modifier leaked
into later ordinary pointer events. Pinch now uses a private synthetic-modifier
event source, preserving legitimate physical modifiers on ordinary pointer
events, with focused isolation coverage. A stable-signed fixed-binary rerun on
the Nubia P0110/pacific Android substitute passed the same opt-in gesture
matrix with Host gesture logs and listen-only macOS event-tap evidence for
tap, right click, drag, plain scroll, Command-modified pinch zoom, and
post-pinch plain-tap modifier isolation; this does not relabel the result as
Xiaomi 13/fuxi evidence. See the
[touch-gesture verification record](docs/changes/2026-08-13-xiaomi13-touch-gestures/TEST.md).

- Deliver USB and LAN connectivity.
- Support virtual extension, mirroring, display selection, HiDPI, rotation, and
  manual video configuration (bitrate/quality/frame-rate presets). Network-driven
  automatic adaptation is a later-phase goal, not part of the Phase 1 USB/LAN path.
- Complete touch, keyboard, mouse, and peripheral input.
- Harden window migration/return, disconnect recovery, automatic reconnect,
  permission onboarding, and actionable errors across supported system states.
- Validate sustained operation on the active Android acceptance device. Xiaomi
  13/fuxi remains a named evidence source, while Nubia P0110/pacific and other
  qualifying Android devices may substitute for general Android
  sustained-operation checks when the evidence records their real identity.

Initial targets are stable 1920×1080 or 1920×1200 at 60 FPS, sub-50 ms USB
glass-to-glass latency, sub-80 ms on a healthy LAN, sub-50 ms P95 input latency,
reconnection within three seconds, and no latency or memory growth over a
two-hour run. USB and LAN glass-to-glass latency gates require external-camera
evidence, while the input-latency gate requires external-camera evidence or a
documented synchronized-clock setup with a reviewable error budget. The gate
profiles are `usb-glass-to-glass-sub50`, `lan-glass-to-glass-sub80`, and
`input-p95-sub50`; host and client telemetry are diagnostic only and cannot
close these gates. As of the 2026-08-20 readiness check, the latency toolchain
passes its fixture gates but no real external-camera package is available in
the repository, so all three external latency gates remain open; see
[the blocked readiness record](docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-20-latency-gates-readiness-blocked/README.md).

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
manifest to declare the device identity, stand/charging setup, thresholds, and
planned recovery scenarios before a future run, plus a package-aware gate
evaluator that checks the raw battery, power, thermal, log, screenshot, and
eight-hour sampling artifacts before it can report `pass`. Hardware-keyboard
workflow evidence is also fail-closed: the current Nubia P0110/pacific Android
16 blocked preflight records the target device identity and input-device
snapshot, then stops because no Android-attached physical keyboard is present
and a stable signed Host with Accessibility/TCC grants is not available. The latest tooling readiness smoke uses the Nubia
P0110/pacific Android 16 phone substitute only, so the physical 8-9 inch tablet,
stand-mounted charging stability, thermal-load, power, login startup, headless
Mac mini, and hardware-keyboard workflow gates all remain open. See the [Phase 2 productization slice](docs/changes/2026-08-14-phase-2-tablet-productization/PRD.md)
and the [tablet acceptance runbook](docs/changes/2026-08-14-phase-2-tablet-productization/RUNBOOK.md).

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

Main commit `73be8c0` hardens this slice at the source level: the Internet
session lease issuer validates the pairing binding before reading identity
credentials, the durable session epoch advances atomically through a single
pairing-scoped transaction, the cross-process security tests are stabilized
against pipe-buffer deadlocks, and the Android decoder-config publish now fails
closed when it cannot publish. These are offline-verified source changes; the
release gates below are unchanged.
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

The macOS M150 adapter has completed real local offer/answer, ICE and
bidirectional DataChannel tests through both direct and forced coturn relay
candidate pairs. Its application record layer is wired to the Keychain-backed
identity/session lifecycle. On 2026-08-05, source commit
`597518f948075e396352bc353afcec01a30303f3` recorded one Nubia P0110/pacific device pass
for the Android M144 adapter, AndroidKeyStore lifecycle, REST signaling client,
product-session UI, and encrypted DataChannel instrumentation through direct and
forced local coturn using synthetic Protocol v1 media. This historical result is
limited to that dated source/device combination and must not be extrapolated to
the current working tree or later commits. It is not real ScreenCaptureKit or
display-capture evidence.
The trusted-LAN path is still separate from Internet mode. Its current
macOS/Android peers use application records on the admitted private-network TCP
session, while explicit legacy fallback remains plaintext and must not be
presented as encrypted or as Internet E2EE evidence.

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
offline build and unit/self-tests, not against real capture output. Not proved:
public Internet, real remote TURN (local loopback and forced local coturn are
not public-Internet or real-deployment evidence), real
ScreenCaptureKit-to-Android device decoder continuity, real network
fluctuation, network handoff, and soak.

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
and the coturn stack through [`deploy/phase3`](deploy/phase3/README.md). Both
services require deployment TLS, secret management, monitoring and limits
described in their runbooks; the example local profile is loopback-only.
`scripts/phase3/coturn_reconcile.py` now provides a bounded operator helper that
accepts a trusted structured coturn allocation snapshot, submits it to Authority's
reconciliation API, and requires an external active-allocation disconnect executor
for unauthorized or conflicting source allocations. It is a contract and local
test target for the exporter/reconciliation/executor boundary, not a deployed
coturn exporter or proof of production enforcement.

See the [Phase 3 requirements](docs/changes/2026-08-04-phase-3-secure-internet/PRD.md),
[technical status](docs/changes/2026-08-04-phase-3-secure-internet/TECH.md),
[threat model](docs/changes/2026-08-04-phase-3-secure-internet/THREAT_MODEL.md),
[test plan](docs/changes/2026-08-04-phase-3-secure-internet/TEST.md), and
[relay operations](docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md).
The previous curated Android interop pass remains withdrawn because its source
commit and raw evidence were unavailable. The separate 2026-08-05
reachable-source record retains raw host/device/UI, service and per-ADB
lease-gate evidence with a privacy scan, without extending its result to current
code. Dated local readiness evidence is recorded under
[`docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness`](docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-20-local-phase3-readiness/README.md).
Automatic account/session-authority issuance, real
encoded ScreenCaptureKit output through the device, automatic fresh-session
recovery after network handoff, public NAT/TURN deployment, cross-service
revocation propagation and soak remain release gates rather than shipped
features. Signaling and relay stores are currently single-node implementations.
Relay credential admission is wired to Authority, and Authority can debit
accepted coturn usage into the control-plane daily-byte ledger. The structured
coturn reconcile helper can fail closed when active source allocations require a
disconnect executor, but the coturn exporter, production reconciliation loop,
active-allocation disconnect executor, and production end-to-end enforcement
remain release gates.

The target is roughly 80–150 ms on healthy Internet paths; relay distance and
network quality may increase it.

### Phase 4 — HarmonyOS NEXT

- Native ArkTS/ArkUI source and an independent Protocol v1 product-session core
  live in [`apps/harmony`](apps/harmony/README.md). Portable gates cover the
  real DevEco project layout, legacy-to-v1 upgrade, channel framing, formal
  control/media fixtures, display/video negotiation, strict session epochs,
  bounded media queues, input encoding (including shared Protocol v1 base and
  extended stylus encoding and capability gating), fail-closed resume results,
  and a portable pairing/credential/replay/revocation core. ArkUI now wires TCP,
  XComponent, AVCodec, Asset Store, foreground suspension, and bounded reconnect in
  source. The portable core encodes both base stylus (position, pressure, tilt)
  and the extended stylus fields (tool kind, barrel buttons, contact/proximity
  state) under capability negotiation, but the production Harmony client
  advertises only CAPABILITY_STYLUS and not CAPABILITY_STYLUS_EXTENDED until
  DevEco/API-checker/HAP/MatePad evidence exists. A contacting pen can fall back
  to touch when the peer lacks stylus support; eraser, proximity/hover, and
  barrel buttons cannot be losslessly downgraded and are suppressed when the
  extended capability is not negotiated. The portable Harmony core now also
  advertises CAPABILITY_CONTROLLER, encodes ControllerEvent field 66, waits for
  Host InputAck acceptance before sending controller state, and releases active
  controllers through all-zero neutral DISCONNECTED events before teardown or
  resume. No DevEco SDK was available for this
  record, so the repository does not claim ArkTS compilation, a HAP, signing,
  installation, hardware decode, HUKS-backed secure pairing, authenticated
  transport, resume-capable Host interoperability, or real-device behavior.
- The [Phase 4 verification record](docs/changes/2026-08-04-phase-4-harmony/TEST.md)
  tracks the remaining DevEco, host-interoperability, and MatePad Mini gates.
- HarmonyOS device acceptance must follow the
  [MatePad Mini runbook](docs/runbook/harmony-matepad-mini.md); Android results
  are never treated as HarmonyOS evidence.
- The read-only `make harmony-readiness EVIDENCE_DIR=...` preflight now records
  DevEco/OHPM/Hvigor/HDC, signed-HAP checksum/signature metadata, Protocol v1
  Host build identity, and MatePad Mini HDC-target readiness into
  `harmony-readiness.json`. It fails closed while any prerequisite is missing
  and is not HAP, installation, streaming, secure-pairing, soak, latency, or
  MatePad Mini acceptance evidence.

### Phase 5 — iOS and advanced capabilities

- A native SwiftUI + VideoToolbox iPhone/iPad foundation now lives in
  [`apps/ios`](apps/ios/README.md): generated Protocol v1 bindings, capability
  negotiation, multi-display routing, H.264/HEVC decode, AV1 fail-closed
  validation, PCM audio, explicit
  clipboard, bounded verified files, epoch filtering, native touch plus
  hardware-keyboard/hover-pointer UI, and bounded trusted-LAN reconnect are
  implemented and core-self-tested.
- The trusted-LAN iOS Core client still uses the explicit plaintext legacy
  fallback to interoperate with the baseline MacHost on TCP `54321`:
  authenticated `SSWA`/`SSWR` admission and the `0D` upgrade lead into the
  Protocol v1 main session, with Hello/capability negotiation, display
  list/start, video-config acknowledgement, media framing, ping/pong,
  display/stream-targeted touch, protocol error, and disconnect covered by a
  real two-process loopback gate. This is not evidence for the current
  macOS/Android secure-record LAN path.
- The iOS app serializes every outbound control envelope through a
  session-owner-scoped FIFO, rejects old connection/decoder deliveries, gates
  each stream on its sent video-config acknowledgement and exact media epochs,
  fragments, and frame sequence, and closes half-open sessions after a bounded
  Pong miss budget.
- The Android and macOS Internet record layers now derive separate directional
  keys, durable nonce counters, and replay domains for control, media, audio,
  and bulk. A shared fixed-vector fixture covers all four AES-256-GCM record
  channels and legacy-compatible key rotation. Audio/bulk WebRTC DataChannels,
  admission/backlog limits, and public-network end-to-end behavior remain
  unproved.
- The macOS Host and Android client now share a transport-neutral, bounded
  single-file transfer domain over Protocol v1 for the existing USB/LAN TCP
  session. File offers require explicit receiver approval and default to reject;
  both sides enforce safe basenames, deny-wins managed policy and resource
  limits, ordered chunks, per-chunk and final SHA-256, session-epoch checks,
  progress-driven backpressure, and cancel/disconnect cleanup. This is offline
  and self-test evidence only: no Android real-device file-transfer acceptance,
  public-Internet run, or WebRTC bulk DataChannel path is claimed.
- The [Phase 5 design](docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md)
  carries additive Protocol v1 fields and client implementations for multiple
  clients/displays, HDR-to-SDR fallback, gesture-to-action mapping,
  Wake-on-LAN, and deny-wins managed configuration.
- The unsigned app has built successfully with the iOS Simulator SDK in CI.
  The iPhone Simulator XCTest and unsigned archive gates pass on the current
  interoperability commit. Signing, iPhone/iPad installation, hardware
  VideoToolbox behavior, host-side advanced adapters, AVAudioEngine playback,
  HDR output, audio/bulk Internet transport, native input behavior, reconnect
  behavior, and all advanced real-device behavior remain separate device
  gates. Android results are never treated as iOS evidence; see the
  [evidence record](docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md).

## Device Strategy

The Android acceptance device can be any currently connected Android handset or
tablet that meets the runtime requirements and is explicitly identified in the
evidence. Xiaomi 13 (model 2211133C, codename fuxi) remains the primary named
evidence source, and Nubia P0110/pacific is an acceptable substitute
for general Android decoding, protocol behavior, input, networking, UI, and
performance validation. Do not relabel one device as another: device-specific
evidence and hardware-gated claims, such as native HID, stylus, thermal, panel,
or SoC decode behavior, remain scoped to the exact device that produced them.
As of 2026-08-10 the Xiaomi 13 has recorded verified streaming, touch, keyboard
and mouse-wheel input, reconnect, a 30-minute soak, display-selection
negotiation, the physical<->virtual<->physical display-switch round-trip, and
HiDPI private-API virtual-display creation/capture (4000x2400 physical / 2000x1200
logical) over USB, plus in-place quality/FPS/bitrate video preferences and
client-invoked focused-window migration/return with disconnect recovery. A
client-local Fit/Fill and four-direction rotation/input matrix is also verified
with host rotation zero; rotated host-display acceptance remains open, with the
recording checklist and offline evidence-summary gate in the Phase 1 test
record. A
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
P0110/pacific, and future P0110/pacific runs may close general Android gates when their
evidence satisfies the same pass criteria. Final tablet
selection emphasizes
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
