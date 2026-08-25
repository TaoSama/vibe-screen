# coturn reconciliation product slice — 2026-08-25

This current-base evidence note covers a local operator/product slice for the
Phase 3 coturn exporter, reconciliation loop, and active-allocation disconnect
executor boundary. It is not a public Internet release pass.

## Scope

- `scripts/phase3/coturn_allocation_exporter.py` adapts a reviewed structured
  collector JSON file into the strict snapshot accepted by Authority
  reconciliation. It rejects human log-like fields, secret-like keys, duplicate
  allocations, malformed timestamps, and TURN REST usernames not bound to the
  declared device ID.
- `scripts/phase3/coturn_reconciliation_loop.py` wraps the existing Authority
  reconciliation helper in a bounded loop, persists consecutive missing-allocation
  state, emits JSONL iteration records, and reports ledger-close candidates only
  after the configured threshold.
- `scripts/phase3/coturn_disconnect_executor.py` consumes the exact environment
  exported by `coturn_reconcile.py --disconnect-command`, marks one local active
  allocation inactive, and writes a non-secret audit record. It is idempotent only
  for the same allocation and reason.

## Verification commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  scripts/phase3/coturn_allocation_exporter.py \
  scripts/phase3/coturn_reconciliation_loop.py \
  scripts/phase3/coturn_disconnect_executor.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/phase3/test_coturn_allocation_exporter.py \
  tests/phase3/test_coturn_reconciliation_loop.py \
  tests/phase3/test_coturn_disconnect_executor.py -v
make phase3-coturn-reconciliation-product-slice
```

The focused tests prove the local contracts for stale allocation tracking and
Authority-reported revoked allocation remediation through the disconnect
executor. `services/authority/internal/authority/server_test.go` also covers the
quota-enforcement handoff: Authority closes the ledger allocation after quota
overage and later reports the same source-observed allocation as
`revoked_allocation_ids`, which is the operator-side disconnect trigger.

## Release-gate boundary

This evidence does not include a public IP path, deployed remote TURN service,
live coturn control socket or provider API, real ScreenCaptureKit capture,
Android MediaCodec decode, packet capture, network handoff, external-camera
latency samples, or two-hour mixed-route soak. No Android device was used for
this local operator-slice verification; it therefore records no Nubia P0110 or
Xiaomi/fuxi device result. The Phase 3 public Internet release gate remains
blocked until those production artifacts exist and pass the release verifier.
