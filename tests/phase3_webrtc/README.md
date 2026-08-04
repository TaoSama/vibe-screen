# Phase 3 local WebRTC E2E

This test starts the real Go signaling process, creates an authenticated session,
and invokes the release macOS CLI. That CLI creates two real
`stasel/WebRTC 150.0.0` peer connections, exchanges offer/answer and ICE through
HTTP signaling, opens the production control and media data channels, sends
payloads in both directions, and reports the selected candidate pair from
libwebrtc statistics without logging addresses or credentials.

Run the direct path from the repository root:

```bash
python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py'
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode direct \
  --output tests/phase3_webrtc/evidence/local-direct.json
```

The harness generates all bearer credentials in memory, uses an ephemeral
loopback port, scans process output for exact credential leakage, and records
only binary hashes and non-secret counters. It does not contact Android or ADB.

## Forced relay

The relay mode starts the Homebrew coturn data plane, proves an authenticated
allocation plus relayed datagrams with coturn's own real client and peer tools,
then injects the temporary TURN settings into the production macOS self-test.
The run passes only when libwebrtc reports a selected `relay` candidate pair:

```bash
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode relay \
  --skip-build \
  --output tests/phase3_webrtc/evidence/local-relay.json
```

TURN URL, username, credential, and `forceRelay=true` are passed only through
`VIBE_WEBRTC_ICE_URLS`, `VIBE_WEBRTC_ICE_USERNAME`,
`VIBE_WEBRTC_ICE_CREDENTIAL`, and `VIBE_WEBRTC_FORCE_RELAY`. The credential is
redacted from failure text and scanned against all captured process output.

`WebRTCInternetTransport` backlog behavior is deterministic policy rather than
an ICE property. Verify its bounded latest-frame replacement separately:

```bash
baseline/MacHost/.build/release/Telemachus --phase3-internet-self-test
```
