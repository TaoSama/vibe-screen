# Phase 3 Public NAT/TURN Readiness

This runbook defines the evidence needed before the Phase 3 public NAT/TURN path
can be treated as production-ready. It does not close the broader Phase 3
Internet release gate by itself; it only proves the deployed STUN/TURN slice is
real, remote, monitored, and fail-closed.

## Required Evidence

Collect all raw materials in a protected operator workspace first. Only curated,
sanitized summaries may be archived in the repository.

- Source provenance: clean repository commit, immutable service image digests,
  reviewed relay and coturn configuration hashes, and secret-file hashes.
- Public endpoints: observed STUN, UDP/TCP TURN, and TLS TURN endpoints, with DNS
  resolution to globally routable addresses. Archive hashes or redacted labels,
  not raw hostnames or addresses.
- TLS: certificate hostname validation, negotiated TLS 1.2 or newer, chain
  validation result, and remaining certificate lifetime.
- Credentials: Authority/relay-issued short-lived TURN credentials, the accepted
  TTL, a rotation or expiry drill, and rejection of the old credential after its
  TTL. Do not archive username/password material.
- Quotas: observed credential request limits, concurrent session or allocation
  limits, daily byte budget, coturn allocation quotas, and at least one denied
  over-limit request.
- Monitoring: allocation, authentication failure, relay byte, and quota decision
  metrics; canary history; and alert rules with named owners.
- Remote path: at least two observers outside the host network, a selected relay
  candidate pair, positive packet exchange, and no local coturn loopback or
  synthetic peer.
- Privacy: no raw endpoints, device identifiers, operator paths, bearer tokens,
  TURN credentials, private keys, or diagnostic bundles containing user content.

## Verification

Run scripts/phase3/public_nat_turn_preflight.py from the repository root after
the real deployment evidence is available. Provide the reviewed production relay
config, coturn config, runtime TURN secret file, TLS certificate and key,
COTURN_EXTERNAL_IP, Authority and relay readiness URLs, sanitized connectivity
evidence, sanitized deployment evidence, an output path, and an external canary
command that emits the same connectivity JSON on stdout.

The deployment evidence uses schema
dev.vibescreen.phase3-public-nat-turn-deployment/v1. A pass requires the
preflight to run the external canary during the same command and to match the
reviewed connectivity file. A saved JSON file alone is not enough.

When infrastructure, credentials, or remote observers are unavailable, rerun with
--allow-blocked and archive the blocked report with a privacy manifest. Do not
edit the report into a pass and do not use local coturn or loopback evidence as a
substitute for the public deployment.

## Release Boundary

A successful public NAT/TURN readiness preflight still does not prove real Mac
screen capture, Android MediaCodec decode, user input, network handoff,
cross-service revocation, latency, or soak. Those artifacts remain separate
Phase 3 Internet release gates and must be collected in the release evidence
package before changing product claims.
