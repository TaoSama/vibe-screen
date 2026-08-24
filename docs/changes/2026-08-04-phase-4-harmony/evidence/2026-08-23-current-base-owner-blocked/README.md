# HarmonyOS current-base owner blocked evidence

Date: 2026-08-23
Base: `origin/main` at `3d23de133adc4414b4c70430c619fadbe7d90207`
Branch: `codex/harmony-current-base-aggregate-owner`

This package records the current-base aggregate owner gate in a fail-closed
environment. It is not DevEco, signed-HAP, HUKS, authenticated-transport,
hardware-decoder, Host-resume, MatePad Mini, soak, or latency acceptance
evidence. It exists to show that the refreshed owner path refuses to close the
Phase 4 HarmonyOS gates when the required proprietary toolchain, signed HAP,
Protocol v1 Host identity, and real MatePad Mini evidence are absent.

Android evidence, including Nubia P0110/pacific or Xiaomi/fuxi records, cannot
close any HarmonyOS or MatePad Mini gate in this package.

## Commands

| Command | Exit | Interpretation |
| --- | ---: | --- |
| `make harmony-readiness EVIDENCE_DIR=docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-23-current-base-owner-blocked` | 2 | Expected blocked result: local DevEco/Hvigor/OHPM/HDC, signed HAP, MatePad target, and Host identity prerequisites are missing. |
| `python3 scripts/harmony_device_gate.py --template > harmony-device-gates.json` | 0 | Redaction-safe blocked device-gate template generation. |
| `python3 scripts/harmony_device_gate.py --allow-blocked --evidence-root ... harmony-device-gates.json` | 0 | Structural validation for a blocked manifest only; does not close real-device gates. |
| `make harmony-current-base-gate EVIDENCE_DIR=docs/changes/2026-08-04-phase-4-harmony/evidence/2026-08-23-current-base-owner-blocked` | 2 | Expected fail-closed aggregate result. The Make target exits 2 because the Python gate exits 1 and `make` reports `Error 1`. |

Retained stdout, stderr, and exit-code files are included beside each generated
JSON artifact.

## Result

`harmony-readiness.json` reports `verdict: blocked` with missing DevEco Studio,
`hvigor`, `ohpm`, `hdc`, signed HAP, signature certificate hash, checksum
manifest, clean final device tree, Protocol v1 Host commit, and Host build
hash.

`harmony-current-base-gate.json` reports `verdict: blocked`,
`can_close_readme_phase4_owner_gates: false`, and
`can_claim_harmony_device_pass: false`. The blocked owner groups are:

- `deveco_build`
- `hap_sign_install`
- `hardware_decode_capability`
- `huks_secure_pairing`
- `authenticated_transport`
- `host_resume_interop`
- `matepad_acceptance`

## Still open

The following gates still require real current-source evidence before they can
be closed:

- DevEco/Harmony SDK API checker and HAP build on the HarmonyOS source tree.
- Signed release HAP install, launch, upgrade, rollback, and cleanup on the
  target MatePad Mini.
- H.264 and HEVC AVCodec hardware-decoder identity and rendered-frame evidence.
- HUKS-backed pairing, credential expiry/replay rejection, and revocation.
- Authenticated Harmony transport records against the Protocol v1 Host.
- Resume-capable Host interop across background/foreground, network roam, Host
  restart, and stale-epoch rejection.
- MatePad Mini UI/input, permission retry, eight-hour soak, and external-camera
  latency package.
