# Phase 4 verification record

Date: 2026-08-05

## Portable checks passed

```text
cd apps/harmony && pnpm run verify
Validated 29 HarmonyOS project files and semantic release boundaries (static only; no ArkTS/HAP claim).
40 tests, 40 passed, 0 failed
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
- pointer/scroll/key envelope separation, HID/button mapping, rotation, and backoff;
- browser-global-free UTF-8 handling and advertised video-size/FPS enforcement;
- parsed AppScope/entry/Hvigor/resource/version/native-dependency/permission
  graph, production seam checks, packaged license/notices, and validator
  negative fixtures.

Hosted `HarmonyOS portable checks (no DevEco or HAP claim)` runs the same frozen
install and verify command. It cannot type-check `.ets` or validate vendor APIs.

## Environment evidence

```text
base commit: 36905b40b2457c9f156e0b9b273fd437303a1efe
node: v26.5.0
pnpm: 11.15.1
TypeScript: 5.9.3
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
task commit. Contract gates that consume that working-tree file are not valid
until it is restored by its owner or from a confirmed clean checkout.

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
  stylus pressure, focus, safe area, letterbox, and both orientations;
- background/foreground, permission denial, Wi-Fi loss/restore/roam, host restart,
  bounded reconnect, resume-result behavior, and no old-epoch render;
- MatePad Mini eight-hour thermal/power/RSS/frame-drop soak and external-camera
  glass-to-glass/input latency. Android evidence is never a substitute.
