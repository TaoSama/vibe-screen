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
revokes the client device at Authority, then proves signaling role access, future
relay credential admission, exact same-allocation credential retry before revoke, relay
`/v1/usage` Authority admission, and later Authority coturn usage accounting fail
closed. Relay unit tests separately cover exact duplicate usage retries before
Authority admission, rejected changed-payload event ID reuse, required
`allocation_id` in production authority mode, restart-safe registry writes,
registry readiness failure, and usage rejection after Authority revocation.

`make phase3-test` also runs static production-profile checks for the Phase 3
relay/Authority deployment files. These checks prove only repository configuration
invariants: production relay and Authority profiles require digest-pinned images,
secrets are file-backed, relay HTTP remains loopback-only, and the coturn
production profile retains TLS, quota, bounded relay-port, and private/internal
peer-deny policy. They do not start a public relay, inspect real secret delivery,
or prove public reachability. The same target validates the structured coturn
snapshot reconciliation helper and the current-base exporter/reconciliation-loop/
disconnect-executor product slice: strict JSON input, optional external exporter
stdout validation, loopback-only plaintext Authority URLs, exact token-source
selection, bounded failure retry, consecutive missing-allocation tracking, and
fail-closed disconnect execution when Authority reports unauthorized, conflicting,
or revoked active source allocations. This local slice proves stale allocation,
revoked device, and quota-closed allocation contracts against structured local
state. The coturn CLI control helper tests cover strict allocation-registry
parsing, coturn `ps` parsing, exact allocation export, ambiguous username
failure, and loopback CLI `cs` disconnect command construction. These tests do
not prove a production coturn exporter, production scheduler, provider billing
reconciliation, production coturn process integration, or real data-plane
allocation termination.
The Phase 3 revocation propagation verifier now pins the evidence contract for
Authority/signaling/relay/coturn propagation. It passes only when a report proves
Authority audit visibility, signaling long-poll wakeup rejection, future and
post-revocation same-allocation relay credential rejection, stale issued TURN credential
rejection, active allocation disconnect, and zero relayed post-revocation
packets; a missing live deployment observation returns a blocked status. The
2026-08-25 current-base blocked record documents that the local service tests
cover Authority-backed signaling, bounded long-poll reauthorization, future and
post-revocation same-allocation relay credential rejection, relay `/v1/usage` Authority
admission/revocation rejection, and strict coturn registry/CLI helper behavior,
but not deployed coturn allocation teardown, stale credential reuse denial, or
packet-denial behavior.

The production end-to-end enforcement release gate has its own aggregate owner
contract:

    make phase3-production-e2e-enforcement \
      EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-25-production-e2e-enforcement-current-base-blocked

This gate accepts only a reviewed production-e2e-enforcement.json manifest that
binds release, Authority, signaling, coturn data-plane, and evidence-review
owners to one source revision. It fails when authority/signaling/coturn policy
values disagree. It returns blocked rather than pass when real deployed
secret-manager configuration, public route evidence, remote TURN observation,
ScreenCaptureKit-to-Android MediaCodec data-plane evidence, active coturn
disconnect proof, or a 120-minute mixed-route production soak is missing. Local
loopback, forced local coturn, and synthetic Protocol v1 peers are hard failures
when presented as public production E2E.

Record failures as failures. In particular, an unavailable XCTest/full-Xcode or
device environment is not a waiver. When production WebRTC/crypto/signaling code
is added, add deterministic Make targets rather than relying on undocumented IDE
steps.

## Public Internet soak gate

The complete Internet soak gate is evaluated by
`python3 -m vibescreen_evidence.phase3_internet_soak gate` or the Make target
`phase3-internet-soak-gate`. It is a composition verifier, not a runner. It
consumes these privacy-reviewed inputs from one evidence directory:

- `phase3-internet-soak-manifest.json`, created before the run from production
  TURN/signaling/relay/Authority/TLS/secret-source/remote-peer inputs;
- `remote-turn-verifier.json`, proving public remote TURN packet exchange;
- `media-continuity.json`, proving real ScreenCaptureKit-to-Android decoder
  continuity;
- `network-handoff.json`, proving fresh-session handoff recovery, stale media
  rejection, and no plaintext fallback;
- `revocation-propagation.json`, proving active coturn allocation disconnect,
  stale credential rejection, and zero post-revocation relayed packets;
- `soak-exact-window-report.json`, proving a clean two-hour mixed direct/relay
  window with route samples, nonce-reuse absence, and RSS, queue, loss, RTT, FPS,
  bitrate, relay-byte, ICE-restart, drop, thermal, and battery metric families.

Exit code `0` means `pass`. Exit code `3` means blocked evidence unless
`--allow-blocked` is set for archiving a blocked result. Exit code `2` means a
complete input proves unsafe behavior, such as plaintext fallback or raw secret
material in a report. Local loopback, forced local coturn, synthetic Protocol v1,
or partial Android UI evidence must not be renamed into any of these files.

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
| Adaptation | WebRTC Internet transport only (USB/LAN keep manual client-driven presets). Offline: fast-drop/slow-rise hysteresis with jitter reset, host-only non-finite/zero-bitrate/missing-RTT conservative handling, even dimensions without upscaling, user-baseline upper-bound clamp, latest-proposal-wins queuing, rotation serialization, stale owner/generation rejection, retry after local or peer rejection, host apply encoder/capture + media gate → `VideoConfig` ACK → keyframe/resume, rejection rollback and host-apply/ACK/rollback-timeout fail-closed. Android policy tests cover hysteresis and neutral reset, not those host telemetry edge cases. Current-base real fluctuation claims additionally require `make phase3-adaptive-media-current-base`, which is fail-closed for static latency fixtures, local loopback, deterministic network-profile output, synthetic media, missing real WebRTC stats, missing fast-drop/slow-rise, missing bitrate/FPS/config-epoch evidence, or transport restarts. Not proved: real ScreenCaptureKit→Android decoder continuity, public Internet, real remote TURN, real network fluctuation, handoff, soak |
| Relay operations | short credential expiry, authority-backed allocation admission before credential issuance, allocation/peer/bandwidth/byte/concurrency quotas, rate limits, alerts, non-authoritative Authority snapshot reconciliation, and separate provider billing reconciliation |
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
| Path handoff | Wi-Fi→cellular→Wi-Fi/VPN | fresh session, new epoch, no stale media/input |
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
    README.md
    phase3-internet-manifest.json
    device-info.json
    host.txt
    build.txt
    apk-sha256.txt
    direct-session.jsonl
    relay-session.jsonl
    network-handoff.jsonl
    network-handoff.json
    replay-revocation.jsonl
    revocation-evidence.json
    soak-2h/summary.json
    soak-2h/samples.jsonl
    soak-2h/host-telemetry.jsonl
    soak-2h/exact-window-report.json
    raw-logcat.txt
    host.log
    real-media-continuity.json
    adaptive-media-fluctuation.json
    adaptive-media-current-base.json
    webrtc-bulk-product-flow-manifest.json
    webrtc-bulk-product-flow-gate.json
    packet-capture-notes.md
    packet-capture-confidentiality.json
    datachannel-record-layer.json
    privacy-manifest.json
    latency/direct/manifest.json
    latency/direct/samples.csv
    latency/direct/raw-camera.mov
    latency/direct/latency-evidence.json
    latency/relay/manifest.json
    latency/relay/samples.csv
    latency/relay/raw-camera.mov
    latency/relay/latency-evidence.json
    latency-method.md          # copy or link docs/runbook/latency-measurement.md
    phase3-internet-release-gate.json
```

When a curated evidence package is intended to close the Phase 3 release gate,
add a `release-gate-manifest.json` beside those artifacts and validate it before
changing release language:

```bash
python3 scripts/phase3/release_gate_manifest.py --print-matrix
python3 scripts/phase3/release_gate_manifest.py \
  docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/release-gate-manifest.json \
  --evidence-root docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>
```

The manifest schema is `dev.vibescreen.phase3-release-gate-manifest/v1`. It is a
necessary-condition verifier, not an automatic release approval: a pass requires
the manifest to cover every open gate below with repository-relative evidence
files, clean-source artifact hashes, truthful device identity, and real-world
observations. USB, trusted-LAN-only, private-network-only, local loopback,
synthetic loopback, synthetic peer, forced-local-coturn, synthetic media, blocked
runs, or Nubia evidence claiming Xiaomi/fuxi identity fail closed. A
DataChannel record-layer pass proves only the Internet DataChannel transport
boundary; audio_capture_playback, clipboard_sync, and file_transfer must remain
not_claimed until real public Internet product-flow evidence exists.

```json
{
  "schema": "dev.vibescreen.phase3-release-gate-manifest/v1",
  "result": "pass",
  "source": {
    "commit": "<40-character-clean-source-commit>",
    "tree_status": "clean"
  },
  "device": {
    "manufacturer": "<exact observed manufacturer>",
    "model": "<exact observed model>",
    "codename": "<exact observed codename>",
    "os_version": "<exact observed Android version>",
    "evidence_role": "<evidence role for this exact observed device>"
  },
  "artifacts": {
    "mac_host_sha256": "<sha256>",
    "android_apk_sha256": "<sha256>"
  },
  "claims": ["Exact human-readable claims for this evidence package"],
  "gates": {
    "public_internet_direct_path": {
      "status": "pass",
      "route": "direct",
      "public_internet_path": true,
      "selected_candidate_pair": "direct(...)",
      "remote_public_route_observed": true,
      "local_loopback_address": false,
      "usb_adb_reverse": false,
      "host_network": "<host public network>",
      "device_network": "<different device public network>",
      "remote_public_asn": "<observed remote ASN>",
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["direct-session.jsonl"]
    },
    "remote_turn_relay_path": {
      "status": "pass",
      "route": "relay",
      "public_internet_path": true,
      "remote_turn_deployment": true,
      "local_coturn_only": false,
      "forced_local_coturn": false,
      "turn_public_hostname": "<public TURN hostname>",
      "turn_resolved_public_ip": "<public TURN IP>",
      "turn_provider": "<provider>",
      "turn_region": "<region>",
      "selected_candidate_pair": "relay(...)",
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["relay-session.jsonl"]
    },
    "real_screencapturekit_to_android_media": {
      "status": "pass",
      "capture_source": "ScreenCaptureKit",
      "android_decoder": "MediaCodec",
      "screen_capture_frames": 1,
      "encoded_frames": 1,
      "android_decoded_frames": 1,
      "first_android_output_observed": true,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["real-media.jsonl"]
    },
    "network_handoff_recovery": {
      "status": "pass",
      "handoff_count": 1,
      "controlled_impairment": true,
      "impairment_tool": "linux-netns-tc-or-equivalent",
      "impairment_profile": {
        "latency_ms": 95,
        "jitter_ms": 20,
        "loss_percent": 2.0,
        "bandwidth_kbps": 6000
      },
      "route_before": "direct",
      "route_after": "relay",
      "fresh_session_requested": true,
      "ice_restart_attempted": true,
      "old_session_closed": true,
      "initial_session_epoch": 7,
      "recovered_session_epoch": 8,
      "stream_pause_detected": true,
      "stream_resume_detected": true,
      "recovery_started_at_monotonic_ms": 1000,
      "recovery_completed_at_monotonic_ms": 5200,
      "session_epoch_advanced": true,
      "stale_epoch_rejected": true,
      "recovered_streaming": true,
      "recovery_seconds": 4.2,
      "approved_limit_seconds": 5,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["network-handoff.jsonl"]
    },
    "cross_service_revocation": {
      "status": "pass",
      "active_session_disconnected": true,
      "direct_reconnect_rejected": true,
      "relay_reconnect_rejected": true,
      "turn_allocation_disconnected": true,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["replay-revocation.jsonl"]
    },
    "packet_capture_confidentiality": {
      "status": "pass",
      "capture_reviewed": true,
      "no_plaintext_media": true,
      "no_plaintext_input": true,
      "no_credentials": true,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["packet-capture-notes.md"]
    },
    "external_camera_latency": {
      "status": "pass",
      "method": "external_camera",
      "sample_count": 5,
      "direct_p95_ms": 150,
      "relay_p95_ms": 150,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["latency-method.md"]
    },
    "webrtc_datachannel_record_layer": {
      "status": "pass",
      "public_internet_path": true,
      "remote_turn_deployment": true,
      "fake_webrtc_engine": false,
      "forced_local_coturn": false,
      "aead": "AES-256-GCM",
      "aad_binds_session_epoch": true,
      "key_epoch_bound": true,
      "directional_key_separation": true,
      "channel_binding_enforced": true,
      "replay_rejected": true,
      "wrong_channel_rejected": true,
      "packet_capture_no_plaintext": true,
      "nonce_reuse_detected": false,
      "plaintext_fallback": false,
      "channels": ["control", "media", "audio", "bulk"],
      "product_flows": {
        "audio_capture_playback": "not_claimed",
        "clipboard_sync": "not_claimed",
        "file_transfer": "not_claimed"
      },
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["datachannel-record-layer.json"]
    },
    "two_hour_mixed_route_soak": {
      "status": "pass",
      "duration_seconds": 7200,
      "routes": ["direct", "relay"],
      "controlled_impairment": true,
      "impairment_tool": "linux-netns-tc-or-equivalent",
      "impairment_profile": {
        "latency_ms": 120,
        "jitter_ms": 35,
        "loss_percent": 2.0,
        "bandwidth_kbps": 10000
      },
      "route_before": "direct",
      "route_after": "relay",
      "network_change_count": 1,
      "bounded_queues": true,
      "bounded_memory": true,
      "no_nonce_reuse": true,
      "no_steady_latency_growth": true,
      "synthetic_media": false,
      "local_loopback_only": false,
      "usb_transport": false,
      "trusted_lan_only": false,
      "private_network_only": false,
      "same_private_network": false,
      "loopback": false,
      "synthetic_loopback": false,
      "synthetic_peer": false,
      "evidence_files": ["soak-summary.json"]
    }
  }
}
```

For blocked readiness, write a separate blocked package instead of weakening the
pass manifest. This records the blocker and intentionally creates a
`release-gate-manifest.json` that fails the pass verifier:

```bash
python3 scripts/phase3/network_recovery_blocked_evidence.py \
  --output-dir docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>-network-recovery-blocked
python3 scripts/phase3/release_gate_manifest.py \
  docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>-network-recovery-blocked/release-gate-manifest.json \
  --evidence-root docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>-network-recovery-blocked
```

The second command is expected to fail for blocked evidence. A blocked package is
evidence of non-execution and readiness gaps only; it must not be used to mark
public Internet, handoff, real media, or soak complete.

Start by proving device identity, not merely that some ADB endpoint responded.
Manual ADB use must follow the same shared lease-aware acceptance flow as the
runner: create and hold `/tmp/vibe-screen-device-internet.lock` from a separate
process, keep `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` absent, and recheck both the Android and
Internet locks before every ADB subprocess:

```bash
test ! -e /tmp/vibe-screen-device-soak.lock
test ! -e /tmp/vibe-screen-device-android.lock
export ADB_ENDPOINT='<device-serial>'
export LEASE_OWNER='<opaque-owner-value>'
export VIBE_SCREEN_COMMIT="$(git rev-parse HEAD)"
python3 - <<'PY' &
import json, os, pathlib, time
path = pathlib.Path("/tmp/vibe-screen-device-internet.lock")
payload = json.dumps({
    "owner": os.environ["LEASE_OWNER"],
    "pid": os.getpid(),
    "task": "phase3-android-internet-acceptance",
    "commit": os.environ["VIBE_SCREEN_COMMIT"],
}, separators=(",", ":")).encode()
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, payload)
os.fsync(fd)
try:
    while True:
        time.sleep(60)
finally:
    os.close(fd)
    path.unlink(missing_ok=True)
PY
LEASE_PID=$!
export LEASE_PID
trap 'kill "$LEASE_PID"; wait "$LEASE_PID" 2>/dev/null || true; rm -f /tmp/vibe-screen-device-internet.lock' EXIT

check_android_internet_locks() {
  test ! -e /tmp/vibe-screen-device-soak.lock
  test ! -e /tmp/vibe-screen-device-android.lock
  python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path("/tmp/vibe-screen-device-internet.lock")
stat = path.stat()
assert stat.st_mode & 0o777 == 0o600
root = json.loads(path.read_text())
assert root["owner"] == os.environ["LEASE_OWNER"]
assert root["task"] == "phase3-android-internet-acceptance"
assert root["commit"] == os.environ["VIBE_SCREEN_COMMIT"]
assert root["pid"] == int(os.environ["LEASE_PID"])
os.kill(root["pid"], 0)
PY
}

adb_guarded() {
  check_android_internet_locks
  adb -s "$ADB_ENDPOINT" "$@"
  check_android_internet_locks
}

adb_guarded devices -l
adb_guarded shell getprop ro.product.manufacturer  # nubia
adb_guarded shell getprop ro.product.model         # P0110
adb_guarded shell getprop ro.product.device        # pacific
adb_guarded shell getprop ro.build.version.release # 16
adb_guarded shell getprop ro.build.version.sdk     # 36
```

Use `adb -s <device-serial>` explicitly for the Nubia path. The archived
identity must be `nubia P0110 / pacific / Android 16 / SDK 36`; it must not be
reported as Xiaomi 13/fuxi evidence.

Then record the exact APK and installed version:

```bash
shasum -a 256 path/to/vibe-screen.apk
adb_guarded install -r path/to/vibe-screen.apk
adb_guarded shell dumpsys package dev.telemachus.display
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

Before treating the package as release evidence, run the package gate:

```bash
make phase3-internet-release-gate \
  EVIDENCE_DIR=/absolute/path/to/phase3-public-internet-run
```

The gate is fail-closed. `phase3-internet-manifest.json` must explicitly record
`network_scope=public_internet`, `turn_scope=deployed_remote_turn`, both direct
and relay routes, a real Android device, a real macOS Host, an identity-signed
Host, granted Screen Recording, real capture-to-MediaCodec continuity, visible
input effects, network handoff, cross-service revocation, packet-capture
confidentiality, and `no_synthetic_media=true`. Missing raw camera files,
annotated latency samples, the exact-window two-hour soak report, public-route
evidence, or remote TURN evidence returns `blocked` or `insufficient`; it never
closes a gate from local loopback, forced local coturn, synthetic media, or a
diagnostic-only device run. A Nubia P0110 run must keep
`manufacturer=nubia`, `model=P0110`, `codename=pacific`, and the real Android
version; it must not be relabeled as Xiaomi/fuxi evidence.

`device-info.json` must independently match the manifest identity fields.
Structured pass files are not free-form status markers: `network-handoff.json`,
`revocation-evidence.json`, and `packet-capture-confidentiality.json` must use
their Phase 3 `kind`, list non-empty `raw_sources`, and set each required
observation to `true`. The soak report must include `phase3_internet_scope`
with public Internet scope, direct and relay route coverage, observed handoff,
observed cross-service revocation, packet-capture confidentiality,
`no_synthetic_media=true`, `no_plaintext_fallback=true`, and
`nonce_reuse_detected=false`; otherwise the aggregate package remains
`insufficient` even when generic two-hour metrics pass.

For the real capture -> Android decoder continuity slice, generate
`real-media-continuity.json` from retained Host and Android logs with
`PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_real_media_continuity` or
`make phase3-real-media-continuity`. The result must record `media_source`
through observed real-capture markers, explicit `capture_sources` metadata from
ScreenCaptureKit/CGDisplayStream, Protocol v1 `session_epoch` or media epoch,
selected `network_path`, Host signing state, Screen Recording state,
VideoToolbox output epochs, MediaCodec first input/output epochs, continuous
output-frame count, drops, and decoder errors. The evaluator is fail-closed:
synthetic-media markers, missing public-Internet route evidence, missing
identity-signed Host evidence, missing Screen Recording permission, missing
real capture-source metadata, missing capture/VideoToolbox output, missing
VideoToolbox output epoch, missing MediaCodec output, or no shared epoch across
Host VideoToolbox output and Android MediaCodec first input/output produce
`blocked`. Decoder/runtime errors or excess drops produce `fail` only after the
required runtime stages are otherwise present. The file is a narrow continuity
preflight and always records `gate_can_close_phase3_release=false`; it cannot by
itself close the broader Phase 3 release gate.


For adaptive media under real network fluctuation, bind retained WebRTC transport
statistics and adaptive policy events to current `HEAD` with
`PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_adaptive_media_current_base`
or `make phase3-adaptive-media-current-base`. The input report schema is
`dev.vibescreen.phase3-adaptive-media-fluctuation/v1` and must record current
clean source, exact Android identity, public-Internet WebRTC scope, controlled
real network impairment, real WebRTC statistics, raw Host/Android/stats sources,
fast downgrade, conservative slow upgrade, bitrate/FPS changes, strictly
increasing video `config_epoch` values, `VideoConfig` ACK before keyframe/resume,
stale owner or generation rejection, rollback fail-closed behavior, no unsafe
oscillation, and no transport/session/media-channel restart. Local loopback,
deterministic `scripts/phase3/network_profile.py` output, static latency
fixtures, synthetic media, missing raw sources, or Nubia P0110 results relabeled
as Xiaomi/fuxi keep the child gate blocked. A transport restart or unsafe
oscillation is a failure. Even a pass records only
`can_claim_current_base_adaptive_media_fluctuation=true` and keeps
`gate_can_close_phase3_release=false`.

After `real-media-continuity.json` exists, bind it to the checked-out current
base and retained Android visible-UI evidence with
`PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_real_media_current_base`
or `make phase3-real-media-current-base`. This child gate requires the
continuity result's repository revision to match current `HEAD`, the captured
tree to be clean, Android device identity to record manufacturer/model/codename,
Android version, and SDK, and a non-empty screenshot, device recording, or
external-camera recording plus an operator note confirming decoded Mac desktop
content is visible in the Android UI. Missing UI evidence, stale or dirty source,
synthetic media, local-only or forced-local-coturn routes, unsigned/ad-hoc Host
builds, blocked TCC, missing real capture-source metadata, missing
capture/VideoToolbox/MediaCodec stages, no shared VideoToolbox-to-MediaCodec
pipeline epoch, decoder errors, or excess drops keep the current-base gate
blocked or failed. Even a pass records only
`release_gate_effect=child_gate_only`; it does not close the broader public
Internet release gate.

For Internet DataChannel audio, clipboard, and file-transfer product-flow
ownership, run `make phase3-advanced-datachannel-current-base` with
`PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON` pointing at the reviewed retained
manifest. To create the default blocked baseline manifest, run
`make phase3-advanced-datachannel-blocked-baseline`. A pass requires retained
evidence files with matching SHA-256 values proving real macOS+Android
public-Internet product sessions with `vibescreen.audio.v1`, the protected
control DataChannel clipboard flow, and `vibescreen.bulk.v1` file-transfer flow.
Existing USB/LAN audio, clipboard, and file-transfer evidence, iOS trusted-LAN
evidence, local loopback, forced local coturn, synthetic Protocol v1 peers, or
raw audio/bulk hook tests must not be used as pass evidence for this gate. A
pass would remain a child gate and would not close the broader public Internet
release gate.

For the narrower public Internet WebRTC bulk file-transfer product-flow owner,
run `make phase3-webrtc-bulk-product-flow` with
`PHASE3_WEBRTC_BULK_MANIFEST_JSON` pointing at
`webrtc-bulk-product-flow-manifest.json` in the retained evidence directory. To
archive the current fail-closed state before a real run exists, run
`make phase3-webrtc-bulk-product-flow-blocked-baseline`. The child gate passes
only when retained artifacts prove a real macOS Host and real Android device used
a deployed public TURN relay WebRTC route for approved bidirectional
`vibescreen.bulk.v1` file transfer, including offer/request/chunk/progress/
completion observations, final SHA-256 equality, bounded queue/backpressure
behavior, cancel and disconnect cleanup, no plaintext fallback, no synthetic
peer, and AES-256-GCM channel/session/key separation. It also carries a release
closure checklist for relay production readiness, real capture-to-MediaCodec
continuity, network handoff, cross-service revocation, external-camera latency,
two-hour mixed-route soak, and packet-capture confidentiality.

Relay deployment preflight hardening cannot satisfy this product-flow gate by
itself. A PR or run that checks relay DNS, `/readyz`, disk, TLS, quotas, secret
source wiring, or similar deployment prerequisites remains readiness evidence
only until it is paired with the real product WebRTC bulk transfer and the
broader release evidence package. Existing USB/LAN file-transfer records, local
loopback, forced local coturn, synthetic Protocol v1 peers, and raw bulk hook
tests must stay blocked if presented as public Internet product E2E. Even a pass
sets only `can_close_public_internet_bulk_product_flow_gate=true`;
`gate_can_close_phase3_release` remains false and the aggregate release gate must
still pass separately.

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
- Android QR pairing verifier tests cover canonical
  `vibescreen://pair?v=1&o=` URL parsing, pre-decode rejection of non-canonical
  payload characters, and single-use Android scanned-offer handling. macOS
  source-level XCTest cases cover first-attempt offer consumption when a
  bootstrap proof fails, but the archived local current-base run records those
  XCTest filters as blocked before execution where the selected Command Line
  Tools environment could not compile XCTest. The Android
  profile codec also covers missing/reserved lease expiry rejection and host
  lease signatures bound to the previously verified pairing identity. These are
  offline parser/state-machine checks and do not prove a real camera QR scan or
  device-to-host request/acceptance exchange;
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
  waiter caps, concurrent capacity, cross-instance routing through one shared
  PostgreSQL ledger, LISTEN/NOTIFY wakeup across store instances, and
  invalidation tombstones when `VIBE_SIGNALING_TEST_DATABASE_URL` is set. Its
  container was not built because Docker is unavailable.
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
  structured snapshot ingestion, external exporter-command stdout validation,
  sanitized token-source selection, loopback-only plaintext Authority URLs,
  Authority response validation, bounded retry after transient failure, and
  fail-closed handling of unauthorized/conflicting/revoked active allocations
  when no disconnect executor exists or when the executor fails. This is a local
  contract test, not production coturn exporter, production scheduler, provider
  billing reconciliation, or data-plane disconnect evidence.
- The 2026-08-25 current-base coturn reconciliation product-slice tests add
  strict structured exporter adaptation, bounded durable reconciliation-loop
  state for stale ledger allocations, local active-allocation disconnect audit
  handling, and the Authority quota-closed allocation handoff that reports the
  allocation as `revoked_allocation_ids` for remediation. This remains local
  structured-state evidence only; no Android device, public Internet path, live
  coturn control socket, provider API, packet capture, latency, or soak evidence
  was collected.
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

- A 2026-08-21 continuity-preflight application to retained blocked Nubia P0110
  evidence is archived under
  [`evidence/2026-08-21-nubia-p0110-real-media-continuity-blocked/`](evidence/2026-08-21-nubia-p0110-real-media-continuity-blocked/README.md).
  It adds a structured fail-closed `real-media-continuity.json` result for the
  ScreenCaptureKit/CGDisplayStream -> Android MediaCodec slice. The source logs
  are the 2026-08-18 blocked Host and Android windows, so the result remains
  blocked by missing Screen Recording permission, missing public-Internet route
  evidence, and absent capture/encoder/decoder output. No ADB command was run
  for this derived preflight, and no Phase 3 release gate changes state.

- A 2026-08-21 local implementation check on branch
  `codex/phase3-network-handoff-recovery` covers the network-recovery code
  slice only. Android focused unit tests passed for `WebRtcInternetTransportTest`
  and `InternetProductSessionTest`, proving bounded ICE restart attempts,
  unsupported-renegotiation fresh-session fallback, old-owner invalidation, and
  late-callback rejection in the JVM test harness. The macOS `Vibe Screen`
  product built and `--phase3-webrtc-loopback-self-test` passed, including the
  local ICE restart loopback; `--phase3-product-signaling-self-test` failed
  closed because `VIBE_SIGNALING_URL`, `VIBE_SIGNALING_SESSION_ID`,
  `VIBE_SIGNALING_HOST_TOKEN`, and `VIBE_SIGNALING_DEVICE_TOKEN` were not
  provided. The broader `--phase3-internet-self-test` passed locally, including
  `sdkTransmissionEpochGate=true`, `recoveryExhaustionFailClosed=true`, and
  `recoveryExhaustionFreshSession=true`; this is still an offline transport
  self-test rather than product-device handoff evidence.
  `swift test --filter InternetProductSessionTests` could not run in
  the local Command Line Tools environment because `xctest`/`XCTest` were
  unavailable. No Android device, real ScreenCaptureKit media, public Internet path, remote
  TURN route, controlled network handoff, packet capture, latency, or soak run
  was executed; all corresponding release gates remain open.

- A 2026-08-23 current-base service slice adds an admin-only Authority session
  profile endpoint for already registered devices, makes Authority return the
  role authorization expiry, lets Signaling adopt Authority-issued sessions as
  local routing metadata only after successful remote authorization, and makes
  the Mac lease issuer sign the exact Authority-supplied `session_epoch` while
  rejecting stale values. Local verification for this slice passed:
  `cd services/authority && go test -count=1 ./internal/authority`,
  `cd services/authority && go test -count=1 ./...`,
  `cd services/signaling && go test -count=1 ./...`, and
  `python3 -m unittest tests.phase3.test_authority_session_profile_contract -v`.

- A 2026-08-25 current-base product slice makes validated network handoff request
  fresh-session recovery immediately instead of first attempting ICE restart,
  while ordinary disconnect recovery keeps its bounded ICE-restart path. Focused
  macOS and Android unit coverage exercises direct handoff-to-fresh-session
  behavior, old transport closure/owner invalidation, replacement session epoch
  installation, and the existing unsupported-ICE fallback. Local direct and
  forced-local-coturn product E2E remain synthetic only;
  `--phase3-internet-self-test` now reports
  `networkHandoffFreshSession=true` for the offline transport contract. The
  blocked readiness record is archived under
  `evidence/2026-08-25-network-handoff-fresh-session-current-base-blocked/`.
  No Android device, real ScreenCaptureKit media, Android MediaCodec decode,
  public Internet path, remote TURN route, controlled network handoff, packet
  capture, latency, or soak run was executed for this product slice; all
  corresponding release gates remain open.
  This is unit/contract evidence only. It does not prove Mac/Android automatic
  profile invocation, Android UI import, public Internet, real ScreenCaptureKit
  capture, Android MediaCodec decode, active disconnect, handoff, latency, or
  soak. A local `cd baseline/MacHost && swift test --filter
  InternetSessionLeaseIssuerTests` attempt was blocked by this environment with
  `no such module 'XCTest'`, so XCTest evidence remains external to this run.

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
