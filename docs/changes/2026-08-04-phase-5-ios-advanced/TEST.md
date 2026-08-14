# Phase 5 verification record

Date: 2026-08-05
Host: macOS 26.4.1, Apple silicon  
Swift: 6.3.1  
Selected developer directory: `/Library/Developer/CommandLineTools`

## Passed

```bash
swift package --package-path apps/ios resolve
swift build --package-path apps/ios
swift build --package-path apps/ios -c release
swift run --package-path apps/ios vibescreen-ios-selftest
apps/ios/Scripts/verify-generated-protocol.sh
make protocol
```

Observed result:

```text
Build complete!
RUN: framing
RUN: protocol/session
RUN: codec/backoff
RUN: multi-display/audio
RUN: clipboard/file/policy
RUN: HDR/gesture/wake/advanced-proto
RUN: trusted-LAN startup codecs
RUN: owner/media/heartbeat generation gates
PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup
```

The workflow requires `swift test --package-path apps/ios -c release` under
full Xcode. That Release XCTest target adds deterministic, no-sleep coverage for a
single-writer control outbox (mixed display/Ping/Pong/config traffic,
512-message pressure, deliberately held sends, owner rotation, and late
completion), media pre-ACK/stale-config/replay/fragment rejection through a
decoder spy, config-epoch frame watermark reset (`epoch 1 / frame 100` to
`epoch 2 / frame 1`), full VideoConfig boundary validation (size, FPS, bitrate,
rotation, codec/color enums, and decode limits), invalid-config state
preservation, fallback state preservation, unknown-field forward compatibility,
late control/media/error/pixel owner delivery, and heartbeat
immediate-Pong, miss-budget, correlation, and rotation behavior. The local
Command Line Tools installation cannot import XCTest; this suite is therefore
a required full-Xcode GitHub gate rather than local XCTest evidence.

The self-test additionally covers multi-client epoch replacement, per-client
stream limits/routes, PCM validation and reorder, clipboard explicit-action
and feedback/digest rejection, managed deny-wins policy, safe filenames,
sequential chunks, file limits/final SHA-256/cleanup, HDR10→SDR config-epoch
fallback, gesture persistence/catalog enforcement, the 102-byte WOL vector,
and every advanced Envelope branch used by the client.
Trusted-LAN additions cover strict pairing/auth/upgrade codecs, transport
startup disconnect and Task-cancellation completion, host control message
ordering/session-epoch validation, Ping/Pong correlation, and the client
disconnect envelope factory.

Project metadata also passes:

```text
plutil -lint apps/ios/VibeScreen.xcodeproj/project.pbxproj: OK
xmllint --noout .../VibeScreen.xcscheme: exit 0
swiftc -frontend -parse apps/ios/VibeScreenApp/*.swift: exit 0
GitHub Actions workflow YAML parse: OK
Buf format/lint/build/breaking: pass
Package.resolved revision: c6fe6442e6a64250495669325044052e113e990c
Pinned Swift binding regeneration: pass; checked output current
Second generation SHA-256 manifest diff: empty (deterministic)
SwiftProtobuf license: bundled in the iOS application Resources
Phase 3 protocol compatibility: 4/4 pass
Go security package: pass
```

## Baseline MacHost trusted-LAN interoperability

Run the release-build, real two-process loopback from the repository root:

```bash
apps/ios/Scripts/run_machost_loopback.py
```

The harness starts the production `Vibe Screen` executable with its bounded iOS
loopback adapter on `127.0.0.1:54321`, then starts the iOS Core transport/session
executable as a separate process. The client uses the production
generation-scoped `ControlOutbox` for every outbound control envelope. It runs
a normal lifecycle and a separate invalid-target case. The covered boundary is:

```text
SSWA/SSWR authentication -> 0D/0D01 upgrade -> ClientHello/HostHello
-> SessionAccepted/capabilities -> display list/start -> VideoConfigResult
-> video media frame -> Ping/Pong -> display+stream-targeted TouchEvent
-> DisconnectNotice

invalid display+stream target -> ProtocolError(INVALID_STATE)
```

Observed result on the host recorded above:

```text
iOS Core MacHost loopback: PASS (auth=SSWA/SSWR, upgrade=0D/0D01,
hello=true, displays=true, videoAck=true, media=true, pong=true,
targetedTouch=true, disconnect=true)
iOS Core MacHost loopback: PASS (scenario=invalid-target,
protocolError=invalidState)
MacHost loopback: PASS (external lifecycle + invalid-target
production-process integration)
```

This proves the iOS Core trusted-LAN transport, FIFO control writer, and
main-session composition
against the baseline MacHost. It does not exercise `StreamViewModel`, the
decoder, or UI; boot the iOS application; use an iOS device; or prove hardware
VideoToolbox behavior.

## iOS SDK build evidence

GitHub Actions run
[`30931951983`](https://github.com/TaoSama/vibe-screen/actions/runs/30931951983),
job `simulator-build` (`92068565317`), built the unsigned universal application
from commit `6f7ffbe0be872390144899642636dbb24d89f120` with Xcode 16.4 and the
iPhoneSimulator 18.5 SDK. The job produced arm64 and x86_64 slices and ended
with `** BUILD SUCCEEDED **`.

This proves Xcode project/package resolution and iOS Simulator SDK compilation.
It did not boot a simulator or run the application. The subsequent engineering
gate adds an XCTest UI smoke test, automatic simulator selection, and unsigned
generic-iOS archive validation; those new steps require their own CI result and
must not be retroactively attributed to the earlier build job.

GitHub Actions run
[`30978213167`](https://github.com/TaoSama/vibe-screen/actions/runs/30978213167)
from interoperability commit `650803ce461e8b157c2b067178b3427d3687fd6f`
passed both jobs. The `core` job verified generated bindings, the release Core
self-test, the real MacHost loopback, and all baseline MacHost self-tests. The
`app-build-test-archive` job used Xcode 16.4 (`16F6`) and an iPhone 17 Pro
Simulator on iOS 26.2; `VibeScreenAppUITests` executed 2 tests with 0 failures
and ended with `** TEST SUCCEEDED **`. The unsigned iPhoneOS Release archive
ended with `** ARCHIVE SUCCEEDED **`, passed the script's app/binary/license
checks, and was uploaded as `VibeScreen-unsigned-xcarchive`.

The portable self-test and HarmonyOS core test now consume the same exact
`contracts/fixtures/client-hello-v1.hex` bytes. HarmonyOS must reproduce the
fixture exactly; SwiftProtobuf must decode the same Hello fields. This does not
satisfy the separate Android application fixture criterion.

## Environment gates and unproved behavior

For the original local run, `xcode-select -p` returned Command Line Tools.
`xcodebuild -version` failed because full Xcode was not installed; `iphoneos`,
`iphonesimulator`, and `simctl` were unavailable, and the keychain contained
zero valid signing identities. CI later closed only the SDK compilation gap.
The following remain unproved until their dedicated gates produce evidence:

- iPad-class Simulator layout (the retained smoke run used an iPhone 17 Pro);
- signing, installation, Local Network permission, and lifecycle behavior;
- VideoToolbox hardware H.264/HEVC decode and sustained thermal/power behavior;
- iOS app/Simulator/device end-to-end host connection, decoded video, touch,
  physical hardware-keyboard input, pointer hover, and disconnect/reconnect (the
  macOS Core loopback proves only the transport and Protocol v1 boundary listed
  above);
- cross-client golden bytes against the Android application;
- AVAudioEngine audible output, UIPasteboard prompts/writes, security-scoped
  file picker/export, UDP broadcast, and managed App Configuration injection;
- host-side multi-client/display, audio capture, clipboard/file handlers,
  color retry, actions, wake helper, and audio/bulk E2EE replay isolation;
- HDR/EDR output (the current client deliberately advertises SDR only).

## Required iOS acceptance run

After installing full Xcode, run the commands in `apps/ios/README.md`, then on
real iPhone and iPad hardware record Xcode/OS/device identifiers, app revision,
host revision, negotiation envelopes, codec choice, stream/epoch telemetry,
touch acknowledgement, USB/network interruption, reconnect duration, and a
30-minute memory/latency series. Raw logs belong under this change directory's
`evidence/` subdirectory.

While the Phase 0 soak owns the controlled endpoint (redacted as
`$ADB_ENDPOINT`), Phase 5 performs only
read-only `getprop`, `logcat`, `dumpsys`, or `ps` queries and does not change
ADB, application, or session state. Any later Android Protocol v1 fixture run
must be coordinated by Phase 0. Android evidence is never an iOS build,
decode, UI, or device result.
