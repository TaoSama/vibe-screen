# Internet Latency Gate Blocked — 2026-08-21

This record captures the repository-side readiness check for the Phase 3
Internet glass-to-glass latency gate. It does not claim a passing Internet
latency run. No public TURN deployment, independently operated remote peer, or
raw external-camera recording from a public-Internet path is present in this
evidence directory.

## Scope

- Device identity reserved for a future qualifying Android run: nubia P0110,
  codename pacific, Android 16.
- Gate profile: `internet-glass-to-glass-sub150`.
- Transport boundary: WebRTC Internet only; this is separate from trusted LAN
  and must not reuse `lan-glass-to-glass-sub80`.
- Current result: blocked. The synthetic sample values exercise the numeric
  threshold path, but the formal verifier fails closed because the manifest
  intentionally omits `internet_route`.

## Required Missing Evidence

- A raw high-frame-rate external-camera video that frames the Mac stimulus and
  Android render result on one timebase.
- A deployed public STUN/TURN service with redacted endpoint/provenance, TLS or
  TURN mode, credential source, and selected candidate-pair evidence.
- An independently operated remote peer on a different public network; a local
  coturn loopback, same-private-network peer, or synthetic Protocol v1 peer does
  not qualify.
- The formal manifest `internet_route` object binding route, TURN deployment,
  remote peer, candidate pair, and non-LAN topology.

## Verifier Result

`summary.json` shows the synthetic rows would pass the numeric P95 threshold:
P95 is 128 ms against the 150 ms threshold.

`latency-evidence-report.json` is the acceptance result for this package and is
intentionally insufficient:

```text
verdict: insufficient
reason: internet_route is required for internet-glass-to-glass-sub150 and must record the public TURN deployment, remote peer, selected candidate pair, and non-LAN network topology
```

This is the desired fail-closed behavior for the current repository state. The
gate can close only with a real evidence package following
[`docs/runbook/latency-measurement.md`](../../../../runbook/latency-measurement.md).
