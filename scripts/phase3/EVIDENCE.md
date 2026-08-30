# Phase 3 verification tools

These tools create observations; they do not turn unavailable dependencies into
passes. Run all Python checks from the repository root:

```bash
python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
python3 scripts/phase3/network_profile.py --profile handoff --output /tmp/vibe-screen-phase3/handoff.json
python3 scripts/phase3/network_profile.py --profile bandwidth-step --output /tmp/vibe-screen-phase3/bandwidth-step.json
python3 scripts/phase3/network_profile.py --profile relay-loss --output /tmp/vibe-screen-phase3/relay-loss.json
python3 scripts/phase3/security_vectors.py --output /tmp/vibe-screen-phase3/security-model.json
python3 scripts/phase3/public_nat_turn_preflight.py \
  --relay-config deploy/phase3/config/relay.production.example.json \
  --coturn-config deploy/phase3/coturn/production.conf \
  --skip-dns-resolution \
  --output /tmp/vibe-screen-phase3/public-nat-turn-preflight.json \
  --allow-blocked
python3 scripts/phase3/relay_deployment_readiness.py \
  --output /tmp/vibe-screen-phase3/relay-deployment-readiness.json \
  --allow-blocked
python3 scripts/phase3/session_authority_readiness.py \
  --report /tmp/vibe-screen-phase3/session-authority-readiness.json \
  --write-summary /tmp/vibe-screen-phase3/session-authority-summary.json
python3 scripts/phase3/release_gate_summary.py --output /tmp/vibe-screen-phase3/release-gate-summary.json
python3 scripts/phase3/revocation_propagation_verifier.py \
  --report /tmp/vibe-screen-phase3/revocation-propagation.json \
  --write-summary /tmp/vibe-screen-phase3/revocation-propagation-summary.json
make phase3-coturn-reconciliation-product-slice
PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_internet_release_gate \
  --evidence-dir /tmp/vibe-screen-phase3/public-internet-run
PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_adaptive_media_current_base \
  --report /tmp/vibe-screen-phase3/public-internet-run/adaptive-media-fluctuation.json \
  --repo . \
  --output /tmp/vibe-screen-phase3/public-internet-run/adaptive-media-current-base.json
```

`revocation_propagation_verifier.py` validates the cross-service revocation
contract for Authority, signaling, relay credential issuance, active coturn
allocation teardown, and post-revocation data-plane denial. It returns `0` only
when the report proves all required observations, `4` when local/control-plane
evidence exists but live allocation or data-plane proof is missing, `1` when the
report proves unsafe post-revocation behavior, and `2` for malformed or unsafe
evidence. The input schema is
`dev.vibescreen.phase3-revocation-propagation/v1`; reports must prove Authority
audit visibility, signaling long-poll wakeup rejection, future relay credential
rejection, post-revocation same-allocation credential retry rejection, stale TURN credential
rejection, active allocation disconnect, and zero post-revocation relayed
packets. Reports must not contain TURN passwords, bearer tokens, private keys,
or other raw secret material. A blocked summary is evidence of the remaining
deployment gap, not a release pass.

The `phase3-coturn-reconciliation-product-slice` target compiles and tests the
local operator slice for the coturn exporter/reconciliation/disconnect boundary.
It covers `coturn_allocation_exporter.py` adapting a reviewed structured
collector JSON into the strict Authority snapshot,
`coturn_reconciliation_loop.py` keeping durable consecutive missing-allocation
state, and `coturn_disconnect_executor.py` consuming the exact
`coturn_reconcile.py` disconnect environment to remove a local
active-allocation entry and write a non-secret audit record. This target is
deliberately current-base/local: it does not start a public relay, does not
prove a deployed exporter or scheduler, does not call a live coturn control
socket or provider API, and cannot close the public Internet release gate.

The security command without `--sut` validates only the attack-vector policy
model. Product coverage requires an implementation adapter, for example:

```bash
python3 scripts/phase3/security_vectors.py --output /tmp/vibe-screen-phase3/security-sut.json --sut -- ./security-adapter
```

The adapter reads one JSON object per stdin line and emits one JSON object with
`accepted` and `reason`. This makes the same ordered vector sequence reusable
against Swift, Kotlin, or a deployed service.

Android acceptance is fail-closed. Supply patterns that are emitted only after
decoded frames, host-side input acknowledgement, and a new post-disconnect
session are observed:

```bash
export ADB_ENDPOINT='<lease-controlled-endpoint>'
python3 scripts/phase3/android_internet_acceptance.py \
  --serial "$ADB_ENDPOINT" \
  --apk /absolute/path/to/app-debug.apk \
  --lease-token "$VIBE_SCREEN_INTERNET_LEASE_TOKEN" \
  --connect-tap 540,1600 \
  --streaming-pattern 'decoded.*frame|streaming active' \
  --host-input-evidence ~/Library/Logs/Telemachus/telemachus.log \
  --host-input-pattern 'phase3_input_injected session_epoch=[0-9]+ input_id=[0-9]+' \
  --reconnect-pattern 'VibeInternet.*active.*epoch=[0-9]+' \
  --session-epoch-pattern 'epoch=(?P<epoch>[0-9]+)' \
  --fresh-session-pattern 'fresh.*session|replacement.*session' \
  --ice-restart-pattern 'ICE.*restart|fresh.*session' \
  --old-session-closed-pattern 'old.*session.*closed|owner.*invalidated' \
  --stale-epoch-rejected-pattern 'stale.*epoch.*rejected|old.*epoch.*rejected' \
  --network-topology public-internet-controlled-router \
  --route mixed \
  --impairment-profile wifi-cellular-handoff-direct-relay \
  --evidence /tmp/vibe-screen-phase3/android.json
```

The script always requires both `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` to be absent, and requires
`/tmp/vibe-screen-device-internet.lock` to contain the exact UTF-8 bytes supplied
by `--lease-token`. It checks all three conditions before validation begins and
again before every ADB subprocess. `--device-lock` is repeatable and can only add
coordination locks; it cannot replace the mandatory checks. A missing/mismatched
Internet owner lock, an occupied coordination lock, or an unreadable lock fails
closed. Never put the lease token in tracked evidence or shell history; source it
from a protected local environment or credential file.

The host-input file is the Mac host's real owner-only runtime log at
`~/Library/Logs/Telemachus/telemachus.log`; `debugLog` creates it on first use
and rotates it at 1 MiB. The script captures its inode and offset immediately
before injecting the swipe and accepts only newly appended bytes, capped at
1 MiB. The session-epoch regular expression must contain the named group
`epoch`; the post-relaunch epoch must be strictly greater than the initial
epoch.

Generated reports, logcat, UI dumps, credentials, APKs, and captures must stay
outside the repository (the examples use `/tmp/vibe-screen-phase3/`). If an
evidence archive is later curated into project docs, review it for tokens,
device identifiers, IP addresses, and screen content first. Never place TURN
credentials or pairing secrets in command-line arguments or tracked files.

The deterministic network simulator covers latency, jitter, loss, bandwidth,
and network-ID handoff without root. It is not evidence for kernel-level packet
shaping. Any later `pf`, Network Link Conditioner, or remote Linux `tc` driver
must default to dry-run, require an explicit interface/target, and restore the
previous state in a `finally`/trap path.

When the shared Android device lease, signed Host permissions, public Internet
path, remote TURN deployment, controlled impairment router, or two-hour soak
window is unavailable, write a blocked package instead of probing the device:

```bash
python3 scripts/phase3/network_recovery_blocked_evidence.py \
  --output-dir docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>-network-recovery-blocked
```

The generated `release-gate-manifest.json` is expected to fail
`scripts/phase3/release_gate_manifest.py`. It documents why the run did not
start and cannot close public Internet, remote TURN, handoff, real media,
latency, or soak gates.

## Security coverage boundary

The vectors exercise duplicate control packets, independent control/media
sequence spaces, bounded out-of-order media, old session epochs, old keys after
rotation, missing current/next-key signatures, revoked keys, forged revocation,
and replayed revocation sequence numbers. Protocol tests pin the header fields
that bind ciphertext to protocol/session/key epoch, sender role, channel,
sequence, AEAD, and nonce, and keep encrypted media separate from control.

They do not prove AES-GCM/ECDH/ECDSA correctness, secure key storage, TURN
credential expiry, relay byte accounting, rate limiting, or abuse controls.
Those claims require the external SUT mode and deployed relay/Android evidence;
the reference policy model is intentionally labelled so it cannot be mistaken
for such evidence.

`session_authority_readiness.py` is the current-base owner verifier for automatic
account/session-authority issuance. It consumes a sanitized report using schema
`dev.vibescreen.phase3-session-authority-readiness/v1` and returns `0` only when
the product flow itself calls Authority profile issuance, product-driven account
and device registration are observed, the unsigned lease never leaves that
product flow for operator copying, the Mac signs the exact Authority-supplied
session epoch, Android imports and verifies the signed lease through product UI,
signaling role authorization rejects cross-role and expired sessions, and any
TURN credential path is short-lived with rotation or expiry proof. It returns `4`
for missing product-flow evidence and `1` for unsafe evidence such as a static
TURN password in product flow. Reports must not include bearer tokens, signaling
tokens, TURN passwords, private keys, device identifiers, or operator paths.

`release_gate_summary.py` is the current-base aggregation gate. It inspects the
local synthetic public artifact projection, the dated Nubia local interop record,
and the current-main blocked real-media attempt, then writes a single summary in
which every public Internet release gate remains `open`. Use
`--require-release-pass` only for a future release-blocking job; today that mode
is expected to exit non-zero because local loopback, synthetic Protocol v1 peers,
forced local coturn, and blocked attempts are readiness evidence only.

`public_nat_turn_preflight.py` is the production deployment evidence preflight for
the #194 public NAT/TURN gate. It fails closed unless a reviewed production relay
config, production coturn config, runtime TURN secret, TLS certificate/key,
globally routable `COTURN_EXTERNAL_IP`, HTTPS Authority and relay readiness
URLs, sanitized remote connectivity evidence, and an external canary command are
all present. It also requires `--deployment-evidence` with schema
`dev.vibescreen.phase3-public-nat-turn-deployment/v1`; that record must prove
public STUN, UDP/TCP TURN, TLS TURN, certificate hostname and TLS-version
inspection, quota enforcement, credential rotation with old-credential rejection
after TTL, monitoring for allocations/auth failures/relay bytes/quota decisions,
alert rules, and at least two remote observers outside the host network. The
command passed through `--connectivity-command` must execute during the preflight
and emit the same connectivity JSON on stdout; a previously saved JSON file is
retained only as reviewed context and cannot by itself make the gate pass. The
connectivity evidence must use schema
`dev.vibescreen.phase3-public-nat-turn-connectivity/v1`, record
`public_internet_path=true` and `remote_turn=true`, record
`forced_local_coturn=false`, `loopback=false`, and `synthetic_peer=false`, and
show a selected relay candidate pair plus positive packet exchange. Reports hash
endpoint-like values and must not contain TURN credentials, raw endpoint
addresses, or device identifiers. `--allow-blocked` is only for archiving a
blocked readiness artifact in environments without a public deployment; omitting
it returns non-zero while the gate is blocked.

`relay_deployment_readiness.py` is a public, fail-closed deployment readiness
preflight that checks DNS, the public relay `/readyz`, and, only when an operator
supplies a local SSH alias, Docker/Compose, disk headroom, listening ports,
existing containers, and local readiness behind the reverse proxy. It is
intended to be run from CI as a blocked readiness artifact when production
material or operator local configuration is unavailable. The report never
contains the SSH alias, raw relay hostname/endpoint values, usernames, tokens,
or operator filesystem paths; DNS results are reduced to counts and SHA-256
hashes. Use `<relay-host-ssh-alias>` in public references and pass the real
local alias only on the private operator machine:

```bash
python3 scripts/phase3/relay_deployment_readiness.py \
  --relay-host relay.taoai.site \
  --ready-url https://relay.taoai.site/readyz \
  --ssh-alias <relay-host-ssh-alias> \
  --output /tmp/vibe-screen-phase3/relay-deployment-readiness.json \
  --allow-blocked
```

`vibescreen_evidence.phase3_webrtc_relay_e2e_current_base` is the dedicated
current-base owner gate for the public Internet WebRTC/TURN relay product E2E
boundary. It consumes
`webrtc-relay-e2e-current-base-manifest.json` and writes
`webrtc-relay-e2e-current-base-gate.json`. It fails closed unless retained
evidence proves real macOS Host and Android product peers over a genuine public
Internet path through a deployed remote TURN relay route, with real
ScreenCaptureKit/CGDisplayStream-to-MediaCodec continuity and AES-256-GCM
record-layer protection. Local loopback, forced local coturn, synthetic peers,
synthetic media, USB, trusted-LAN TCP, and relay deployment preflights never
close this child gate; `gate_can_close_phase3_release` remains false.

The aggregate owner is PR #258 (`codex/phase3-current-base-gates`). Keep that PR
as the only current-base source of truth for overall Phase 3 public Internet
release-gate status; child PRs own bounded evidence packages instead of
duplicating aggregate status. The summary records #194 as the public Internet and
real remote TURN owner, #173 as the ScreenCaptureKit-to-Android-decoder owner,
PRs #224 and #171 as the network-handoff/recovery owners, #190 as the revocation
propagation owner, #214 as the soak owner, and #254 as the production enforcement
owner, with production relay deployment preflight ownership as a prerequisite only and the
`phase3_webrtc_relay_e2e_current_base_owner` child gate as the current product
E2E owner record for the public Internet WebRTC/TURN relay boundary. The merged
#241 coverage audit is a docs-only baseline that informs this
ownership map, not an executable aggregate verifier. Older broad
manifest/contract candidates such as #164 and #188 should be
narrowed or superseded for aggregate ownership. None of those child gates can
close from loopback, synthetic media, forced local coturn, or blocked deployment
records; public deployment evidence must fail closed until the real external
route, remote TURN, capture-to-device decoder, handoff, revocation, latency, and
soak artifacts exist.

`vibescreen_evidence.phase3_internet_release_gate` is the package-level checker
for the future public Internet run. It requires a `phase3-internet-manifest.json`
that explicitly marks a genuine public Internet path, a deployed remote TURN
route, real Android and macOS peers, identity-signed Host, Screen Recording,
real capture-to-MediaCodec continuity, visible input effects, network handoff,
cross-service revocation, packet-capture confidentiality, and no synthetic media.
It also requires direct and relay latency reports generated from raw
external-camera packages, the exact-window two-hour soak report, raw session and
telemetry logs, privacy-reviewed packet/capture notes, and
datachannel-record-layer.json for the control/media/audio/bulk DataChannel
record-layer contract. That record-layer file is transport-boundary evidence
only and must leave audio capture/playback, clipboard sync, and file transfer as
not_claimed unless separate real public Internet product-flow evidence exists.
If any required input is missing, USB-only, trusted-LAN-only, private-network
only, loopback, synthetic-loopback, synthetic-peer, forced-local-coturn,
synthetic, or marked blocked, the checker returns non-zero and writes verdict
blocked or insufficient; it never promotes readiness evidence into a release
pass.

`vibescreen_evidence.phase3_adaptive_media_current_base` is the narrower
current-base child gate for adaptive video behavior under real WebRTC Internet
network fluctuation. It consumes an already-collected
`adaptive-media-fluctuation.json` report and binds it to clean current `HEAD`;
it does not start the Host, touch ADB, change network settings, or close the
Phase 3 release gate. A pass requires public-Internet scope, controlled real
impairment, real WebRTC statistics, retained raw Host/Android/WebRTC stats
sources, fast-drop/slow-rise observations, bitrate/FPS changes, strictly
increasing `config_epoch` values, `VideoConfig` ACK before keyframe/resume,
stale generation rejection, rollback fail-closed behavior, and continuous
WebRTC transport/session/media-channel state. Static latency fixtures, local
loopback, deterministic `scripts/phase3/network_profile.py` output, synthetic
media, missing raw sources, or Nubia P0110 evidence relabeled away from
`pacific` keep the child gate blocked; transport restarts or unsafe oscillation
fail the child gate. After collecting the real fluctuation report, run:

```sh
make phase3-adaptive-media-current-base \
  EVIDENCE_DIR=/tmp/vibe-screen-phase3/public-internet-run
```

Use the explicit product slice to exercise the macOS product-session composition
through real signaling/libwebrtc and, in relay mode, forced local coturn:

```bash
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode direct --slice product \
  --output .build/phase3-local-synthetic-product-e2e/direct.json \
  --timeout-seconds 60
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode relay --slice product --skip-build \
  --output .build/phase3-local-synthetic-product-e2e/relay.json \
  --timeout-seconds 60
```

The product evidence must identify `slice: product`, the selected direct/relay
route, Protocol v1 negotiation, session/config epochs, touch/control exchange,
keyframe and delta media, application AEAD, seeded-plaintext log scan, tool
versions, and the complete repository source fingerprint. Dirty-tree evidence is
explicitly labelled non-commit evidence and includes the tracked diff hash plus
the untracked-file manifest/hash. The build manifest binds that source fingerprint
to the signaling executable, MacHost executable, and the actual WebRTC framework
Mach-O plus its required runtime bundle layout. MacHost and the framework execute
from one random `0700` private snapshot, and `DYLD_FRAMEWORK_PATH` points only to
that snapshot. The manifest records direct coturn use as `not_used`; a successful
relay run records the SHA-256 of the verified coturn snapshot used for both
`--version` and the real process. `--skip-build` fails closed if source or bound
build artifacts have changed. Relay credentials are supplied through a temporary
`0600` coturn config, not process arguments. The forced libwebrtc relay candidate
pair is the TURN proof; there is no separate `turnutils` smoke.

This uses a synthetic local Protocol v1 device harness and does not start screen
capture or the product UI. It is not macOS-to-Android, real encoded-screen/input,
packet-capture, public-Internet/NAT, or deployed STUN/TURN evidence. The default
`transport` slice retains the narrower adapter/DataChannel smoke test.

## Android M144 to Mac M150 product interop

`android_product_session_interop_acceptance.py` installs commit-bound app and
instrumentation APKs, starts the real local signaling service, and drives the
external M150 host against the Android M144 product session. Run direct and
relay as separate sessions with separate output directories. Relay mode requires
a caller-managed, device-reachable local coturn process; pass its owner-only raw
log and version record so the evidence remains auditable.

Before reading the device lease, the runner verifies a clean `HEAD`, runs fixed
Android app/instrumentation, release Mac host, and signaling builds, then verifies
the same clean commit and tree again. It accepts only those fixed output paths
and records each build command's result and output hashes. This controlled build
is the source-to-artifact provenance gate; caller-supplied APKs and binaries are
not accepted.

The runner does not acquire the shared device. Before starting it, atomically
create `/tmp/vibe-screen-device-internet.lock` as a regular `0600` JSON file with
exactly `owner`, `pid`, `task`, and `commit`. `task` must be
`phase3-android-internet-acceptance`, `commit` must equal the clean `HEAD`, and
`pid` must be a separate, continuously alive lock-holder process. Every ADB
subprocess rechecks all fields, the original inode and bytes, holder liveness,
and the absence of every other `vibe-screen-device-*.lock`. Deletion,
replacement, owner change, holder exit, or a new conflicting lock fails closed.

Supply the ADB endpoint and signaling bind address only as runtime arguments.
Supply STUN/TURN URLs and credentials in a bounded `0600` JSON file outside Git;
the runner transfers the one-use Android configuration over ADB stdin, verifies
that instrumentation consumed it, and removes both the private file and reverse
mapping through the same lease gate. Raw host/device/signaling/coturn outputs and
the JSON report must remain outside Git until their explicit privacy review.

The fail-closed markers prove the selected direct/relay candidate path,
Protocol v1, AES-256-GCM control and media records, synthetic video config plus
keyframe/delta delivery, authenticated touch, and the limited pairing/lease UI
instrumentation assertions emitted by the runner. They do not prove full product
UI coverage, rotation, ScreenCaptureKit, visible Mac input effects,
disconnect/reconnect, revocation propagation, public Internet traversal, or
soak.

After a run, validate the JSON with the current-base gate. The default profile
requires real ScreenCaptureKit/CGDisplayStream through Android MediaCodec and
therefore blocks the synthetic-media product-interop report by design:

```bash
make phase3-android-current-base-interop-gate \
  PHASE3_ANDROID_INTEROP_EVIDENCE=/absolute/path/to/acceptance.json
```

Use `PHASE3_ANDROID_INTEROP_GATE_PROFILE=product-interop` only to replace the
historical 2026-08-05 synthetic-media interop record on current source. That
profile still rejects withdrawn records, local WebRTC loopback output, stale
commits, non-P0110 device identity, missing direct or relay route reports, and
any claim that the synthetic-media run proved ScreenCaptureKit, Android
MediaCodec, public Internet, handoff, latency, or soak. It also compares the
direct and relay route-level `adb_gate` lease identity fields, so the top-level
`same_device_lease_holder` boolean alone is never sufficient.

## Production E2E enforcement gate

Use production_e2e_enforcement.py only after a production-shaped run has a
reviewed manifest. It is the aggregate release-gate verifier for the Authority,
signaling, coturn, and data-plane enforcement chain, not a service deployer:

    python3 scripts/phase3/production_e2e_enforcement.py \
      --manifest /protected/evidence/production-e2e-enforcement.json \
      --output /protected/evidence/production-e2e-enforcement-result.json

The manifest must name owners for release decision, Authority, signaling, coturn
data plane, and evidence review; bind clean source and artifact hashes; include
real deployed secret-manager configuration for Authority, signaling, and coturn;
prove matching authority/signaling/coturn policy values; and include public
route, remote TURN, real ScreenCaptureKit capture, Android MediaCodec decode,
application AEAD, coturn allocation/disconnect, Authority admission, signaling
authorization, and at least a 120-minute mixed-route soak. Missing deployment
inputs return blocked. Policy drift or a local/synthetic run relabeled as public
production E2E returns failed.
