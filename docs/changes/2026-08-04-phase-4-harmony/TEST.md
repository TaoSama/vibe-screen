# Phase 4 verification record

Date: 2026-08-05

## Reproducible source identity

The full clean verification below ran from a detached worktree with:

```text
tested commit: 11ced21f64279c27e1f9107a58a8a11f5ed5f532
tested tree: eb78445bbf59a1351980ce3e58c8175e8f7081f2
git status --porcelain before gates: (empty)
git status --porcelain after gates: (empty)
upgrade acknowledgement bytes: 0d01
```

## Portable checks passed

```text
cd apps/harmony && pnpm run verify
Validated 32 HarmonyOS project files and semantic release boundaries (static only; no ArkTS/HAP claim).
77 tests, 77 passed, 0 failed
```

Coverage includes:

- historical and formal ClientHello exact bytes, packed enum/resource/decode limits;
- zero-length ListDisplaysRequest oneof encoding;
- formal HostHello → SessionAccepted → list/start display → VideoConfig sequence;
- touch fixture with display/stream target;
- split/coalesced protocol upgrade and control/video channel framing;
- formal MediaPacketHeader/Annex-B parsing and payload length rejection;
- additive unknown fields and truncated fixed-field rejection;
- epoch/message/stream/config validation and capacity-one media queue;
- negotiated-capability/input gates and non-finite input rejection;
- single-writer FIFO, dequeue-time message IDs, response correlation, and a
  delayed VideoConfigResult interleaved with heartbeat traffic;
- matching-Pong timeout, retryable recovery policy, and cleanup error aggregation;
- bounded/priority-aware control backpressure, handshake/config/first-frame watchdog wiring,
  decoder-configuration rejection, and SDR/8-bit video acceptance;
- wait-keyframe recovery across queue overflow, frame gaps, decoder push
  failure, epoch reset, and keyframe push completion;
- configure/surface/prepare/start failure injection plus configure/release
  supersede at every await window, stage-rejection cleanup races, one
  per-candidate cleanup promise, the A/B/C transition barrier, and old
  continuation isolation;
- native decoder creation reservation before the factory call, create-await
  supersede/release and A/B/C barriers, single uninitialized release, and
  observable factory/release failures;
- deterministic parse/timeout/error/socket-close/controller-close/supersede
  races with one transport close owner and one notification;
- pointer/scroll/key envelope separation, HID/button mapping, rotation, and backoff;
- browser-global-free UTF-8 handling and advertised video-size/FPS enforcement;
- parsed AppScope/entry/Hvigor/resource/version/native-dependency/permission
  graph, parse diagnostics, method-scoped production import/call checks,
  dominating capability guards, exact bounded-queue control flow, packaged
  license/notices, and external/method-local/constant-terminal/dead-path
  validator negatives.

Hosted `HarmonyOS portable checks (no DevEco or HAP claim)` runs the same frozen
install and verify command. It parses TypeScript-compatible ArkTS and an ArkUI
lifecycle/input shell, but cannot run the DevEco ArkTS API/type checker, parse
the full declarative ArkUI builder grammar, or validate vendor APIs.

## 2026-08-16 gated stylus portable replay

The Harmony stylus slice was replayed onto `origin/main`
`49645ead2115b51e61e30c0954ddc35c88cabd1d` without merging or cherry-picking
the former feature branch. The source-only gates passed:

```text
cd apps/harmony && pnpm run verify
  PASS: 35 semantic project files; 101/101 portable tests
python3 contracts/fixtures/messages/v1/generate.py --check
  PASS: checked fixtures match generation
python3 -m unittest contracts.tests.test_protocol_fixtures -v
  PASS: 11/11 protocol fixture tests
cd apps/harmony && make doctor
  BLOCKED: hvigor and ohpm are not installed
```

The portable additions cover the shared base and extended stylus fixtures,
capability dependency closure, touch fallback and extended-only suppression,
strict input/lifecycle validation, release-before-close ordering, bounded
release priority, and resume suppression while stylus state is active or not
yet released. A terminal or release control must also be confirmed written by
the control writer before resume is allowed. The production client continues
to advertise only base stylus.
This record does not establish DevEco ArkTS compilation, API compatibility, a
HAP, signing, installation, hardware decode, or MatePad behavior.

## 2026-08-19 controller gate audit

The Harmony controller-input gate was audited without claiming production
controller support. The portable project validator now fails closed if the
production Harmony client starts advertising `CAPABILITY_CONTROLLER`, exposes a
`ControllerEvent` payload field or encoder, adds a `ProductSession.controller()`
send path, or adds a platform `HarmonySessionController.sendController()` route
before lifecycle, neutral-release, DevEco, HAP, and MatePad evidence exists. The
runtime portable tests also pin that field 66 remains absent from the production
encoder surface and that an incoming `ControllerEvent` fixture is rejected by a
streaming Harmony `ProductSession` as an unexpected Protocol v1 payload.

```text
cd apps/harmony && pnpm run verify
  PASS: 35 semantic project files; 109/109 portable tests
```

This pass does not implement controller-specific input and does not prove the
receiver-side all-zero neutral-state synthesis required for button masks, stick
axes, triggers, and hat axes when an admitted controller lifecycle is discarded.
It also does not establish DevEco/API-checker, HAP, signing, installation,
hardware decode, HUKS-backed secure pairing, host interoperability, or MatePad
behavior.

## Clean cross-repository gates

The following commands ran against the tested commit/tree above:

```text
cd apps/harmony && pnpm install --frozen-lockfile && pnpm run verify
  PASS: 32 semantic project files; 77/77 portable tests
make protocol
  PASS: Buf format/lint/build/breaking; 13/13 contract tests
make evidence-tools-test release-tools-test
  PASS: 36/36 evidence tests; 4/4 release-tool tests
cd baseline/AndroidClient && ./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies
  PASS: 67 tasks, 66 executed, 1 up-to-date
make baseline-macos-self-test baseline-macos-app
  PASS: release build; host/transport/reliability/Protocol v1 self-tests; app/zip/checksum package
apps/ios/Scripts/verify-generated-protocol.sh
swift package --package-path apps/ios resolve
swift build --package-path apps/ios
swift run --package-path apps/ios vibescreen-ios-selftest
  PASS: generated bindings current; native core build and deterministic self-test
```

Two platform test commands were attempted but are environment-blocked rather
than product failures:

```text
make baseline-macos-test
  BLOCKED: no such module 'XCTest' under active Command Line Tools
apps/ios/Scripts/build_ios.py
  BLOCKED: xcodebuild requires Full Xcode; active directory is CommandLineTools
```

## Environment evidence

```text
base commit: 36905b40b2457c9f156e0b9b273fd437303a1efe
node: v26.5.0
pnpm: 11.15.1
TypeScript: 5.9.3
Go launcher: 1.24.13; Buf selected Go 1.25.12 toolchain
Swift: 6.3.1
JDK: 17.0.19
hvigor: not found
ohpm: not found
hdc: not found
DevEco Studio: not found
```

Public OpenHarmony 5.0 API declarations were inspected at immutable commit
`85c68ed2a9ea8437377ce0a168db747629446b0a`. They confirm Asset Store's
`Map<Tag, Value>`, XComponent surface ID, ArkUI changedTouches/mouse/key fields,
and Ability/network seams. That public interface set does not include the
commercial HarmonyOS NEXT AVCodecKit surface, so it cannot prove the decoder.

During this task an unrelated concurrent modification changed
`contracts/fixtures/messages/v1/bin/upgrade_acknowledgement.bin` from binary
`0d 01` to the text `0d\n`. All task subagents denied writing it and the source
could not be proven, so the file was not overwritten and is excluded from the
task commits. The detached clean verification worktree obtained the committed
binary `0d 01` without modifying the unexplained working-tree file; the formal
contract gate then passed `test_upgrade_bytes_are_pinned`.

## DevEco gates

- clean OHPM sync with recorded lock/tool/SDK versions;
- ArkTS/API checker for every `.ets` file and module schema;
- confirmation/correction of AVCodecKit buffer callback, memory write, PTS,
  render/free, flush, reconfigure, EOS, and release calls;
- debug and signed release `assembleHap`, HAP contents/permissions/signature,
  SHA-256, install, in-place upgrade, rollback behavior, and uninstall cleanup;
- Asset Store client/host record CRUD and malformed-version removal;
- XComponent surface creation/destruction across rotation/background/foreground.

## Host and device gates

- real upgrade/HostHello/session/display/video/control/media interoperability;
- secure PairingOffer/Request/Result proof, credential issue/revoke, replay and expiry;
- H.264 and HEVC hardware render with decoder identity evidence;
- multi-touch, Up/Cancel, keyboard/HID/modifiers, pointer/buttons, wheel/trackpad,
  stylus (base pressure/tilt and extended eraser/barrel/proximity under
  capability gating), focus, safe area, letterbox, and both orientations;
- controller-specific input: Protocol v1 defines `CAPABILITY_CONTROLLER = 26`
  and lifecycle-scoped `ControllerEvent`, and the Harmony portable protocol
  model mirrors `Capability.CONTROLLER = 26`; the production client does not
  advertise the capability and has no `ControllerEvent` encoder, controller
  lifecycle implementation, or platform routing. Portable checks now reject
  premature production advertisement, encoder, session, and platform routes and
  reject an incoming field-66 fixture in the streaming session. A future
  receiver must prove
  that it synthesizes the same all-zero neutral state for the button mask, stick
  axes, triggers, and hat axes before discarding an active controller on
  disconnect, session teardown, ownership takeover, or transport loss. Current
  portable checks do not prove that neutral-state rule; DevEco/API-checker, HAP,
  and device evidence are also absent;
- background/foreground, permission denial, Wi-Fi loss/restore/roam, host restart,
  bounded reconnect, resume-result behavior, and no old-epoch render;
- MatePad Mini eight-hour thermal/power/RSS/frame-drop soak and external-camera
  glass-to-glass/input latency. Android evidence is never a substitute.
