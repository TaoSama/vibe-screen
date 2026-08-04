# Phase 3 relay data plane

This directory runs the Vibe Screen relay credential service beside a real
coturn TURN/STUN data plane. Both processes read the same runtime-only TURN REST
secret. The control plane issues a short-lived username/password; coturn checks
that HMAC before creating an allocation. TURN forwards WebRTC ciphertext and
does not receive Vibe Screen content keys or plaintext screen/input data.

## Local start and health check

Requirements are Docker Engine with Compose v2 and OpenSSL. Docker Desktop can
run this local profile, but the production host-network profile is Linux-only.

```bash
cd deploy/phase3
./scripts/generate-secrets.sh
docker compose pull coturn
docker compose build relay
docker compose up -d --wait
curl --fail http://127.0.0.1:8090/healthz
curl --fail http://127.0.0.1:8090/readyz
./scripts/verify-stack.sh
```

The last command asks the live control plane for a 120-second credential and
runs `turnutils_uclient` inside the coturn container. It fails unless actual
authenticated allocations exchange relayed packets. Container health checks
cover coturn STUN responsiveness and relay-process liveness; `/readyz` is the
authoritative relay storage readiness check. A network-disabled one-shot init
container assigns the named state volume to relay UID/GID 65532 before the
non-root scratch control-plane container starts.

The local profile intentionally disables TURN TLS and allows loopback peers so
the self-contained test works. Its relay UDP allocation range is
`49160-49200`, bound only to host loopback. It is not suitable for public
exposure. A phone cannot use the advertised/bound `127.0.0.1`: explicitly bind
the Compose TURN and relay-range ports to the Mac's device-reachable address
and replace the local JSON URIs before a separately authorized device test.

Stop without deleting quota state:

```bash
docker compose down
```

Delete the named `relay-data` volume only when deliberately discarding local
quota/revocation state. Secret files under `secrets/` and TLS files under
`tls/` are ignored by Git; `generate-secrets.sh` refuses to overwrite them.

## Production configuration

Production uses host networking so coturn can bind the full relay port range
without Docker userland-proxy mappings. Perform these steps on a dedicated
Linux host:

1. Copy `config/relay.production.example.json` to the ignored
   `config/relay.production.json`. Replace every example hostname and verify
   its `turn_realm` equals `COTURN_REALM`.
2. Provision independent secret files with mode `0600`; distribute the same
   `turn_secret.txt` to relay and coturn. Store/rotate them through the
   deployment secret manager, not source control.
3. Install the public certificate chain as ignored `tls/fullchain.pem` and its
   private key as `tls/privkey.pem`.
4. Set `COTURN_REALM` to the certificate DNS hostname and
   `COTURN_EXTERNAL_IP` to `public-ip/private-ip` behind one-to-one NAT, or to
   the public IP on a directly addressed host.
5. Allow inbound UDP/TCP 3478, TCP 5349, and UDP 49152-65535. Keep relay HTTP
   on loopback behind an authenticated TLS reverse proxy. Apply provider DDoS
   controls before these host rules.
6. Validate the effective configuration, start, and inspect health/logs:

```bash
export COTURN_REALM=relay.example.com
export COTURN_EXTERNAL_IP=203.0.113.10/10.0.0.10
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml pull coturn
docker compose -f docker-compose.production.yml build relay
docker compose -f docker-compose.production.yml up -d --wait
curl --fail http://127.0.0.1:8090/readyz
docker compose -f docker-compose.production.yml logs --since=10m relay coturn
```

`production.conf` enables UDP/TCP TURN, TLS on 5349, TLS 1.2+, fingerprints,
short nonces, per-user/total allocation quotas, a 20 MB/s allocation cap,
loopback/multicast peer denial, and a bounded relay range. Tune quotas from
observed demand; never remove peer filtering or broaden the range silently.

## Upgrade, rollback, and rotation

- Resolve a new immutable multi-platform image digest, audit its SBOM and
  licenses, update tag plus digest together, then run local credential/TURN and
  forced-relay canaries before production rollout.
- Back up the `relay-data` volume before changing the control-plane binary.
  Roll back binary/image/config together, but never roll back persisted device
  revocation or key epochs.
- Rotate API-token files one service at a time. TURN-secret rotation requires
  a bounded dual-key or drain window; this coturn profile accepts one REST
  secret, so the safe current procedure is to stop new credential issuance,
  wait at most the configured maximum credential TTL, drain allocations,
  replace the shared file on both services, and restart.
- Revocation stops future credential issuance only. For urgent abuse, also
  disable the signaling session and drain/terminate matching coturn
  allocations; do not wait for credential expiry alone.

## Abuse, observability, and current limitations

coturn enforces `user-quota`, `total-quota`, `max-bps`, peer-address filters,
nonce expiry, and a fixed port range. The relay control plane separately rate
limits issuance and exposes `/metrics` behind a dedicated metrics token. Place
both behind host/provider connection limits and alert on authentication failures,
allocation growth, relay bytes, port exhaustion, and credential rejections.

The repository still has no coturn-to-`/v1/usage` collector. Therefore the
control plane's daily-byte and per-device concurrent-session accounting is not
authoritative for this deployment; coturn's own limits remain the immediate
enforcement boundary. The control plane is also single-replica/local-state.
These are production launch blockers, not implied features.

## Provenance and license

No coturn source is copied into this repository. The Compose files execute the
external image below and the repository contributes only original
configuration and test scripts:

| Artifact | Immutable source | License | Use |
| --- | --- | --- | --- |
| coturn source | <https://github.com/coturn/coturn>, tag `4.7.0`, commit `678996a52954ddc7a44afd9f72f5b5c647e41083` | BSD-3-Clause | TURN/STUN server implementation; no source copied |
| coturn container | `coturn/coturn:4.7.0-r0`, manifest `sha256:99bf5bf6ab1c119862d0c3d2dfb2bbf805a86a131492cab18c148be64ae7d978`, image-build revision `aa685e2669bac662d553a3d8eef6412d95ba7664` | coturn BSD-3-Clause plus licenses of bundled distribution libraries | Runtime data plane; no image layer vendored |

The arm64 child manifest observed during verification was
`sha256:caac4599652148becc606d7cfc7acbc8cb42012df27ae013a627bde4ff493d4c`.
The upstream BSD license and copyrights remain in the image. A public release
must archive the image SBOM and all bundled dependency notices; describing the
whole image as only BSD-3-Clause would be incomplete. No GPL/AGPL code was
copied or translated for this deployment.
