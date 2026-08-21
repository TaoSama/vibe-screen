# Deployment prerequisites

Phase 3 public Internet pass evidence requires all of these prerequisites before
running the remote TURN verifier or Internet soak runner:

- Production relay configuration using the production Authority mode and
  PostgreSQL storage.
- Relay and Authority database connections with certificate and hostname
  verification.
- Public TURN DNS that resolves only to globally routable addresses.
- TURN TLS on the production TLS port with a deployed certificate chain and
  private key.
- File-backed TURN REST secret shared only by relay and coturn.
- coturn production ACL denying private, CGNAT, loopback, link-local, and ULA
  peers, with no broad peer allow override.
- Authority and relay readiness probes passing before routing clients.
- macOS Host and Android device artifacts built from the recorded source
  revision.
- A real remote TURN peer for relayed packet exchange, not a local loopback
  peer.
- A two-hour mixed direct, relay, and network-change Internet soak summary with
  route counts, handoff evidence, required metric families, and nonce-reuse
  checks.

The current local workspace has none of the production deployment materials
listed above except the checked-in static coturn production policy, so this run
is blocked by design.
