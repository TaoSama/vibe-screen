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
WakeHost device-identity binding, and every advanced Envelope branch used by
the client. Focused macOS/Android tests cover the shared HMAC golden vector,
replay and unauthorized rejection, broadcast-target validation, and the
Android Protocol v1 action path to a captured magic-packet sender.
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
loopback adapter on `127.0.0.1:54321` and explicit plaintext legacy fallback,
then starts the iOS Core transport/session executable as a separate process. The
client uses the production
generation-scoped `ControlOutbox` for every outbound control envelope. It runs
a normal lifecycle and a separate invalid-target case. The covered boundary is:

```text
SSWA/SSWR authentication -> explicit plaintext legacy fallback
-> 0D/0D01 upgrade -> ClientHello/HostHello
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
main-session composition against the baseline MacHost's explicit legacy
fallback. It does not exercise `StreamViewModel`, the decoder, or UI; boot the
iOS application; use an iOS device; prove hardware VideoToolbox behavior; or
prove the macOS/Android secure-record LAN path.

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

## Mac/Android bounded file-transfer loop

On 2026-08-19 the MacHost and Android Protocol v1 file-transfer implementation
was verified offline from the repository root with:

```bash
git diff --check
make protocol
cd baseline/MacHost && swift build
cd ../.. && make baseline-macos-self-test
cd baseline/AndroidClient && ./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug
```

Observed result:

```text
Protocol fixture/security tests: 35 tests, OK
MacHost swift build: Build complete
Host self-test: PASS
Transport self-test: PASS
Reliability self-test: PASS
Protocol v1 self-test: PASS
video encoder self-test passed
Android Gradle: BUILD SUCCESSFUL, 70 actionable tasks
```

The added Mac/Android unit fixtures cover explicit approval default-reject,
safe basenames, deny-wins managed policy, maximum byte and chunk limits,
ordered offsets, per-chunk and final SHA-256, session-epoch rejection, empty
file final-chunk handling, cancel cleanup, and logical bulk channel `4`
framing. Production USB/LAN integration sends one file chunk per
accept/progress acknowledgement and cancels/stages fail-closed on policy, digest,
disk, backpressure, disconnect, or peer cancellation.

This is not real-device evidence. It does not prove Android picker/UI flows, an
installed APK moving files against a live Mac, public Internet behavior, WebRTC
bulk DataChannels, or host/iOS advanced file adapters. A local
`swift test --filter ProtocolV1FileTransferTests` attempt failed before running
tests because the selected Command Line Tools SwiftPM environment could not
import `XCTest`; the full-Xcode CI gate remains responsible for Mac XCTest
execution.

## Current-base aggregate readiness

The current-base aggregate owner is #182. It owns the aggregate iOS acceptance
tracking entry point for the current base, while the narrower readiness work
remains scoped to the related PR/task owners: #196 gesture/action mapping, #207
managed policy, #208 trusted-LAN secure records, #209 AVAudioEngine/PCM, #238
reconnect, #251 VideoToolbox, #253 host advanced adapters, and #257 native
input. The aggregate must not pass by owner declaration alone; it passes only
when the machine-readable gate can prove every required iOS hardware and broader
Phase 5 gate from retained evidence.

Use the fail-closed current-base collector before scheduling or reporting an iOS
device run:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

That command writes `ios-current-base-manifest.json` and
`ios-current-base-gate.json`. On the current development baseline without signed
iPhone and iPad hardware evidence, the expected verdict is `blocked`, the
command exits nonzero, and both `can_close_ios_device_acceptance` and
`can_close_current_base_aggregate` remain false. A `pass` requires signing,
device install, Protocol session, H.264 and HEVC VideoToolbox decode, input,
reconnect, audio playback, HDR output, host advanced adapters, and trusted-LAN
secure-record evidence. Simulator UI, unsigned archives, MacHost loopback,
Android device evidence, and plaintext legacy fallback are readiness inputs
only.

| Gate | Current-base state | Evidence boundary |
| --- | --- | --- |
| signing | blocked-readiness | Requires a signed archive, a unique bundle ID, a certificate, and a provisioning profile. |
| VideoToolbox H.264/HEVC | open | Implementation and CI build evidence exist; hardware decode requires iPhone and iPad records. |
| advanced adapters | open | Client/core and Mac/Android slices are offline-tested; host/product E2E remains separate. |
| AVAudioEngine/PCM | open | Core PCM validation exists; audible iOS playback is not recorded. |
| HDR | open | SDR fallback is implemented; HDR/EDR output is not recorded. |
| native input | open | Encoding and loopback touch evidence exist; signed iOS app/device input is not recorded. |
| reconnect | open | Core heartbeat/backoff exists; trusted-LAN iOS device reconnect is not recorded. |
| trusted LAN secure records | open | Current iOS baseline loopback is explicit plaintext legacy fallback, not secure-record LAN evidence. |

2026-08-22 current-base readiness smoke on this worktree ran:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base-smoke-20260822
```

The command wrote the manifest and gate report, then exited nonzero as expected
with `verdict=blocked`. The retained gate JSON recorded
`can_close_ios_device_acceptance=false`,
`can_close_current_base_aggregate=false`, and
`can_claim_device_pass=false`. Blocking reasons included full Xcode/iPhoneOS SDK
unavailability in the active Command Line Tools environment, missing signing
identity/profile/signed archive, missing physical iPhone and iPad install
evidence, and missing E1-E7 gate evidence. The broader HDR, advanced-adapter,
and trusted-LAN secure-record gates remained insufficient.

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
  and disconnect/reconnect (the macOS Core loopback proves only the transport
  and Protocol v1 boundary listed above);
- iOS trusted-LAN encrypted-session behavior; the current loopback exercises
  explicit plaintext legacy fallback only and is not AES-256-GCM secure-record
  LAN evidence;
- cross-client golden bytes against the Android application;
- AVAudioEngine audible output, UIPasteboard prompts/writes, security-scoped
  file picker/export, real sleeping-host Wake-on-LAN over router/NIC firmware
  paths, and managed App Configuration injection;
- host-side multi-client/display, audio capture, clipboard/file handlers,
  color retry, actions, and wake helper;
- audio capture/playback, clipboard, and file-transfer product flows over
  audio/bulk WebRTC DataChannels, plus real-network E2E behavior. The
  Android/macOS raw product-session record hooks, owner-scoped admission,
  bounded backlog, record-layer key, nonce, replay, and fixed-vector checks are
  offline evidence only;
- HDR/EDR output (the current client deliberately advertises SDR only).

## Required iOS acceptance run

After installing full Xcode, follow the
[iOS device acceptance runbook](../../runbook/ios-device-acceptance.md). Run the
commands in `apps/ios/README.md`, then on real iPhone and iPad hardware record
Xcode/OS/device identifiers, app revision, host revision, negotiation
envelopes, codec choice, stream/epoch telemetry, touch acknowledgement,
network interruption, reconnect duration, and any owner-requested bounded
memory/latency series. Raw logs belong under this change directory's
`evidence/` subdirectory or an external release bundle after privacy review.
Every committed run summary must include sanitized `acceptance.json`,
`ios-device-acceptance-gate.json`, a hash manifest, and the privacy-reviewed
artifact list. The aggregate gate is read-only and fails closed: missing
metadata, environment, signing, device, or formal E1-E7 gate evidence returns
`blocked`; missing broader Phase 5 HDR, advanced-adapter, or trusted-LAN
secure-record evidence returns `insufficient`; Android-substituted evidence
returns `fail`.

While the Phase 0 soak owns the controlled endpoint (redacted as
`$ADB_ENDPOINT`), Phase 5 performs only
read-only `getprop`, `logcat`, `dumpsys`, or `ps` queries and does not change
ADB, application, or session state. Any later Android Protocol v1 fixture run
must be coordinated by Phase 0. Android evidence is never an iOS build,
decode, UI, or device result.
