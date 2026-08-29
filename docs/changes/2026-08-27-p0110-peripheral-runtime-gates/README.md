# P0110 peripheral runtime gates current-base refresh

Date: 2026-08-27

Latest PR-head refresh: `5d72a6bec2632ae333b1956331b746e463555ccb`, after
merging `origin/main` at `c0e4263f7af2d2ab1131e7fc15e5e9d3e3fef443` into
`codex/p0110-peripheral-runtime-gates`. Historical current-base evidence from
`3b2ba11e832a3618eaedfc67f92414b161423a00` remains below as the previous
snapshot.

Device under test: `nubia P0110 / pacific / Android 16 / SDK 36`; public
evidence redacts the ADB serial as `[redacted-device-serial]`. Do not relabel this
evidence as Xiaomi 13/fuxi.

## Scope

This refresh checks the README runtime gates for physical stylus drawing-app
confirmation, controller runtime acceptance, native pointer HID mouse
confirmation, hardware-keyboard workflow, and the generic peripheral-input
framework boundary. It does not close any runtime gate. Capability/readiness
snapshots and offline gates remain separate from physical runtime acceptance.

## Results

| Gate | Evidence | Verdict | Can close gate | Blocking reason |
| --- | --- | --- | --- | --- |
| macOS Host readiness prerequisite | `host-readiness-current-pr-head/host-readiness.json` | `blocked` | `false` | Current source was clean at the start of collection, but the installed Host lacks source provenance, TCC cannot be verified read-only, the virtual HID entitlement is missing, and Launch-at-Login remains unverified. The default readiness path now skips the local login-item diagnostic so automated tests and CI do not invoke the macOS login-item dump tool; that diagnostic is explicit opt-in only. |
| Controller runtime acceptance | `../2026-08-19-controller-runtime-acceptance/evidence/2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483/controller-runtime-summary.json` | `blocked` | `false` | No physical Android `SOURCE_GAMEPAD`/`SOURCE_JOYSTICK` controller was visible; the Host is not identity-signed with the approved virtual HID entitlement and no virtual-gamepad availability, Mac-side response, or neutral-release evidence exists. |
| Physical stylus drawing app | `../2026-08-19-physical-stylus-acceptance/evidence/2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483/stylus-summary.json` | `blocked` | `false` | P0110 exposes pass-eligible `goodix_stylus_input` capability, but no physical drawing was observed and no same-session Android `Stylus forwarded`, Host `Stylus injected`, stable signed/TCC Host, or visible macOS drawing-app evidence was captured. |
| Native pointer HID mouse | `native-pointer-hid-current-pr/native-pointer-hid-summary.json` | `blocked` | `false` | No external Android input device with `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source was attached; stable signed/TCC Host evidence is also missing. |
| Hardware keyboard workflow | `hardware-keyboard-current-pr/hardware-keyboard-summary.json` | `blocked` | `false` | No external Android-attached keyboard was visible; Host listener was observed, but stable signed/TCC readiness and physical key workflow evidence are missing. |
| Generic peripheral-input framework | `docs/changes/2026-08-23-peripheral-input-framework/TEST.md` | offline readiness only | `false for concrete peripherals` | The framework is capability-gated and fail-closed with `unsupported_peripheral_kind`; it is not a runtime pass for any concrete peripheral. |

## Commands

All Android commands used an explicit serial target. Public command examples
redact that serial and local paths.

```bash
git fetch origin --prune
git merge --no-edit origin/main

make baseline-macos-host-readiness \
  EVIDENCE_DIR=docs/changes/2026-08-27-p0110-peripheral-runtime-gates/host-readiness-current-pr-head

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 scripts/controller_runtime_readiness.py \
  --serial [redacted-device-serial] \
  --host-log <host-log> \
  --host-app "/Applications/Vibe Screen.app" \
  --redact-identifiers \
  --evidence-dir docs/changes/2026-08-19-controller-runtime-acceptance/evidence/2026-08-27-p0110-controller-runtime-current-pr-blocked-7e06483

make physical-stylus-acceptance \
  EVIDENCE_SERIAL=[redacted-device-serial] \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_DIR=docs/changes/2026-08-19-physical-stylus-acceptance/evidence/2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483 \
  STYLUS_HOST_LOG=<host-log> \
  STYLUS_OBSERVE_SECONDS=0 \
  STYLUS_DRAWING_OBSERVATION=""

make native-pointer-hid-acceptance \
  EVIDENCE_SERIAL=[redacted-device-serial] \
  EVIDENCE_DIR=docs/changes/2026-08-27-p0110-peripheral-runtime-gates/native-pointer-hid-current-pr \
  NATIVE_POINTER_HOST_LOG=<host-log> \
  NATIVE_POINTER_OBSERVE_SECONDS=0 \
  NATIVE_POINTER_VISIBLE_RESULT_NOTE=""

make hardware-keyboard-readiness \
  EVIDENCE_SERIAL=[redacted-device-serial] \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_PORT=54321 \
  EVIDENCE_DIR=docs/changes/2026-08-27-p0110-peripheral-runtime-gates/hardware-keyboard-current-pr
```

Each runtime/readiness collector returned exit code `2`, which is the
expected blocked-readiness result. The controller summary CLI exits `2`; the
strict stylus, native-pointer, and hardware-keyboard gate targets with
`--require-pass` also exit `2`, confirming the generated summaries do not close
their runtime gates.

## Boundaries

- Synthetic `adb input` events were not used as physical peripheral evidence.
- `goodix_stylus_input` capability is readiness only; it is not physical
  drawing-app confirmation.
- Host listener observation alone is not stable signed/TCC readiness and cannot
  close pointer, stylus, keyboard, or controller gates.
- The generic peripheral-input framework remains an offline fail-closed contract
  and does not claim support for any concrete peripheral hardware.

## Integrity

`SHA256SUMS` files are included for the aggregate evidence directory and the
controller/stylus evidence directories refreshed by this run.

## Previous current-base snapshot

The previous 2026-08-27 clean `origin/main` snapshot at
`3b2ba11e832a3618eaedfc67f92414b161423a00` is retained in
`host-readiness/`, `hardware-keyboard/`, `native-pointer-hid/`,
`../2026-08-19-controller-runtime-acceptance/evidence/2026-08-27-p0110-controller-runtime-current-base-blocked-3b2ba11/`,
and
`../2026-08-19-physical-stylus-acceptance/evidence/2026-08-27-nubia-p0110-pacific-stylus-current-base-blocked-3b2ba11/`.
It was also blocked and did not close any physical peripheral runtime gate.
