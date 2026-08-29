# Phase 5 verification record

Date: 2026-08-05; updated 2026-08-27 for iOS PCM playback verifier
Host: macOS 26.4.1, Apple silicon  
Swift: 6.3.1  
Selected developer directory: `/Library/Developer/CommandLineTools`

## Passed

2026-08-27 local Command Line Tools run from rebased branch
local branch `codex/pr209-current-base-20260827` verified the core
playback queue policy used by the iOS AVFoundation adapter against current
`origin/main` `e94d3a051e683d2a7d6f34fd03badd1b4ef264d0` at source commit
`839f1fc9520c8ea6ca18e6782aa3fa0f6458e838`:

```bash
swift build --package-path apps/ios --configuration release
apps/ios/.build/release/vibescreen-ios-selftest
apps/ios/Scripts/verify-generated-protocol.sh
make protocol
plutil -lint apps/ios/VibeScreen.xcodeproj/project.pbxproj
xmllint --noout apps/ios/VibeScreen.xcodeproj/xcshareddata/xcschemes/VibeScreen.xcscheme
swiftc -frontend -parse apps/ios/VibeScreenApp/*.swift
git diff --check
```

Observed local result:

```text
swift build: Build complete!
vibescreen-ios-selftest: PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup
verify-generated-protocol.sh: generated macOS and iOS Protocol v1 bindings are current
make protocol: Ran 37 tests ... OK
project.pbxproj: OK
xmllint: exit 0
swiftc parse app sources: exit 0
git diff --check: exit 0
```

An initial `make protocol` attempt failed before completing because the system
temporary volume had no free space for Python/Go temporary directories. After
cleaning only this worktree's regenerable SwiftPM build products and rerunning
with `TMPDIR=$PWD/.build/tmp`, the same command passed. The host still cannot
run XCTest or the app-level AVFoundation verifier because only Command Line
Tools are selected:

```text
swift test --package-path apps/ios --configuration release
error: no such module 'XCTest'

xcodebuild -version
xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance

xcrun xctrace list devices
xcrun: error: unable to find utility "xctrace", not a developer tool or in PATH
```

The blocked environment record is retained at
`docs/changes/2026-08-21-ios-audio-playback-verification/evidence/2026-08-25-ios-audio-playback-current-base-blocked/`.
The Host-side advanced adapter readiness gate,
`phase5-host-advanced-adapters-gate`, is a source/readiness owner only: it
does not close host-side multi-client/display, audio, clipboard, file-transfer,
wake, managed-policy, HDR/EDR, or iOS native-input device gates.

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
stream limits/routes, PCM validation and reorder, bounded playback queue
policy, overrun/drop accounting, queue-empty accounting, late-completion
accounting, stop/restart reset, clipboard explicit-action and feedback/digest
rejection, managed deny-wins policy, safe filenames, sequential chunks, file
limits/final SHA-256/cleanup, 10-bit BT.2020/PQ to SDR config-epoch fallback,
gesture persistence/catalog enforcement, the 102-byte WOL vector, WakeHost
device-identity binding, and every advanced Envelope branch used by the client.
Focused macOS/Android tests cover the shared HMAC golden vector, replay and
unauthorized rejection, broadcast-target validation, and the Android Protocol v1
action path to a captured magic-packet sender.
Trusted-LAN additions cover strict pairing/auth/upgrade codecs, transport
startup disconnect and Task-cancellation completion, host control message
ordering/session-epoch validation, Ping/Pong correlation, and the client
disconnect envelope factory.

The app target adds a focused `AVAudioSession`/`AVAudioEngine` verifier through
`VibeScreenAppUITests/testAudioPlaybackSelfTestSchedulesPCMAndRestarts`. The
test launches the app with `--audio-playback-self-test`, configures PCM S16LE,
schedules synthetic audio through `AVAudioPlayerNode`, observes bounded queue
overrun/drop behavior, waits for played-buffer and queue-empty counters to
advance, stops, restarts on a newer config epoch, waits for playback completion
again, observes the initial `AUDIO_PLAYBACK_SELF_TEST=RUNNING` diagnostic line,
and waits for terminal `AUDIO_PLAYBACK_SELF_TEST=PASS` in the UI. The app-side
15-second timeout reports stalled playback completion as terminal `FAIL`; this
closes only the executable playback-path check when run by full Xcode on a
Simulator or signed device; it does not prove audible iPhone/iPad output
without external audio confirmation. Late-completion accounting remains covered
by the offline queue tests and is
reported by the app verifier as diagnostic telemetry.

The Host-side advanced adapter readiness gate remains a source/readiness gate:
it keeps host-side multi-client/display, audio, clipboard, file-transfer,
HDR/color, host-action, wake, and managed-policy device gates open until the
separate product-flow evidence exists.

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
loopback adapter on `127.0.0.1` by asking the Host to bind port `0`, then
passes the selected localhost port to the iOS Core transport/session executable
started as a separate process. The secure-record path is used by default. The
client uses the production
generation-scoped `ControlOutbox` for every outbound control envelope. It runs
a normal lifecycle and a separate invalid-target case. The covered boundary is:

```text
SSWA/SSWR authentication -> VSLS/VSLR AES-256-GCM records
-> 0D/0D01 upgrade inside the record stream -> ClientHello/HostHello
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
main-session composition against the baseline MacHost's secure-record loopback
path. The same harness can explicitly exercise plaintext legacy fallback with
`--legacy-plaintext`; that fallback is a regression path and must not be
reported as encrypted evidence. The default loopback does not exercise
`StreamViewModel`, the decoder, or UI; boot the iOS application; use an iOS
device; prove hardware VideoToolbox behavior; or prove real-network LAN device
acceptance.

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

## iOS native-input behavior gate owner

The README Phase 5 native-input behavior gate is owned by
`phase5-ios-native-input-behavior`. The current repository includes a read-only
evidence summary entry point:

```bash
make ios-native-input-gate EVIDENCE_DIR=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>
```

The gate consumes a sanitized `ios-native-input-observations.json` file and
writes `ios-native-input-gate.json`. It requires real signed iPhone and iPad
runs, Local Network permission, baseline MacHost listener identity, Protocol v1
session negotiation, input capability negotiation, selected display/stream
routing, touch tap and drag on both iPhone and iPad classes, hardware
keyboard press/release, modifier cleanup, hover or pointer accessory movement, Host input acknowledgements, and retained
iOS/Host logs. Missing iOS hardware, signed app, Host listener, hardware
keyboard, or hover/pointer accessory evidence reports `blocked`; missing
non-blocking behavior evidence reports `insufficient`; any claim that uses
Android evidence, Simulator evidence, or offline tests as iOS input behavior
reports `fail`. Only `pass` can close the iOS native-input behavior gate.

This is an evidence/readiness owner, not device evidence. No signed iPhone or
iPad native-input run is recorded in this repository yet, so the README Phase 5
native-input behavior gate remains open.

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

The current-base aggregate owner is #290. Merged #182 remains the historical
sanitized iOS device-acceptance baseline, while #290 owns the aggregate iOS
acceptance tracking entry point for the current base. The narrower readiness
work remains scoped to the related PR/task owners: #196 gesture/action mapping,
PR #207 managed policy, #208 trusted-LAN secure records, #209 AVAudioEngine/PCM,
PR #238 reconnect, #251 VideoToolbox, #253 host advanced adapters, #257 native
input, #279 key-release/native-input modifier behavior, and #282 Phase 5 host
gate ownership. The aggregate must not pass by owner declaration alone; it
passes only when the machine-readable gate can prove every required iOS hardware
and broader Phase 5 gate from retained evidence.

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

The HDR output row now has its own fail-closed current-base verifier:

```bash
make ios-hdr-edr-gate EVIDENCE_DIR=.build/evidence/ios-hdr-edr
```

With no retained physical iOS HDR/EDR observations, the expected verdict is
`blocked` and `can_close_ios_hdr_output_gate=false`. A pass requires physical
iPhone/iPad HDR-capable display identity, measured EDR/HDR display capability,
`CAPABILITY_HDR_VIDEO` negotiation, an accepted HDR config rather than SDR
fallback, 10-bit PQ/HLG VideoToolbox output metadata, renderer-layer EDR
enablement, visible HDR/EDR output diagnostics, same-revision SDR peer fallback,
and retained artifacts. Simulator, unsigned archive, Android, SDR fallback,
protocol-only, and macOS fallback evidence returns `fail` if it is used as an
HDR claim.

| Gate | Current-base state | Evidence boundary |
| --- | --- | --- |
| signing | blocked-readiness | Requires a signed archive, a unique bundle ID, a certificate, and a provisioning profile. |
| VideoToolbox H.264/HEVC | open | Implementation and CI build evidence exist; hardware decode requires iPhone and iPad records. |
| advanced adapters | open | Client/core and Mac/Android slices are offline-tested; host/product E2E remains separate. |
| AVAudioEngine/PCM | open | Core PCM validation exists; audible iOS playback is not recorded. |
| HDR | open | Dedicated `ios-hdr-edr-gate` owner exists; current renderer is SDR-only and HDR/EDR output is not recorded. |
| native input | open | Encoding and loopback touch evidence exist; signed iOS app/device input is not recorded. |
| reconnect | open | Core heartbeat/backoff exists; trusted-LAN iOS device reconnect is not recorded. |
| trusted LAN secure records | open | Current iOS baseline loopback proves secure-record readiness only; signed iPhone/iPad and real-network LAN evidence remain open. |

The Host-side advanced adapter readiness gate is a source/readiness contract
only. It does not close host-side multi-client/display, audio, HDR,
clipboard/file, file-transfer, wake, managed-configuration, native-input,
reconnect, trusted-LAN, or other device/product-flow gates.

The signing row is now backed by a dedicated app-signing readiness owner:

```bash
make ios-app-signing-readiness-gate \
  IOS_APP_SIGNING_READINESS_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness.json
```

The gate is passive and fail-closed. It requires retained Team ID, provisioning
profile UUID, unique bundle ID, non-ad-hoc codesign identity, physical-device
UDID hashes, signed-app entitlements, signed artifact SHA-256, a clean
current-base commit, and signing artifact paths for the archive command,
codesign entitlements, and provisioning profile output. Public retained evidence
must use sanitized presence fields, hashes, and redaction flags rather than raw
Team IDs, profile UUIDs, certificate hashes, identity names, physical-device
UDIDs, or local filesystem paths. Missing any one of
those fields returns `blocked`; Simulator, unsigned, ad-hoc, or Android-derived
material returns `fail`. A pass only unblocks the app-signing prerequisite for
`ios-current-base-gate` when the resulting
`ios-app-signing-readiness-gate.json` is bound into the generated manifest. The
aggregate checks both `dedicated_signing_readiness_gate` and
`dedicated_signing_readiness_owner`, then derives the signing row from the gate
sanitized `signing_summary`; hand-written manifest signing fields without that
owner remain blocked. It still cannot close install, launch, VideoToolbox,
input, reconnect, audio, or full iOS device acceptance.
The current retained blocked owner record is
[`2026-08-29-ios-signing-current-base-blocked`](evidence/2026-08-29-ios-signing-current-base-blocked/README.md).

The native-input row is also backed by a dedicated owner summary.
`ios-current-base-manifest` binds `ios-native-input-gate.json` when supplied via
`IOS_NATIVE_INPUT_GATE_JSON`, and the aggregate requires
`dedicated_native_input_gate`, `dedicated_native_input_owner`,
`dedicated_native_input_current_base`, and an input evidence marker containing
`ios-native-input-gate.json verdict=pass can_close_ios_native_input_gate=true`
before the E5 input row can pass. Hand-written `gates.input.status=pass` entries
without that owner summary remain blocked. This does not record or imply a
signed iPhone/iPad native-input run.

2026-08-23 current-base readiness smoke on this worktree ran:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base-smoke-20260823
```

The command wrote the manifest and gate report, then exited nonzero as expected
with `verdict=blocked`. The retained gate JSON recorded
`can_close_ios_device_acceptance=false`,
`can_close_current_base_aggregate=false`, and
`can_claim_device_pass=false`. Blocking reasons included full Xcode/iPhoneOS SDK
unavailability in the active Command Line Tools environment, missing signing
identity/profile/signed archive, missing physical iPhone and iPad install
evidence, and missing E1-E7 gate evidence. The broader HDR, advanced-adapter,
and trusted-LAN secure-record gates remained insufficient. The generated
manifest also records the local Xcode/iPhoneOS SDK and Swift toolchain probes so
that an environment-only readiness improvement cannot be mistaken for signed
iOS hardware acceptance.

## Phase 5 multi-client/display current-base gate

The current-base owner for planned multiple clients/displays is the read-only
`phase5-multi-client-current-base-gate` target. It is deliberately separate
from single-client display-selection and display-switch records: one client
switching between physical and virtual displays is not simultaneous
multi-client concurrency and cannot close this gate.

Use it after collecting a retained evidence package:

```bash
make phase5-multi-client-current-base-gate \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>
```

The evidence package must include `multi-client-concurrency.json` plus retained
Host routing, transport ownership, display identity, macOS Host, and two
Android-client artifacts. Each retained artifact must be a JSON file with the
expected Phase 5 artifact `kind`, the shared schema version, and the same
`source_revision` as the manifest, plus true observations for that artifact's
routing, transport, display, Host, or Android-client claim; Android-client
artifacts must also include the device identity they exercised. A pass requires
at least two simultaneous clients, distinct session IDs and epochs, independent
transport connections, per-client route binding, per-client frame queue or
broadcast ownership, per-client input target validation, a defined
parallel/broadcast capture model, Host `CAPABILITY_MULTI_CLIENT` advertisement,
and visible distinct streams on the Android clients. It also requires iOS and
HarmonyOS owner status to be recorded, so the planned cross-platform
destination does not silently lose ownership.

The gate is fail-closed:

- missing `multi-client-concurrency.json` is `blocked`;
- single-client multi-display evidence is `insufficient`;
- device identity relabeling is `fail`;
- only a complete package returns `pass` with
  `can_close_phase5_multi_client_display_gate=true`.

The 2026-08-24 current-base smoke record is intentionally blocked because no
two-device or multi-client run was available. It records the current production
boundary found in source audit: MacHost `StreamingServer` still owns a single
active `NWConnection`, a single `ProtocolV1SessionCoordinator`, a single
capture pipeline, and one virtual display; `ProtocolV1SessionConfiguration`
does not advertise `.multiClient` in production. PR #201 adds an offline Host
routing boundary, but its own record keeps production capped at one active
client/stream and does not close multi-device or parallel-capture acceptance.
The Host-side advanced adapter readiness gate is source/readiness evidence only
and does not close host-side multi-client/display or other Phase 5 device gates.

## MacHost multi-client/display routing boundary

On 2026-08-21 the Host Protocol v1 session layer gained an offline-tested
multi-client/display routing boundary. The shared `HostMultiClientDisplayRouter`
keys clients by `session_id` and `session_epoch`, enforces configured
`maximum_clients` and per-client video-stream limits, allocates display-bound
`stream_id` values, rejects stale lower epochs while a newer route is active,
and releases routes when a session closes. The session coordinator now validates
touch, pointer, scroll, keyboard, controller, and host-action targets against
the route owned by the same client session before any input action reaches the
Host injection layer.

Local validation from the repository root:

```bash
swift build --package-path baseline/MacHost
make baseline-macos-self-test
make protocol
git diff --check
```

Observed result:

```text
Build complete!
Host self-test: PASS (display identity/catalog, input/window geometry, startup/recovery policy, callback generation, fallback replacement, ADB device selection)
Transport self-test: PASS (config=true, keyframe=true, pong=true, touch=true, malformedTouchRejected=true, portConflict=true, codecNegotiations=1, protocolV1Lifecycle=true, protocolV1ReadyLifecycle=true, protocolV1PreReadyStops=true, fileApprovalDispatch=true, error=none)
Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)
Protocol v1 self-test: PASS (framing, golden, negotiation, display/video gate, multi-client routing, epoch, targeted input, heartbeat, graceful disconnect, error, media)
video encoder self-test passed (encoded callbacks: 1)
```

`make protocol` also passed the Buf format/lint/build/breaking checks and the
37 Python protocol fixture/security tests. `git diff --check` reported no
whitespace errors.

Additional XCTest coverage was added for the same boundary: router stream/client
caps, stale-epoch rejection, disconnect cleanup, HostHello versus
SessionAccepted resource-limit reporting, `CAPABILITY_MULTI_CLIENT` negotiation,
duplicate-display rebind error mapping, and cross-client touch/keyboard target
rejection. On this local machine
`swift test --package-path baseline/MacHost --filter ProtocolV1SessionTests/testHostDisplayRouterIsolatesClientsEpochsAndStreamLimits`
still fails before executing tests because the selected Command Line Tools
SwiftPM environment cannot import `XCTest`. Full-Xcode CI remains responsible
for running that XCTest target.

This record is blocked for real acceptance. No two-device Host run was executed,
no Android device command was needed, and no device evidence is claimed. The
production `StreamingServer` still intentionally configures one active client,
one virtual display, and one video stream per client; it continues to replace an
old Network.framework connection when a new one is admitted. `ScreenCapture`,
`VirtualDisplayManager`, AppDelegate display state, and frame queues remain
single-instance. Therefore this closes only the offline Protocol v1 Host routing
boundary and does not close multi-device, parallel capture, or multi-virtual-
display acceptance.

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
- iOS trusted-LAN device behavior; the current default loopback exercises
  AES-256-GCM secure records only on localhost and is not signed iPhone/iPad or
  real-network LAN evidence;
- cross-client golden bytes against the Android application;
- AVAudioEngine path execution beyond the launch-argument verifier, audible
  iPhone/iPad output, UIPasteboard prompts/writes, security-scoped file
  picker/export, real sleeping-host Wake-on-LAN over router/NIC firmware paths,
  and managed App Configuration injection. The WakeHost current-base evidence
  owner is #199 after rebasing onto #225 and must use
  `make wake-host-current-base-gate` to keep this gate blocked until hardware
  evidence exists;
- Host-side advanced adapter readiness gate coverage for host-side multi-client/display, audio capture, clipboard/file handlers,
  color retry, actions, and wake helper;
- audio capture/playback, clipboard, and file-transfer product flows over
  audio/bulk WebRTC DataChannels, plus real-network E2E behavior. The
  Android/macOS raw product-session record hooks, owner-scoped admission,
  bounded backlog, record-layer key, nonce, replay, and fixed-vector checks are
  offline evidence only;
- HDR/EDR output (the current clients deliberately advertise SDR only, and
  fallback/readiness tests do not prove visible HDR output).

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
