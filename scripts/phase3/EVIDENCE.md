# Phase 3 verification tools

These tools create observations; they do not turn unavailable dependencies into
passes. Run all Python checks from the repository root:

```bash
python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
python3 scripts/phase3/network_profile.py --profile handoff --output /tmp/vibe-screen-phase3/handoff.json
python3 scripts/phase3/security_vectors.py --output /tmp/vibe-screen-phase3/security-model.json
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
python3 scripts/phase3/android_internet_acceptance.py \
  --apk /absolute/path/to/app-debug.apk \
  --connect-tap 540,1600 \
  --streaming-pattern 'decoded.*frame|streaming active' \
  --input-pattern 'input.*ack' \
  --reconnect-pattern 'session_epoch.*2|reconnected' \
  --evidence /tmp/vibe-screen-phase3/android.json
```

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
