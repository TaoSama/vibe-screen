# Phase 3 local WebRTC evidence — 2026-08-04

## Environment

- macOS 26.4.1 arm64
- Go 1.24.13 darwin/arm64
- Swift 6.3.1, target arm64-apple-macosx26.0
- Python 3.11.15
- WebRTC Swift package 150.0.0, immutable revision
  `6ed87f05368632f71dc95c89c14c051561710925`
- coturn 4.16.0
- Repository commit unavailable because the repository has no initial commit

No ADB or Android device command was executed by this test.

## Commands and results

```bash
python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v
```

Result: PASS, 6 tests.

```bash
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode direct \
  --output tests/phase3_webrtc/evidence/local-direct.json
```

Result: PASS. The harness built isolated release artifacts, started the real
Go signaling binary, passed `/healthz` and `/readyz`, created a short-lived
authenticated session, and launched the macOS release CLI. Two real production
libwebrtc peer connections exchanged offer/answer and 10 SDP/ICE signaling
messages. The ordered/reliable control channel and unordered/zero-retransmit
media channel delivered Protocol v1 AES-256-GCM application records in both
directions. libwebrtc stats selected
`direct(local=host,remote=host,protocol=udp)`. Exact bearer values were absent
from signaling and peer process logs.

Recorded binaries:

- signaling SHA-256:
  `41c54e7b1a7ee8203f35dc2119fa827a55b318be7bbff2bd618f4de3ae7dba5a`
- macOS host SHA-256:
  `9823b03e4ef34e91ee90655000619acfcf4726f895d33bdd7c71b3af286acf17`

```bash
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode relay \
  --skip-build \
  --output tests/phase3_webrtc/evidence/local-relay.json
```

Result: PASS. A real local coturn process accepted an authenticated allocation
and relayed 3/3 datagrams. The same live server then carried the two production
libwebrtc peers with `forceRelay=true`; offer/answer and 4 relay-only ICE
messages passed, both channels delivered AES-256-GCM application records
bidirectionally, and libwebrtc stats selected
`relay(local=relay,remote=relay,protocol=udp)`. The temporary TURN
password was absent from captured coturn, utility, signaling, and peer output.

```bash
cd baseline/MacHost
swift build -c release
.build/release/Telemachus --phase3-internet-self-test
.build/release/Telemachus --phase3-webrtc-loopback-self-test
```

Result: PASS. The release build succeeded. The transport policy replaced a
pending stale frame with the latest keyframe (`latestFrameDrops=1`) and sent
only the first in-flight and newest pending payload. The real loopback peers
also passed ICE restart, bidirectional channels, and a stats-selected direct
candidate pair.

The relay control-plane hardening rerun also passed `make verify` under the Go
race detector, rejected the usage token at `/metrics`, required a separate
metrics token, exported the current-day estimated cost as a gauge, and synced
the state-file parent directory after atomic replacement.

```bash
cd services/signaling && make verify
```

Result: PASS. `gofmt`, `go vet`, and `go test -race -count=1 ./...` completed;
the real-process and internal signaling packages passed.

## Remaining boundary

The real peer E2E intentionally sends small test payloads and does not create
an artificial libwebrtc send backlog. Latest-frame replacement is instead
proved deterministically at the `WebRTCInternetTransport` policy boundary. This
run is local loopback evidence; it does not claim external-NAT or public TURN
reachability, Android interoperability, stream rendering, input, or soak.
