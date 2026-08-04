# Phase 3 verification plan

## Evidence rules

Every result records UTC time, repository revision or tree hash, host/client
version, artifact SHA-256, toolchain versions, configuration **without secrets**,
network topology, direct/relay route, and raw log/evidence paths. A build, fake
engine, emulator, or loopback result may prove its own layer only; none substitutes
for the Xiaomi 12 Internet end-to-end gate.

## Reproducible local checks

Run current repository checks first:

```bash
make protocol
make baseline-macos-build
make baseline-macos-test
make baseline-android-test
make baseline-android-apk
```

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
| Transport | direct ICE, forced TURN, IPv4/IPv6, UDP-blocked/TCP-TLS relay, two channel semantics, payload/backlog/frame caps |
| Recovery | Wi-Fi/cellular/VPN changes, route changes, ICE restart backoff, signaling loss, TURN loss, process restart, old-epoch injection |
| Adaptation | trace-driven RTT/loss/jitter/bandwidth, downgrade/upgrade hysteresis, config acknowledgment/rejection, keyframe recovery |
| Relay operations | short credential expiry, allocation/peer/bandwidth/byte/concurrency quotas, rate limits, alerts, spend reconciliation |
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
    latency-method.md
```

Start by proving device identity, not merely that some ADB endpoint responded:

```bash
adb connect 100.72.246.116:5555
adb -s 100.72.246.116:5555 devices -l
adb -s 100.72.246.116:5555 shell getprop ro.product.manufacturer
adb -s 100.72.246.116:5555 shell getprop ro.product.model
adb -s 100.72.246.116:5555 shell getprop ro.serialno
adb -s 100.72.246.116:5555 shell getprop ro.build.fingerprint
adb -s 100.72.246.116:5555 shell getprop ro.build.version.sdk
```

Then record the exact APK and installed version:

```bash
shasum -a 256 path/to/vibe-screen.apk
adb -s 100.72.246.116:5555 install -r path/to/vibe-screen.apk
adb -s 100.72.246.116:5555 shell dumpsys package dev.telemachus.display
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
adaptation decisions. Go tests also exercise the standalone cryptographic core.
They do not prove the production composition of WebRTC, platform/product crypto,
signaling and TURN, Internet connectivity, or E2E security.

No Xiaomi 12 Phase 3 Internet acceptance evidence is recorded here yet. All
device, security-review, network-simulation, relay-operation, latency, and soak
criteria remain unproved until their raw artifacts exist and are reviewed.

Local verification on 2026-08-04 proved the following layers in one shared-tree
snapshot:

- `make protocol`: format, lint, build, and v1 breaking check passed;
- `go test -race ./... && go vet ./...` in `packages/security`: passed;
- `go test -race ./... && go vet ./...` in `services/relay`: passed after the
  concurrent relay source/test changes converged;
- Phase 3 Python suite: 21 tests passed; security-vector CLI passed
  24 vectors, including direction reflection and global revocation sequencing;
- Android `./gradlew testDebugUnitTest`: 68 tests passed with zero
  failures/errors; this does not run instrumented PeerConnection tests;
- Android `./gradlew auditReleaseDependencies`: passed the fixed AAR, Gson,
  SBOM and bundled WebRTC/Gson notice hashes; release packaging depends on this
  task;
- macOS `swift build`: an initial run failed while concurrent Phase 3 files were
  inconsistent; after the owning edits converged, a fresh rerun passed. The
  `swift test` command still fails before execution because the XCTest module is
  unavailable in the selected developer environment.
- `services/signaling make verify`: format, vet, race tests and a real child-process
  offer/answer/candidate exchange passed; its container was not built because
  Docker is unavailable.
- macOS production WebRTC loopback and a real local signaling-process self-test
  passed for SDP/ICE and both data channels. The binary links M150 WebRTC.
- A fresh local M150 loopback rerun passed with direct UDP, bidirectional reliable
  ordered control, unordered zero-retransmit media, and ICE restart. The signaling
  self-test correctly failed closed when its four explicit session credentials
  were absent; a separately configured run is the recorded passing service test.
- The reproducible local runner passed a real signaling process using both direct
  UDP and `forceRelay=true`. Local coturn 4.16.0 selected
  `relay(local=relay,remote=relay,protocol=udp)` and delivered application
  AES-256-GCM control/media records bidirectionally. Its independent allocation
  check relayed 3/3 datagrams and scanned generated credentials out of logs.
- `services/relay/integration/test-turn-rest.sh` passed short-term control-plane
  credential issuance, authenticated coturn allocation, ChannelBind and 10/10
  relayed messages.
- The relay control plane's race suite passed after separating usage and metrics
  credentials, enforcing an exact Bearer scheme, exporting current-day estimated
  cost as a gauge, and syncing the state directory after atomic replacement.

These checks did not exercise public NAT/external TURN, OS-level network
impairment, Android M144 against macOS M150, an Android Internet stream, or soak.
The Android instrumentation APK uses the real record layer but cannot execute
during the coordinated device freeze.
