# WakeHost current-base evidence owner

Status: current-base evidence owner active; real WOL acceptance blocked
Owner: #199 (`codex/phase5-wake-host-request`)
Baseline dependency: #225 (`codex/wake-on-lan-magic-packet`)
Started: 2026-08-23

## Goal

Keep the WakeHost current-base evidence gate tied to the latest `origin/main`
after the authenticated magic-packet baseline landed. The owner must make the
remaining sleep/wake evidence explicit and fail closed until retained hardware
and network artifacts prove the gate.

## Scope

- Treat #225 as the implemented baseline for authenticated Protocol v1
  WakeHostRequest handling and UDP Wake-on-LAN magic-packet emission.
- Add a current-base evidence summary gate that distinguishes offline baseline
  readiness from a real sleeping-Mac WOL pass.
- Document the exact hardware/network evidence required before WakeHost can be
  reported as closed.
- Preserve the existing default-deny behavior for USB/default sessions and any
  session without an available authorizer.

## Non-goals

- Do not replace #225's shared-secret HMAC baseline with the older draft
  pairing-bound ECDSA prototype from #199. That older diff predates #225 and
  conflicts with the current base.
- Do not mark WakeHost, remote wake, router broadcast, or firmware WOL as
  accepted from offline tests.
- Do not operate a real Mac sleep cycle, router, or device from this owner
  update.

## Acceptance Boundary

The current-base WakeHost gate can close only when a retained evidence record
shows all of the following: current `origin/main` revision recorded, #225
baseline present, focused offline authorization/protocol checks passed, actual
paired client identity recorded, identity-signed Host with required TCC
permissions, Wake for network access or NIC WOL configuration, real Mac sleep
state before the request, verified router broadcast or directed WOL delivery,
packet emission only after authorization, retained packet capture or router log,
observed Mac wake, post-wake Host availability, and negative rejected attempts
for unpaired, expired, replayed, and wrong-signature requests.

The offline security evidence must now identify focused coverage for clock-skew
accept/reject boundaries, active/previous/unknown key rotation behavior,
host/device identity binding, replay-store eviction, SecureOn password raw-byte
format validation, and rejected non-allowlisted broadcast targets. These are
necessary but not sufficient: hardware WOL remains blocked until the real sleep,
network delivery, packet capture, wake observation, and post-wake availability
artifacts are retained.

When any blocking hardware/network prerequisite is absent, the gate must report
`blocked` and both `can_close_wake_host_current_base_gate` and
`can_claim_sleeping_mac_wake` must remain false.
