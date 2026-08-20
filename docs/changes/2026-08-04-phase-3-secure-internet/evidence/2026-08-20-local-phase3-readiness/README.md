# Phase 3 local readiness evidence - 2026-08-20

This record captures local Phase 3 release-gate readiness checks on clean
`origin/main` commit `18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee`. It is not
Android-device, public-Internet, real-screen-capture, handoff, latency, or soak
evidence. Runtime PASS JSON and private diagnostics stayed under `.build/` so
the repository source fingerprint remains bound to source inputs only.

## Result

**PASS for the local readiness subset only.** The following commands completed
successfully in that run:

- `make protocol`
- `make phase3-test`
- `make phase3-local-synthetic-product-e2e`
- `make phase3-authority-container-test`
- `services/relay/integration/test-turn-rest.sh`
- `services/relay/integration/test-turn-peer-acl.sh`

The local synthetic product run generated redacted public summaries for direct
and forced relay routes. Both summaries are bound to commit
`18a6ea70d0fbf6bc187f5a7242424ad3e88cf5ee` and source fingerprint
`cff510433eb3fd750eec2286684e52cee9d225b8beeef589e186bfa514d3fb06`. Direct
selected a UDP direct candidate pair. Forced relay used coturn `4.16.0`, selected
a UDP relay candidate pair, and reported `forced_libwebrtc_relay=true`. Both
summaries explicitly record these limitations: `local_loopback_only`,
`synthetic_protocol_v1_device`, `no_android_device_or_ui`,
`no_real_screen_capture`, and `no_public_internet_path`.

The Authority container gate built the local non-root container, started the
local PostgreSQL-backed Compose stack, verified migration order, readiness,
restart-persistent admission state, fail-closed storage behavior, runtime
hardening, and secret-log scanning. The relay data-plane scripts verified
short-lived control-plane TURN credentials, authenticated allocation,
ChannelBind and relayed packet exchange, stable per-device quota principal,
quota `486`, authenticated `Refresh` release, and explicit `403` peer-policy
denial for private, CGNAT, link-local, internal, and IPv6 loopback ranges.

## Artifact hashes

The private logs and generated runtime artifacts remain outside the repository
under `.build/phase3-release-gate-readiness-18a6ea70-1787229350246/`. The hashes
below bind this note to those local files without committing runtime PASS JSON or
private diagnostics:

```text
2cefe64b050797778b93f09a55d0df0e75f23b135457992b7e3733dac6adabef  phase3-local-synthetic-product-e2e/public/direct.json
08c1c4df8e726815570032046a8e5188804f2108ad00aa570a8ea9564ce124ba  phase3-local-synthetic-product-e2e/public/relay.json
e5d3ae474f8d1ce9eb3a8197e22edee4ab040970fa73f275bb9f5008a107178b  make-protocol.log
1beb13ec3b0432abb0d5b71dd696f9718018fa765aa8e1913be441e14ef66ebc  make-phase3-test.log
029a0044d20a69db467baa3c0c4a0e6b79dc114d066bd751302453d1b27d8405  make-phase3-local-synthetic-product-e2e.log
19019fa2fb018cced274bfaf60d70e041f8b6bcc68a6fbff7d7095e9cdc6b17c  make-phase3-authority-container-test.log
7de4a1a551cb7c39f85d88a6639fefd4acada172c2a4afb38f9af1f718ea50f2  relay-turn-rest.log
5d02b3b3c48c45f22b76010fd277d07fad999b7fbf2d4e006dde4491945cfa45  relay-turn-peer-acl.log
```

## Evidence layout

- `README.md`: this human-readable local readiness summary.
- `privacy-scan.json`: deterministic scan proving the committed evidence files
  contain no unredacted network endpoints, hardware identifiers, credential
  material, URLs, or user absolute paths.
- `SHA256SUMS`: integrity binding for every archived file except itself.

## What this proves

- That source snapshot passed protocol format, lint, build, breaking, and
  protocol fixture tests.
- Phase 3 Go security, signaling, relay and authority verification passed, along
  with the Phase 3 Python static, privacy, source-evidence, production-profile,
  acceptance-script, local WebRTC runner, and security-vector suites.
- The current macOS product session can complete the local synthetic direct and
  forced-coturn relay WebRTC paths through the real signaling process, protected
  production M150 adapter, Protocol v1 application records, and synthetic peer.
- The local Authority and relay operational gates that can run without public
  infrastructure passed on this machine.

## What this does not prove

This record does not close the Phase 3 Internet release gate. It does not prove
Xiaomi 13 or Nubia Android-device behavior, Android UI, real ScreenCaptureKit
capture, visible Mac input effects, public Internet routing, real remote TURN,
packet-capture confidentiality, automatic network handoff, active TURN allocation
disconnect, multi-node deployment, production PostgreSQL TLS/HA/PITR/NTP,
external-camera latency, or mixed-route soak. Those remain open release gates.
