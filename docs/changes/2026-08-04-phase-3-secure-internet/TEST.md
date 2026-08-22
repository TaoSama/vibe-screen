# Phase 3 verification plan

## Evidence rules

Every result records UTC time, repository revision or tree hash, host/client
version, artifact SHA-256, toolchain versions, configuration **without secrets**,
network topology, direct/relay route, and raw log/evidence paths. A build, fake
engine, emulator, or loopback result may prove its own layer only; none
substitutes for the planned Xiaomi 13 (2211133C) Internet end-to-end gate. The existing
Nubia P0110 record is identified separately and is never relabeled as Xiaomi
evidence.

The shared Android endpoint is lease-controlled. Before any `adb connect`,
install, force-stop, launch, device query, media-port probe, or Mac host stream
start, require the soak and Android coordination locks to be absent and atomically
hold `/tmp/vibe-screen-device-internet.lock`. The acceptance script requires a
regular `0600` structured lease with exact `owner`, independent live holder
`pid`, task and source `commit` fields. It checks the initial inode and bytes plus
all other device locks before and after every ADB subprocess. Each check is
fsync-appended to a new machine-readable JSONL journal without recording the
owner value or command arguments. A missing/replaced lock, changed owner bytes,
dead holder, other device lock, or changed journal invalidates the complete run;
no parameter disables these checks.

## Reproducible local checks

Run current repository checks first:

```bash
make protocol
make phase3-test
make phase3-authority-container-test
make baseline-macos-build
make baseline-macos-test
make baseline-android-test
make baseline-android-apk
```

`phase3-authority-container-test` has a 15-minute CI timeout. It builds the
non-root scratch image, validates the local and production-shaped Compose models,
starts a real PostgreSQL, verifies ordered migration and readiness, creates and
authorizes a session, restarts Authority without losing that admission, then
proves database-outage liveness/readiness separation and storage failure before
recovery. It also checks the runtime user, read-only root filesystem, dropped
capabilities, and generated-secret absence from container logs.

This local container gate does not prove production PostgreSQL TLS, managed
secret delivery, NTP offset monitoring, PITR/restore, public ingress, automatic
issuance, active coturn allocation disconnect, or multi-node behavior. Those
remain explicit production or end-to-end gates. When
`VIBE_AUTHORITY_TEST_DATABASE_URL` points at a disposable PostgreSQL database,
`services/signaling` also runs a process integration test that starts real
Authority, signaling, and relay binaries, creates authority-backed signaling
sessions, obtains authority-admitted relay credentials, invalidates one session,
revokes the client device at Authority, then proves both signaling role access
and future relay credential admission fail closed.

`make phase3-test` also runs static production-profile checks for the Phase 3
relay/Authority deployment files. These checks prove only repository configuration
invariants: production relay and Authority profiles require digest-pinned images,
secrets are file-backed, relay HTTP remains loopback-only, and the coturn
production profile retains TLS, quota, bounded relay-port, and private/internal
peer-deny policy. They do not start a public relay, inspect real secret delivery,
or prove public reachability. The same target validates the structured coturn
snapshot reconciliation helper: strict JSON input, loopback-only plaintext
Authority URLs, exact token-source selection, and fail-closed external disconnect
execution when Authority reports unauthorized or conflicting active source
allocations. That helper test does not prove a production coturn exporter,
scheduled loop, provider billing reconciliation, or real data-plane allocation
termination.

Record failures as failures. In particular, an unavailable XCTest/full-Xcode or
device environment is not a waiver. When production WebRTC/crypto/signaling code
is added, add deterministic Make targets rather than relying on undocumented IDE
steps.

## Test matrix

| Layer | Required evidence |
| --- | --- |
| Static | protocol format/lint/build/breaking; dependency lock/SBOM/license audit; secret scan; unsafe-log scan |
| Compatibility | Swift/Kotlin golden bytes, unknown fields, old v1 peer without Phase 3 capabilities, required-capability rejection |
| Crypto | transcript and KDF known-answer vectors; AEAD/AAD mutation; nonce uniqueness; cross-role/channel/session/key separation |
| Identity | pair, expiry, single use, wrong identity, downgrade, rotation overlap/rollback, revocation persistence |
| Replay | duplicate, too old, reordered media, reordered control, cross-channel/session/epoch/key, crash/restart counter safety |
| Transport | direct ICE, forced TURN, IPv4/IPv6, UDP-blocked/TCP-TLS relay, control/media/audio/bulk channel semantics, payload/backlog/frame caps |
| Recovery | Wi-Fi/cellular/VPN changes, route changes, ICE restart backoff, signaling loss, TURN loss, process restart, old-epoch injection |
| Adaptation | WebRTC Internet transport only (USB/LAN keep manual client-driven presets). Offline: fast-drop/slow-rise hysteresis with jitter reset, host-only non-finite/zero-bitrate/missing-RTT conservative handling, even dimensions without upscaling, user-baseline upper-bound clamp, latest-proposal-wins queuing, rotation serialization, stale owner/generation rejection, retry after local or peer rejection, host apply encoder/capture + media gate → `VideoConfig` ACK → keyframe/resume, rejection rollback and host-apply/ACK/rollback-timeout fail-closed. Android policy tests cover hysteresis and neutral reset, not those host telemetry edge cases. Not proved: real ScreenCaptureKit→Android decoder continuity, public Internet, real remote TURN, real network fluctuation, handoff, soak |
| Relay operations | short credential expiry, authority-backed allocation admission before credential issuance, allocation/peer/bandwidth/byte/concurrency quotas, rate limits, alerts, spend reconciliation |
| Privacy | packet capture, logs/crash/evidence/telemetry scan, retention and deletion drill |
| Android device E2E | install, pair, direct stream, relay stream, touch/keyboard, network handoff, revoke, reconnect, two-hour soak |
| Latency | external-camera direct and relay raw samples; never infer glass-to-glass from unsynchronized clocks |

## Protocol compatibility cases

1. Current peer with current peer negotiates all mutually implemented security
   capabilities and algorithms.
2. A legacy Protocol v1 peer lacking Phase 3 capabilities is rejected for Internet
   mode with an actionable error; it is not downgraded to LAN TCP.
3. Unknown additive fields are preserved/ignored as specified, but an unknown
   required algorithm/capability fails closed.
4. Field order and unknown-field differences do not change canonical signed/AAD
   bytes; canonicalization has cross-language fixtures.
5. `session_epoch`, `key_epoch`, revocation sequence, sequence number, and
   `config_epoch` boundary values and overflow behavior are tested.

## Network simulation

Use a documented Linux network namespace/router or equivalent reproducible
network harness between endpoints. Archive the script/tool version and exact
parameters. Cover at least:

| Scenario | Suggested impairment | Expected behavior |
| --- | --- | --- |
| Healthy | 20–50 ms RTT, <0.5% loss | highest allowed stable profile, direct preferred |
| Moderate | 100 ms RTT, 2% loss, 10 Mbps | bounded downgrade without oscillation |
| Weak | 250 ms RTT, 5% loss, 4 Mbps | lower resolution/FPS/bitrate, current input/control preserved |
| Severe burst | 400 ms RTT, 10% burst loss, reordering | bounded queue, keyframe recovery, actionable state |
| Bandwidth step | 20→3→12 Mbps | fast downgrade, conservative upgrade |
| NAT restricted | no viable direct pair | authenticated TURN fallback |
| UDP blocked | TCP/TLS relay only | connects or reports explicit unsupported route |
| Path handoff | Wi-Fi→cellular→Wi-Fi/VPN | ICE restart, new epoch, no stale media/input |
| Relay loss | kill selected TURN path | bounded failover/recovery, no plaintext fallback |

Simulation proves policy and transport behavior, not physical glass-to-glass
latency or a mobile carrier path.

## Security negative tests

- fuzz length-delimited protobuf, signaling JSON/binary framing, SDP/candidate
  counts and sizes, and encrypted packet headers;
- flip/strip/reorder transcript fields and algorithm/capability lists;
- replay pairing offers, rotation nonces, revocations, and encrypted packets;
- restore an older application database/backup and verify key/revocation rollback
  is rejected;
- crash before/after counter/epoch persistence and prove no AEAD nonce repeats;
- attempt active-session takeover during ICE restart and candidate injection;
- exhaust control backlog, media frame size, TURN allocation, authentication, and
  reconnect budgets;
- scan `logcat`, unified logs, crash reports, packet captures, evidence manifests,
  and relay telemetry for known seeded secrets/plaintext.

## Android Internet evidence template

The current-base replacement owner for the historical/withdrawn Android interop
record is `scripts/phase3/android_current_base_interop_gate.py`, exposed through
`make phase3-android-current-base-interop-gate`. The gate is intentionally
fail-closed and has three proof profiles:

| Profile | What can pass | What remains open |
| --- | --- | --- |
| `product-interop` | Current clean `HEAD`, `nubia P0110 / pacific / Android 16 / SDK 36`, direct plus forced local coturn route reports from `android_product_session_interop_acceptance.py`, one stable device lease, Protocol v1, AES-256-GCM control/media, Android UI instrumentation, and synthetic config/keyframe/delta media | Real ScreenCaptureKit/CGDisplayStream, Android MediaCodec output, public Internet, handoff, latency, and soak |
| `real-capture` | Current clean `HEAD`, the same P0110 identity, direct plus forced local coturn route reports, one stable device lease, Protocol v1, AES-256-GCM control/media, Android UI instrumentation, authenticated touch, plus `real_screen_capture`, `screen_capture_kit`, `videotoolbox_output`, `android_mediacodec_decode`, `mediacodec_first_output_frame`, `continuous_fps_and_decode_latency`, and `disconnect_reconnect` assertions with matching `evidence_boundaries` set to `pass` | Public NAT/TURN and carrier/remote-route evidence |
| `public-internet` | Everything in `real-capture` plus `public_internet_path` and `public_nat_or_remote_turn` assertions | Release still also needs any separate soak, latency, revocation, multi-node, and operations gates called out below |

The default Make target uses `PHASE3_ANDROID_INTEROP_GATE_PROFILE=real-capture`
so local synthetic product evidence and the historical 2026-08-05 P0110 record
remain blocked by default:

```bash
make phase3-android-current-base-interop-gate \
  PHASE3_ANDROID_INTEROP_EVIDENCE=/absolute/path/to/acceptance.json
```

Use `PHASE3_ANDROID_INTEROP_GATE_PROFILE=product-interop` only when the intent is
to replace the historical synthetic-media product-interop record on current
source without claiming real capture, Android MediaCodec, public Internet,
handoff, latency, or soak. A `blocked` output from this gate is valid evidence
of the current blocker; it is not a pass. The gate rejects any `product-interop`
route report that marks real-capture, public-Internet, handoff, latency, soak,
or other out-of-profile assertions or boundaries as `pass`. The real-capture and
public-Internet profiles require their matching `evidence_boundaries` entries to
be `pass`, and the combined direct/relay report must prove the same ADB lease
identity through the route-level `adb_gate` fields rather than relying only on
the top-level `same_device_lease_holder` boolean.

Store evidence under a new immutable run directory such as:

```text
docs/changes/2026-08-04-phase-3-secure-internet/evidence/
  2026-08-04T120000Z-xiaomi12-internet/
    manifest.json
    commands.txt
    adb-devices.txt
    device-properties.txt
    artifact-sha256.txt
    host-version.txt
    client-version.txt
    direct-session.jsonl
    relay-session.jsonl
    network-handoff.jsonl
    replay-revocation.jsonl
    soak-summary.json
    logcat-redacted.txt
    host-log-redacted.txt
    packet-capture-notes.md
    latency-method.md          # copy or link docs/runbook/latency-measurement.md
```

Start by proving device identity, not merely that some ADB endpoint responded:

```bash
test ! -e /tmp/vibe-screen-device-android.lock
export ADB_ENDPOINT='EP0110PZ0B9110300B'
adb -s "$ADB_ENDPOINT" devices -l
adb -s "$ADB_ENDPOINT" shell getprop ro.product.manufacturer  # nubia
adb -s "$ADB_ENDPOINT" shell getprop ro.product.model         # P0110
adb -s "$ADB_ENDPOINT" shell getprop ro.product.device        # pacific
adb -s "$ADB_ENDPOINT" shell getprop ro.build.version.release # 16
adb -s "$ADB_ENDPOINT" shell getprop ro.build.version.sdk     # 36
```

Use `adb -s EP0110PZ0B9110300B` explicitly for the Nubia path. The archived
identity must be `nubia P0110 / pacific / Android 16 / SDK 36`; it must not be
reported as Xiaomi 13/fuxi evidence.

Then record the exact APK and installed version:

```bash
shasum -a 256 path/to/vibe-screen.apk
adb -s "$ADB_ENDPOINT" install -r path/to/vibe-screen.apk
adb -s "$ADB_ENDPOINT" shell dumpsys package dev.telemachus.display
```

The run log must state, with timestamps and route evidence:

1. how signaling and TURN endpoints were configured without recording secrets;
2. successful pairing and identity fingerprints confirmed by the tester;
3. direct Internet stream video plus touch and keyboard input;
4. forced TURN stream with proof that the selected candidate pair is relay;
5. Wi-Fi/cellular or independently routed network handoff and recovery duration;
6. disconnect/reconnect with increased session epoch and rejected old packet;
7. key rotation, active revocation, direct and relay reconnect rejection;
8. two-hour mixed-route soak with RSS, queue, loss, RTT, FPS, bitrate, relay bytes,
   ICE restarts, drops, thermal/battery, and latency series;
9. redaction/secret scan result for every archived artifact.

If cellular control cannot be automated over remote ADB, document the manual
device action and correlate it with monotonic host/client/relay events. Do not
claim a network handoff based only on toggling UI.

## Current evidence and unproved items

At document creation, repository policy/unit tests may prove schema validation,
channel separation, ICE-restart policy, bounded queues, relay accounting, and
adaptation decisions. The macOS `AdaptiveMediaPolicy` unit tests cover
fast-drop/slow-rise hysteresis, boundary jitter without oscillation, non-finite
loss/RTT and zero-bitrate conservative fallback, and missing-RTT handling.
Android `AdaptiveVideoPolicy` tests cover its fast-drop/slow-rise thresholds and
neutral-sample reset. The host `InternetProductSession` covers the
host-apply and `VideoConfig` ACK gates, `config_epoch` enforcement, bounded
host-apply/ACK/rollback deadlines, even non-upscaled dimensions,
latest-proposal-wins queuing, rotation serialization (including resuming a
deferred rotation after local rejection), stale owner/generation isolation, and
retry after local or peer rejection. These map to focused codec, session, and
transport-policy unit tests rather than device evidence. The client
`InternetProductSession` covers strict `config_epoch` increase, concurrent
transaction rejection, decoder-effect commit before ACK, and 5-second
video-configuration timeout fail-closed. These are offline, layer-local results.
Go tests also exercise the standalone cryptographic core. They do not prove the
production composition of WebRTC, platform/product crypto, signaling and TURN,
Internet connectivity, or E2E security. The production host composition wires
the adaptive encoder/capture-application callback, but this path is verified
only through offline build and unit/self-tests, so no real
ScreenCaptureKit→Android decoder continuity, public-Internet, real
remote-TURN, real network-fluctuation, handoff, or soak evidence exists.

No Xiaomi 13 (2211133C) Phase 3 Internet acceptance evidence is recorded here. A narrower
Nubia P0110 local direct/forced-coturn product-session record is listed below;
it does not close the target Xiaomi, public-Internet, real-capture, handoff,
latency, or soak criteria.

Local verification on 2026-08-04 and 2026-08-05 proved the following layers in
recorded shared-tree snapshots. A result applies only to the layer and tree state
named by that run:

- `make protocol`: format, lint, build, and v1 breaking check passed;
- `go test -race ./... && go vet ./...` in `packages/security`: passed;
- `go test -race ./... && go vet ./...` in `services/relay`: passed after the
  concurrent relay source/test changes converged;
- Phase 3 Python suite: 66 tests passed, including repository endpoint privacy,
  fail-closed device-lock handling, and build/source evidence binding;
  security-vector CLI passed
  24 vectors, including direction reflection and global revocation sequencing;
- Android clean `./gradlew --no-daemon clean testDebugUnitTest lintDebug
  assembleDebug compileDebugAndroidTestKotlin auditReleaseDependencies` passed
  with 265 JVM tests and zero failures/errors/skips. The security tests cover
  paired-host lease signature mutation, reserved maximum epochs, stale durable
  cipher epochs, monotonic identity reauthorization, restart-safe credential and
  revocation cleanup, best-effort close aggregation, and generation-scoped route
  changes with a bounded candidate-resolution timeout and one ClientHello. New
  cases cover pairing-record partial persistence, post-persist business failure,
  deletion failure and cross-restart metadata/secret cleanup. Short-disconnect
  route interleavings restore ACTIVE, heartbeat and touch without a second
  ClientHello, while fresh-session and FAILED late callbacks keep the old owner,
  heartbeat and touch disabled. Initial and runtime rotation values reach the
  product decoder configuration. `compileDebugAndroidTestKotlin` and the debug
  APK build passed.
  Authenticated revocation tests additionally cover durable pending admission
  before close, close while formal tombstone persistence is in flight, formal
  persistence failure followed by restart/retry, pending-barrier failure with a
  process-scoped owner recreation, successful retry through final close,
  different-pairing metadata overwrite rejection, already-open pairing-dialog
  rejection, deterministic pairing-commit/revocation-reserve linearization,
  every old-pairing revocation stage, owner-aware legacy/current marker recovery,
  coexisting pairing/authenticated-revocation markers across simulated restart,
  and old-cleanup/new-owner upgrade recovery without profile, binding, or secret
  cross-deletion; same-owner cleanup still deletes every owned resource. The
  upgrade cases instantiate the production `InternetSessionProfileStore` with
  in-memory preference/secret adapters, call its real
  `retryPendingRevocationCleanup` entry point, and assert marker progression,
  restart retry, profile secret and deferred-queue state. Legacy writer,
  ready/EOF and fresh-fallback regressions passed five independent rerun rounds.
  `processReleaseMainManifest` also passed and the merged release
  manifest sets `usesCleartextTraffic=false`;
- Android `./gradlew auditReleaseDependencies`: passed the fixed AAR, Gson,
  SBOM and bundled WebRTC/Gson notice hashes; release packaging depends on this
  task;
- macOS `swift build`: an initial run failed while concurrent Phase 3 files were
  inconsistent; after the owning edits converged, a fresh rerun passed. The
  historical local `swift test` command failed before execution because XCTest
  was unavailable in that selected developer environment. The 2026-08-06 main
  Xcode execution snapshot is recorded separately below.
- `services/signaling make verify`: format, vet, race tests and a real child-process
  offer/answer/candidate exchange passed; PostgreSQL store tests additionally
  cover migration/readiness, restart-durable routing, expiry, long-poll wakeup,
  waiter caps, and concurrent capacity when `VIBE_SIGNALING_TEST_DATABASE_URL` is
  set. Its container was not built because Docker is unavailable.
- macOS production WebRTC loopback and a real local signaling-process self-test
  passed for SDP/ICE and both data channels. The binary links M150 WebRTC.
- A fresh local M150 loopback rerun passed with direct UDP, bidirectional reliable
  ordered control, unordered zero-retransmit media, and ICE restart. The signaling
  self-test correctly failed closed when its four explicit session credentials
  were absent; a separately configured run is the recorded passing service test.
- The reproducible local runner passed a real signaling process using both direct
  UDP and `forceRelay=true`. Local coturn 4.16.0 selected
  `relay(local=relay,remote=relay,protocol=udp)` and delivered application
  AES-256-GCM control/media records bidirectionally. The forced selected
  libwebrtc relay candidate pair is the current runner's TURN proof; the earlier
  standalone `turnutils` 3/3 datagram smoke is historical and is not inferred
  from the current runner.
- `services/relay/integration/test-turn-rest.sh` passed short-term control-plane
  credential issuance, authenticated coturn allocation, ChannelBind and relayed
  messages. A deterministic one-socket TURN helper filled `user-quota=2` with
  two exact allocations whose credentials used different sessions and expiries;
  the next allocation received 486. One holder then sent an authenticated
  Refresh with `LIFETIME=0`, after which a new allocation succeeded and was also
  released. The complete check passed five consecutive runs after removing the
  scheduler-sensitive multi-allocation client assumption.
- `services/relay/integration/test-turn-peer-acl.sh` parsed the production ACL
  and used authenticated CREATE_PERMISSION requests to prove explicit 403 denial
  for private, CGNAT, link-local and internal peers, including IPv6 loopback; a
  public IPv4 control remained allowed.
- The relay control plane's race suite passed after separating usage and metrics
  credentials, enforcing an exact Bearer scheme, exporting current-day estimated
  cost as a gauge, and syncing the state directory after atomic replacement.
- `scripts/phase3/coturn_reconcile.py` has focused unit coverage for strict
  structured snapshot ingestion, sanitized token-source selection, loopback-only
  plaintext Authority URLs, Authority response validation, and fail-closed
  handling of unauthorized/conflicting active allocations when no disconnect
  executor exists or when the executor fails. This is a local contract test, not
  production coturn exporter or data-plane disconnect evidence.
- Signaling issuer-only invalidation passed store, HTTP, race and repeated
  real-process tests: invalidation is idempotent, destroys role tokens and queued
  payloads, wakes long polls, and retains only the request-ID tombstone until
  expiry.
- Relay revoke/issuance serialization and revoked-device rejection passed race
  and persistence tests. New credentials fail closed after revocation. Authority
  PostgreSQL tests now also prove account suspension, device revocation, and
  signaling invalidation close the authority relay-allocation ledger while later
  coturn usage for those revoked, suspended, expired, or closed allocations
  fails closed without advancing counters. The coturn
  integration still relayed 10/10 test messages; it did not prove termination of
  an allocation that was already active when the control-plane revoke occurred.
- Phase 3 Python tests cover fail-closed device-lease handling and evidence
  revision recording. These tests do not access the Android endpoint.
- Swift and Kotlin pairing implementations have local happy-path, one-time,
  expiry, downgrade, mutation, strict-wire, and protected-secret-storage tests;
  the Android pairing target passed 8/8 tests. They have not yet completed a real
  cross-language QR exchange. Swift and Kotlin do share a passing hard-coded
  product-session bound-context known-answer value. The macOS package built;
  its XCTest cases did not execute in that historical Command Line Tools-only
  environment.
- Platform lifecycle tests cover peer-scoped durable epoch reservation, rollback
  rejection, signed targeted revocation, tombstone persistence, and pairing-secret
  deletion failure/retry. Added deterministic XCTest source covers an N open
  transaction latched across a concurrent N+1 reservation, post-persist pairing
  business failure plus deletion failure across coordinator restart, and lease
  issuance across concurrent callers and authority restart while ignoring an
  abnormal caller epoch. These XCTest cases executed in the 2026-08-06 main CI
  run recorded below; the local Command Line Tools environment remains unable
  to run them.
- The macOS executable Internet self-test keeps a selected route explicitly
  unknown until complete candidate-pair stats arrive and fails closed on timeout;
  the loopback self-test still selected a real direct host/host UDP pair after
  the change. It also covers multi-device revoked-identity epoch floors and
  restart-safe secret-cleanup state. The lease self-test matches Android's
  canonical digest, mutates every signed field, rejects malformed input, and
  signs/verifies with a temporary real Keychain identity. It additionally proves
  pairing-scoped durable authority allocation across restart/concurrency, rejects
  stale cipher seal/open after the durable epoch advances, and uses a deterministic
  latch to prove N+1 reservation waits while N open owns the durable epoch lock.
  The historical local run could not execute XCTest, while the 2026-08-06 main
  CI run did.
- The local product slice passed in both modes:
  `run_local_e2e.py --mode direct --slice product` and
  `run_local_e2e.py --mode relay --slice product --skip-build`. Both traversed
  `InternetProductSession`, the protected production M150 adapter and real
  signaling; relay selected forced local coturn. The synthetic Protocol v1 device
  completed hello/session acceptance at epoch 1, video-config acknowledgment at
  config epoch 1, then runtime `DisplayChanged` plus a 90-degree `VideoConfig` at
  config epoch 2 and acknowledgment before post-rotation media. Touch/control,
  keyframe plus delta media, application AEAD, and the seeded-plaintext log scan
  passed. Direct reported
  `direct(local=host,remote=host,protocol=udp)`; forced TURN reported
  `relay(local=relay,remote=relay,protocol=udp)`. No independent `turnutils`
  datagram result is claimed by this runner. This did not start capture/UI and
  is not Android, real screen/input, or packet-capture evidence.
- The current worktree updates that local product slice so post-rotation media is
  real VideoToolbox-generated HEVC keyframe and delta payloads sent through the
  production WebRTC media DataChannel to the same synthetic Protocol v1 device
  peer. The input frames are synthetic `CVPixelBuffer`s and the check still does
  not start ScreenCaptureKit/CGDisplayStream, instantiate Android MediaCodec, or
  produce Android UI evidence.
- The prior curated Android interop record remains
  [withdrawn](evidence/android-product-interop.json). Its claimed source commit
  does not exist in this repository, and raw host output, instrumentation output,
  runtime timestamps, exact commands/environment, artifact provenance,
  candidate-pair/E2EE logs, and UI source files were not retained. No pass result
  is recoverable from the summary, and none is inferred or reconstructed.
- A historical combined Android acceptance PASS is archived under
  [`evidence/2026-08-05-nubia-p0110-internet/`](evidence/2026-08-05-nubia-p0110-internet/README.md).
  Its clean, reachable source is
  `597518f948075e396352bc353afcec01a30303f3`; the device boundary is only
  `Nubia P0110 / pacific / Android 16`. Direct and forced local coturn used the
  same lease snapshot and controlled APK/host/signaling artifacts. Each route
  recorded 24 ADB subprocesses and 48 valid before/after gate records. The real
  Android app passed Internet tab/route selection, signed pairing, strict signed
  lease import, local revoke/re-pair and secure-dialog checks. The Android M144
  and macOS M150 production adapters passed Protocol v1, AES-256-GCM control and
  media, synthetic config/keyframe/delta media, and authenticated touch through
  direct and selected relay candidate pairs. Earlier failed attempts are not
  included.

That pass is not ScreenCaptureKit, real display content, visible Mac input,
Android rotation, disconnect/reconnect or network-handoff evidence. It also does
not prove negative lease cases through the UI, cross-service revocation, public
Internet/STUN/TURN or carrier/CGNAT traversal, packet capture, latency, or soak;
those release gates remain open. It is not current-source evidence. Xiaomi 13
(2211133C) acceptance also remains open. A future current-source replacement
must pass `scripts/phase3/android_current_base_interop_gate.py` for the intended
profile; otherwise the replacement state is `blocked`.

- A 2026-08-18 attempt to re-verify current-main real display capture through
  the USB media path on `Nubia P0110 / pacific / Android 16` is archived as
  [`BLOCKED`](evidence/2026-08-18-nubia-p0110-current-main-real-media-blocked/README.md).
  The Android and macOS artifacts built from clean commit
  `5f7a4c394ac6f33b75636b17e12d15b425a0688b`, and the Android app was updated
  only with `install -r`, but the packaged Host had no macOS Screen Recording
  permission and never opened its listener. No capture frame, VideoToolbox
  output, Protocol v1 media session, MediaCodec first output, FPS/decode result,
  or successful-session reconnect was produced. This environment block does not
  change any open Phase 3 release gate.

- A 2026-08-20 local readiness run on clean main commit
  `18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee` is archived under
  [`evidence/2026-08-20-local-phase3-readiness/`](evidence/2026-08-20-local-phase3-readiness/README.md).
  It passed `make protocol`, `make phase3-test`,
  `make phase3-local-synthetic-product-e2e`,
  `make phase3-authority-container-test`,
  `services/relay/integration/test-turn-rest.sh`, and
  `services/relay/integration/test-turn-peer-acl.sh`. The local product E2E
  public summaries are bound to that commit and source fingerprint, prove
  direct UDP plus forced local coturn relay candidate-pair selection through the
  real signaling process and production macOS WebRTC adapter, and explicitly
  record `local_loopback_only`, `synthetic_protocol_v1_device`,
  `synthetic_videotoolbox_input_frames`, `no_android_device_or_ui`,
  `no_real_screen_capture`, `no_android_mediacodec_decode`, and
  `no_public_internet_path`. This dated readiness record does not close
  the Android device, public-Internet, real-capture, handoff, latency, or soak
  release gates.

### Main CI follow-up snapshot (2026-08-06)

On 2026-08-06, main commit `4c2e908fe31af4c187684991301e163371444eab`
passed GitHub Actions Phase 0
[run 31084214883](https://github.com/TaoSama/vibe-screen/actions/runs/31084214883),
including the 202/202 MacHost XCTest suite, protocol, Android, Phase 3, and
evidence-tool jobs. The same commit passed iOS engineering
[run 31084214830](https://github.com/TaoSama/vibe-screen/actions/runs/31084214830)
and HarmonyOS portable
[run 31084214856](https://github.com/TaoSama/vibe-screen/actions/runs/31084214856).
The latter workflows prove Simulator/core or portable gates only, not iOS or
HarmonyOS real-device behavior. The device
acceptance remains bound to source commit
`597518f948075e396352bc353afcec01a30303f3`; the later CI result is evidence
for that dated main commit only. Public Internet, ScreenCaptureKit media, real
input effects, network handoff, cross-service revocation, latency, and soak
gates remain open.
