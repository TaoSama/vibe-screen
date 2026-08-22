# Phase 3 public Internet release-gate readiness - 2026-08-22

This record audits the Phase 3 public Internet release gate on clean
`origin/main` commit `de2752e0033713ad48bb7f86960f9180d8e7342f` after
`git fetch origin --prune`. It intentionally does not reuse the existing local
loopback, forced local coturn, or synthetic Protocol v1 results as public
Internet evidence.

## Result

**BLOCKED / insufficient for the public Internet release gate.** No public
deployment, remote TURN/NAT traversal, real Android UI/media decode, network
handoff, active revocation propagation, external-camera latency, or mixed-route
soak evidence was produced in this run.

The repository already has open PRs that target narrower parts of this gate:
current-base summaries, Android interop replacement, production enforcement,
release-gate manifests, public Internet evidence, soak, latency, revocation,
authority issuance, signaling PostgreSQL, coturn reconciliation, real-media
continuity, and network recovery. This record avoids duplicating those changes
and captures the current mainline readiness boundary instead.

## Production blockers

- Public deployment: no production signaling, Authority, relay, and coturn stack
  is evidenced on a public host with external TLS/private ingress, managed
  PostgreSQL, secret delivery, NTP monitoring, backup/restore, logs, alerts,
  quotas, and rate limits.
- Remote TURN/NAT: no evidence shows a real remote TURN candidate pair selected
  across a public Internet path; local loopback and forced local coturn remain
  local readiness only.
- Device media: no current commit evidence shows ScreenCaptureKit output encoded
  by the Host and decoded by Android MediaCodec through the Internet product
  session.
- Handoff/recovery: no Wi-Fi/cellular or independently routed network handoff run
  proves a new session epoch, keyframe recovery, and old-packet rejection.
- Revocation enforcement: control-plane revocation is not proven to disconnect
  the active peer and terminate existing coturn allocations in production.
- Performance/stability: no external-camera Internet latency package and no
  two-hour mixed direct/relay/network-change soak package are archived.
- Scale/operations: multi-instance signaling, load-balancer behavior, global
  create-rate enforcement, multi-region consistency, and authoritative provider
  billing reconciliation remain unproved.

## Evidence layout

- `readiness.json`: machine-readable fail-closed readiness result.
- `commands.txt`: command trace used for the audit and verification.
- `privacy-scan.json`: deterministic privacy scan for committed evidence files.
- `SHA256SUMS`: integrity binding for every archived file except itself.

## Interpretation

This record can be used as a current-base blocked readiness artifact. It cannot
close the Phase 3 public Internet release gate, and it must not be cited as a
successful public deployment, remote TURN, real capture, Android MediaCodec,
handoff, revocation, latency, or soak result.
