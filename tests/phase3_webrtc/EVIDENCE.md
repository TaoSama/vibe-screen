# Phase 3 local WebRTC historical record — obsolete

The previous 2026-08-04 `local-direct.json` and `local-relay.json` files were
removed on 2026-08-06. They are not evidence: they recorded no reachable Git
commit or source fingerprint, predated build-manifest binding, and the relay
file did not contain the current `forced_libwebrtc_relay` proof. Their binary
hashes and `PASS` summaries must not be used to infer current behavior.

The old text also described a separate `turnutils` 3/3 datagram smoke. That was
an earlier harness boundary and is not a current runner result. The current
relay proof is the forced selected libwebrtc relay candidate pair from the same
trusted terminal record as the application-E2EE and product-session markers.

## Current executable workflow

Run from the repository root. Private outputs stay under ignored `.build/`
paths so the output write does not invalidate its own source fingerprint:

```bash
python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode direct --slice product \
  --diagnostics-dir .build/phase3-local-synthetic-product-e2e/direct-logs \
  --output .build/phase3-local-synthetic-product-e2e/direct.json
python3 scripts/phase3_webrtc/run_local_e2e.py \
  --mode relay --slice product --skip-build \
  --diagnostics-dir .build/phase3-local-synthetic-product-e2e/relay-logs \
  --output .build/phase3-local-synthetic-product-e2e/relay.json
python3 scripts/phase3_webrtc/public_artifacts.py \
  --root .build/phase3-local-synthetic-product-e2e \
  --output .build/phase3-local-synthetic-product-e2e/public
```

Only the fixed allowlist-only `<private-root>/public` projection is uploadable.
The projector rejects alternate output paths and requires the direct and relay
records to carry the same commit, source fingerprint, and artifact hashes. The private JSON,
raw process output, credentials, addresses, and local paths remain private.
Every current private record must include a reachable repository revision, the
complete source fingerprint, and artifact hashes validated against the build
manifest.
