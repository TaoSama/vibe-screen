# HarmonyOS current-base aggregate owner audit

Date: 2026-08-23; rebased check: 2026-08-24
Base: `origin/main` at `b759d785898ede5bbd4370255b3d49e56457f0ef`
Scope: current-base owner selection and fail-closed evidence routing only. This
record does not close any HarmonyOS real-device gate.

## Current-base owner

This branch is the current-base aggregate owner successor for the Phase 4
README gate surface. It refreshes the owner-gate approach from PR #283 onto
`b759d785898ede5bbd4370255b3d49e56457f0ef`, expands the aggregate scope to the
full DevEco/HAP/decode/HUKS/authenticated-transport/resume/MatePad surface, and
absorbs the strict evidence-root hardening from PR #269. PR #250 remains a
README-only support change that clarifies component-level decode and resume
ownership, not a competing aggregate owner path.

PR #239 remains the semantic MatePad Mini acceptance package design, not a
replacement for this current-base owner gate. Its refreshed branch consumes this
gate output as an input to the final acceptance package instead of creating a
second final-owner path.

## Open PR owner map

| PR | Current status | Owner decision | Notes |
| --- | --- | --- | --- |
| #283 | draft; behind current main | Prior current-base gate candidate | Superseded by this branch because this branch is based on current `origin/main` and expands scope beyond decode/HAP/resume. |
| #239 | refreshed against current main | MatePad acceptance package design owner | Keep as the final acceptance package layer that consumes this current-base gate; it does not itself close real-device gates without MatePad evidence. |
| #269 | draft; behind current main | Support verifier hardening | Strict evidence-root validation is folded into this branch. |
| #250 | draft; rebased onto current main | Support README attribution | Keep as a narrow README clarification; it does not replace this aggregate owner gate. |
| #202 | draft; conflicts with current main | Focused authenticated-record support | Needs refresh before feeding the aggregate owner; not a final closure owner. |
| #203 | draft; conflicts with current main | Focused AVCodec hardware-decode support | Needs real DevEco/HAP/MatePad decode evidence before it can close decode gates. |
| #204 | draft; conflicts with current main | Focused HUKS secure-pairing support | Needs real HUKS runtime and Host/Authority compatibility evidence. |
| #205 | draft; conflicts with current main | Focused Host resume interop support | Needs resume-capable Host plus HarmonyOS device evidence; also introduces `resume_capable_host_interop` expected by this aggregate gate. |
| #206 | draft; conflicts with current main | Focused HAP lifecycle support | Needs DevEco build, signed HAP, install, launch, upgrade, rollback, and cleanup evidence. |
| #210 | draft; behind current main | Support controller-status guard | Keep as docs/static guard input; controller device behavior remains MatePad acceptance evidence. |

## Aggregate gate contract

`make harmony-current-base-gate EVIDENCE_DIR=...` reads:

- `harmony-readiness.json` from `make harmony-readiness`; and
- `harmony-device-gates.json` from the strict MatePad Mini device evidence package.

It writes `harmony-current-base-gate.json` and exits nonzero unless all owner
groups are closed by real evidence:

| Owner group | Required evidence boundary |
| --- | --- |
| `deveco_build` | `deveco_sdk_and_api_checker` plus DevEco/Hvigor/OHPM/HDC readiness. |
| `hap_sign_install` | `signed_release_hap` and `hap_install_launch` plus signed-HAP lifecycle artifacts. |
| `hardware_decode_capability` | H.264 and HEVC hardware decode device gates plus AVCodec evidence. |
| `huks_secure_pairing` | HUKS-backed pairing and credential revocation/replay gates. |
| `authenticated_transport` | authenticated transport record evidence; plaintext legacy fallback is not enough. |
| `host_resume_interop` | Protocol v1 interop, lifecycle/network/host-restart resume, stale-epoch rejection, and resume-capable Host evidence. |
| `matepad_acceptance` | permission, input matrix, eight-hour soak, and external-camera latency evidence. |

The gate also calls the strict `harmony_device_gate` validator with the manifest
directory as evidence root. A final pass therefore requires local relative
evidence files under the package. URLs, absolute paths, missing artifacts,
directories, and path traversal fail closed.

## Evidence boundary

No DevEco SDK, signed HAP, MatePad Mini HDC target, HUKS secure-pairing run,
authenticated Harmony transport run, hardware decoder output, Host resume
interop run, eight-hour soak, or external-camera latency package was produced
for this audit. Android evidence, including Nubia P0110/pacific or Xiaomi/fuxi
records, cannot close HarmonyOS or MatePad Mini gates.

The expected result in ordinary CI or this local environment is `blocked`, not
`pass`. A `pass` is only valid after a real MatePad Mini evidence package
passes both `make harmony-device-gate` and `make harmony-current-base-gate` on
the current source tree.
