# Phase 3 public Internet remote TURN blocked evidence - 2026-08-21

This record captures the fail-closed public Internet remote TURN preflight and
Internet soak boundary for the current local workspace. It is a BLOCKED record,
not public Internet, real remote TURN, Android-device, real-screen-capture,
network-handoff, latency, or soak evidence.

## Result

The preflight did not pass because this workspace does not contain the required
production deployment material. The checked-in production coturn policy was
readable and matched the expected TLS/auth/private-peer-deny shape, but the
ignored production relay configuration, runtime secret file, TLS certificate
chain, TLS private key, public external TURN address, Authority readiness probe,
and relay readiness probe were unavailable.

The soak summary is also BLOCKED. No remote TURN verifier output and no private
two-hour Internet soak summary were supplied, so the runner intentionally wrote a
blocked result instead of reusing local loopback or forced local coturn evidence.

## Evidence layout

- `preflight.json`: structured public Internet remote TURN preflight result.
- `soak-summary.json`: structured Internet soak boundary result.
- `deployment-prerequisites.md`: deployment prerequisites that must exist before
  this gate can produce pass evidence.
- `privacy-scan.json`: deterministic scan for committed evidence privacy.
- `SHA256SUMS`: integrity binding for every archived file except itself.

## Boundary

This record does not promote any existing local result. In particular, local
loopback, forced local coturn, synthetic Protocol v1 media, and local readiness
checks remain valid only for their own layers and cannot close the Phase 3 public
Internet release gate.
