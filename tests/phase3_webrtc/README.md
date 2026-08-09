# Phase 3 local WebRTC E2E

This test starts the real Go signaling process, creates an authenticated session,
and invokes the release macOS CLI. That CLI creates two real
`stasel/WebRTC 150.0.0` peer connections, exchanges offer/answer and ICE through
HTTP signaling, opens the production control and media data channels, sends
payloads in both directions, and reports the selected candidate pair from
libwebrtc statistics without logging addresses or credentials.

Run the product slice from the repository root. Runtime evidence and private
diagnostics must stay under the ignored `.build/` tree so writing them cannot
change the source fingerprint they are bound to:

```bash
python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode direct --slice product \
  --diagnostics-dir .build/phase3-local-synthetic-product-e2e/direct-logs \
  --output .build/phase3-local-synthetic-product-e2e/direct.json
```

The harness generates all bearer and ICE credentials in memory, uses an
ephemeral loopback port, scans process output for exact username and credential
leakage, and records only binary hashes and non-secret counters. It does not
contact Android or ADB. Source fingerprints hash tracked worktree bytes
directly, so Git `assume-unchanged` and `skip-worktree` flags cannot hide a
build input change. Ignored files under the signaling or MacHost source roots
fail closed unless they are under an explicit `.build*` output directory.
The build manifest also binds the WebRTC framework's actual Mach-O and required
bundle layout. The runner copies MacHost and that framework into one random
owner-only snapshot and points `DYLD_FRAMEWORK_PATH` only at the snapshot, so a
replace-and-restore of the SwiftPM output cannot alter the loaded dependency.

## Forced relay

The relay mode starts the Homebrew coturn data plane and injects temporary TURN
settings into the production macOS self-test. The run passes only when
libwebrtc itself reports the forced selected `relay` candidate pair with both
local and remote candidate types equal to `relay`; a `relay(...)` label around
host candidates is rejected. There is no separate `turnutils` datagram smoke
in this runner:

```bash
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode relay --slice product --skip-build \
  --diagnostics-dir .build/phase3-local-synthetic-product-e2e/relay-logs \
  --output .build/phase3-local-synthetic-product-e2e/relay.json
python3 scripts/phase3_webrtc/public_artifacts.py \
  --root .build/phase3-local-synthetic-product-e2e \
  --output .build/phase3-local-synthetic-product-e2e/public
```

TURN URL, username, credential, and `forceRelay=true` are passed only through
`VIBE_WEBRTC_ICE_URLS`, `VIBE_WEBRTC_ICE_USERNAME`,
`VIBE_WEBRTC_ICE_CREDENTIAL`, and `VIBE_WEBRTC_FORCE_RELAY`. The username and
credential are redacted from failure text and scanned against all captured
process output. The runner opens and hashes coturn once, creates a private
execution snapshot, and uses that same snapshot for the version allowlist check
and the forced-relay process. Private and public evidence record its actual
execution SHA-256; direct evidence explicitly records `not_used`.
Only the generated `public/` projection is suitable for CI artifact upload;
the private evidence JSON and diagnostics remain local.

`WebRTCInternetTransport` backlog behavior is deterministic policy rather than
an ICE property. Verify its bounded latest-frame replacement separately:

```bash
"baseline/MacHost/.build/release/Vibe Screen" --phase3-internet-self-test
```
