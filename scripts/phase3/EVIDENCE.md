# Phase 3 verification tools

These tools create observations; they do not turn unavailable dependencies into
passes. Run all Python checks from the repository root:

```bash
python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
python3 scripts/phase3/network_profile.py --profile handoff --output /tmp/vibe-screen-phase3/handoff.json
python3 scripts/phase3/security_vectors.py --output /tmp/vibe-screen-phase3/security-model.json
python3 scripts/phase3/release_gate_summary.py --output /tmp/vibe-screen-phase3/release-gate-summary.json
```

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

`release_gate_summary.py` is the current-base aggregation gate. It inspects the
local synthetic public artifact projection, the dated Nubia local interop record,
and the current-main blocked real-media attempt, then writes a single summary in
which every public Internet release gate remains `open`. Use
`--require-release-pass` only for a future release-blocking job; today that mode
is expected to exit non-zero because local loopback, synthetic Protocol v1 peers,
forced local coturn, and blocked attempts are readiness evidence only.

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
keyframe/delta delivery, and authenticated touch. They do not prove the product
UI, rotation, ScreenCaptureKit, visible Mac input effects, disconnect/reconnect,
revocation propagation, public Internet traversal, or soak.
