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

## 2026-08-19 controller input portable closure

The Harmony controller-input source path now has a portable/offline closure. The
production Harmony source advertises `CAPABILITY_CONTROLLER`, exposes
`ControllerEvent` payload field 66 in the protocol encoder, validates controller
identity, button, stick, trigger, hat, lifecycle, and four-active-controller
bounds, and waits for the Host's accepted `InputAck` for CONNECTED before
admitting STATE or DISCONNECTED. Active controller state blocks resume until a
terminal all-zero neutral `DISCONNECTED` release has been written through the
control writer. The platform session controller routes controller samples behind
a dominating `Capability.CONTROLLER` guard and uses the same active-input
release path for disconnect, background, reconnect, and transport-loss cleanup.

```text
cd apps/harmony && pnpm run verify
  PASS: 35 semantic project files; 115/115 portable tests
```

This is not DevEco or device evidence. It does not establish ArkTS/API-checker
compatibility, a debug or release HAP, signing, installation, hardware decode,
HUKS-backed secure pairing, Host interoperability on a HarmonyOS device, or
MatePad behavior. Controller-specific input still needs the MatePad Mini
acceptance matrix before being claimed as device-verified.

## 2026-08-20 HarmonyOS device-gate manifest validator

The MatePad Mini runbook now requires a redacted `harmony-device-gates.json`
manifest beside the raw evidence. The validator is intentionally stricter than
the portable source checks: a passing manifest must bind the clean repository
commit/tree, DevEco/Harmony SDK and HDC versions, a signed release HAP and
signature hash, MatePad Mini HarmonyOS identity, Protocol v1 Host build, and
explicit pass evidence for every remaining real-device gate. Android platform
records, non-MatePad device records, missing HAP/signing hashes, dirty source
state, and blocked gates fail closed.

```text
python3 scripts/harmony_device_gate.py --template
  PASS: prints a redaction-safe manifest template only
make harmony-device-gate EVIDENCE_DIR=/path/to/evidence
  PASS only when /path/to/evidence/harmony-device-gates.json has every required
  real-device gate marked pass with evidence references that exist under
  /path/to/evidence
python3 scripts/harmony_device_gate.py --allow-blocked /path/to/evidence/harmony-device-gates.json
  STRUCTURE-ONLY: may document blocked readiness, but is not acceptance evidence
```

The strict path validates evidence references with `--evidence-root`; direct
strict script invocations default the evidence root to the manifest directory.
Every `pass` gate reference must be a local relative artifact file below the
evidence directory. Missing artifacts, directories, absolute paths, URLs, and
`..` traversal fail closed. `--allow-blocked` intentionally skips file-existence
checks so blocked readiness manifests can be archived without being mistaken for
acceptance.

This validator does not run DevEco, install a HAP, pair a device, decode media,
or interoperate with the Host. It exists to keep those external observations
complete and correctly scoped once a MatePad Mini and signing environment are
available.

## 2026-08-21 HarmonyOS readiness preflight

The HarmonyOS path now has a read-only readiness preflight before the final
device-gate manifest. It records DevEco Studio, Hvigor/OHPM/HDC versions,
redacted HDC target identity, MatePad Mini-class device properties, signed HAP
hashes and checksum linkage, signing-certificate hash, and Protocol v1 Host
build identity into `harmony-readiness.json`. The command exits 2 with a
machine-readable `verdict: blocked` while any prerequisite is missing. This is
intentional fail-closed behavior and does not claim ArkTS compilation, HAP
installation, secure pairing, authenticated records, hardware decode, Host
interoperability, input, soak, external latency, or MatePad Mini acceptance.

```text
make harmony-readiness EVIDENCE_DIR=/path/to/evidence
  PASS only when DevEco/Hvigor/OHPM/HDC, signed HAP/checksums/signature hash,
  Host build identity, and one MatePad Mini-class HDC target are present
python3 scripts/harmony_readiness.py --output /tmp/harmony-readiness.json
  BLOCKED in ordinary CI or local environments without DevEco/HAP/MatePad Mini
```

The preflight output uses `schema_version: vibescreen.evidence/v1` and is covered
by `tools/schemas/harmony-readiness.schema.json`. The Harmony workflow runs a
blocked dry run and rejects script or schema drift, but it still labels the job
as portable/no-HAP evidence only.

## 2026-08-21 HUKS secure-pairing source gate

The Harmony secure-pairing portable path now requires a HUKS-backed security
profile before it can produce a `PairingRequest`. The accepted profile is
fixed to non-exportable P-256 signing keys, HUKS-bound credential storage, a
persistent identity, and an Authority device ID matching the signed device
identity. Stored secure-pairing records are version 2 and must persist that
profile; legacy version-1 records, no-HUKS providers, exported-key profiles,
profile/device mismatches, expired pairing results, replayed control records,
and revoked credentials fail closed in portable tests.

A separate redacted evidence contract now validates the future MatePad Mini
HUKS run:

```text
python3 scripts/harmony_secure_pairing_gate.py --template
  PASS: prints a redaction-safe manifest template only
python3 scripts/harmony_secure_pairing_gate.py --allow-blocked docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-huks-secure-pairing-blocked/harmony-secure-pairing.json
  STRUCTURE-ONLY: blocked HUKS/DevEco/MatePad/Authority evidence is well formed
make harmony-secure-pairing-gate EVIDENCE_DIR=/path/to/evidence
  PASS only when /path/to/evidence/harmony-secure-pairing.json marks every
  HUKS, PairingOffer/Request/Result, issue/revoke, expiry/replay, old-peer,
  no-HUKS, and Authority/Signaling check as pass with redacted evidence
```

The top-level Harmony device manifest also requires the
`huks_backed_secure_pairing` gate to reference a nested
`harmony-secure-pairing.json` with a matching status. This keeps generic device
logs from closing the security gate without the specific HUKS and
service-admission proof. The blocked record for this work is under
`docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-21-huks-secure-pairing-blocked/`.

This is still not DevEco or device evidence. It does not establish HUKS API
behavior, private-key non-exportability on a real tablet, signed HAP install,
QR/controller UX, authenticated transport packets, production Authority
deployment, public-network behavior, Host interoperability, or MatePad Mini
acceptance.

## 2026-08-21 AVCodecKit hardware-decode preflight

The HarmonyOS H.264/HEVC hardware decode gate now has a dedicated structured
preflight and manifest validator. A passing manifest must bind a clean source
commit/tree, DevEco/Harmony SDK/Hvigor/OHPM/HDC provenance, a signed
`dev.vibescreen.harmony` HAP and signature hash, a MatePad Mini HarmonyOS
identity, a Protocol v1 Host build, and both codec records marked pass. For each
of `h264` and `hevc`, the codec record must cover decoder capability, hardware
decoder identity, XComponent surface, buffer callback, Protocol v1 media header,
PTS preservation, input push, output render, output buffer free, flush,
reconfigure, EOS, and release.

```text
python3 -m vibescreen_evidence.harmony_avcodec_preflight --template
  PASS: prints a redaction-safe blocked template only
make harmony-avcodec-preflight EVIDENCE_DIR=/path/to/evidence
  BLOCKED in this environment when DevEco/HDC/HAP/MatePad evidence is absent
make harmony-avcodec-validate EVIDENCE_DIR=/path/to/evidence
  PASS only when /path/to/evidence/harmony-avcodec-preflight.json has both
  hardware codec records marked pass with the required lifecycle evidence
PYTHONPATH=tools python3 -m vibescreen_evidence.harmony_avcodec_preflight \
  --allow-blocked --validate /path/to/evidence/harmony-avcodec-preflight.json
  STRUCTURE-ONLY: may document blocked readiness, but is not acceptance evidence
```

The main Harmony device-gate manifest now requires `h264_hardware_decode` and
`hevc_hardware_decode` pass entries to reference `harmony-avcodec-preflight.json`.
That reference does not itself prove hardware decode; it ensures the broader
device gate cannot close without the per-codec AVCodecKit manifest.

A local blocked record is committed under
[`evidence/2026-08-21-harmony-avcodec-preflight-blocked`](evidence/2026-08-21-harmony-avcodec-preflight-blocked/README.md).
It records missing DevEco/HDC/Hvigor/OHPM/HAP/MatePad prerequisites and keeps
both H.264 and HEVC hardware decode gates open. Android, emulator, simulator,
portable source, and source-only static results remain invalid substitutes.

## 2026-08-23 current-base owner gate

The Phase 4 README owner surface for DevEco build, signed-HAP install,
hardware decode capability, HUKS secure pairing, authenticated transport,
resume-capable Host interoperability, and MatePad Mini acceptance is now
represented by a read-only current-base aggregate gate. It consumes
`harmony-readiness.json` and `harmony-device-gates.json`, then writes
`harmony-current-base-gate.json` with separate owner checks for:

- `deveco_build`: requires passing `deveco_sdk_and_api_checker` evidence that
  references DevEco/Hvigor/API-checker readiness plus DevEco/HAP/MatePad
  readiness;
- `hap_sign_install`: requires passing `signed_release_hap` and
  `hap_install_launch` device gates, evidence that references signed-HAP
  lifecycle artifacts, plus DevEco/HAP/MatePad readiness;
- `hardware_decode_capability`: requires passing `h264_hardware_decode` and
  `hevc_hardware_decode` device gates, evidence that references
  `harmony-avcodec-preflight.json`, plus DevEco/HAP/MatePad/Host readiness;
- `huks_secure_pairing`: requires passing `huks_backed_secure_pairing` and
  `credential_revocation_replay` with HUKS/secure-pairing evidence plus
  DevEco/HAP/MatePad/Host readiness;
- `authenticated_transport`: requires passing
  `authenticated_transport_records` with authenticated-record evidence plus
  DevEco/HAP/MatePad/Host readiness;
- `host_resume_interop`: requires passing `host_protocol_v1_interop`,
  `resume_background_foreground`, `resume_network_roam`,
  `resume_host_restart`, `no_old_epoch_render`, and
  `resume_capable_host_interop` device gates, evidence that references
  `harmony-host-interop-preflight.json`, plus DevEco/HAP/MatePad/Host readiness.
- `matepad_acceptance`: requires passing permission, input, eight-hour soak,
  and external latency device gates with MatePad acceptance package evidence.

```text
make harmony-current-base-gate EVIDENCE_DIR=/path/to/evidence
  PASS only when both input manifests are present and every owner gate is backed
  by real MatePad Mini device evidence
PYTHONPATH=tools python3 -m unittest tools.tests.test_harmony_current_base_gate -v
  PASS: verifies missing DevEco/HAP/MatePad/Host inputs stay blocked, Android
  substitution fails, generic cross-domain evidence cannot close owner gates,
  missing security, transport, MatePad, or resume evidence stays blocked, and a
  complete synthetic manifest can reach pass
```

This gate does not run DevEco, install or launch a HAP, pair a device, decode
media, interoperate with the Host, or create MatePad Mini evidence. Without
DevEco, MatePad Mini hardware, signed HAP metadata, HUKS/authenticated
transport artifacts, and Host resume evidence, its correct result is `blocked`
and the README gates remain open.

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
- confirmation/correction of the commercial AVCodecKit declarations and a
  passing `harmony-avcodec-preflight.json` covering buffer callback, memory
  write, PTS, render/free, flush, reconfigure, EOS, and release for both H.264
  and HEVC;
- debug and signed release `assembleHap`, HAP contents/permissions/signature,
  SHA-256, install, in-place upgrade, rollback behavior, and uninstall cleanup;
- Asset Store client/host record CRUD and malformed-version removal;
- XComponent surface creation/destruction across rotation/background/foreground.

## Host and device gates

- real upgrade/HostHello/session/display/video/control/media interoperability;
- secure PairingOffer/Request/Result proof, credential issue/revoke, replay and expiry;
- H.264 and HEVC hardware render with decoder identity evidence bound to the
  structured AVCodec preflight manifest;
- multi-touch, Up/Cancel, keyboard/HID/modifiers, pointer/buttons, wheel/trackpad,
  stylus (base pressure/tilt and extended eraser/barrel/proximity under
  capability gating), focus, safe area, letterbox, and both orientations;
- controller-specific input: the Harmony portable source now advertises
  `CAPABILITY_CONTROLLER = 26`, encodes lifecycle-scoped `ControllerEvent`,
  waits for accepted CONNECTED `InputAck`, and sends all-zero neutral
  DISCONNECTED release controls before active controller teardown or resume.
  DevEco/API-checker, HAP, Host interoperability, and device evidence remain
  absent;
- background/foreground, permission denial, Wi-Fi loss/restore/roam, host restart,
  bounded reconnect, resume-result behavior, and no old-epoch render;
- MatePad Mini eight-hour thermal/power/RSS/frame-drop soak and external-camera
  glass-to-glass/input latency. Android evidence is never a substitute.
