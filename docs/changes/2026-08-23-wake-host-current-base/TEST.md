# WakeHost current-base verification

## Local checks

Run from the repository root:

```bash
PYTHONPATH=tools python3 -m unittest tools.tests.test_wake_host_current_base tools.tests.test_schemas
if make wake-host-current-base-gate EVIDENCE_DIR=.build/evidence/wake-host-current-base-smoke-20260823; then exit 1; else test "$?" -ne 0; fi
jq -e '.verdict == "blocked" and (.can_close_wake_host_current_base_gate == false) and (.can_claim_sleeping_mac_wake == false)' .build/evidence/wake-host-current-base-smoke-20260823/wake-host-current-base-gate.json
python3 -m unittest contracts.tests.test_security_contract
(cd baseline/MacHost && swift build -c release)
(cd baseline/MacHost && swift test --filter WakeHostTests)
(cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.WakeHostTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest)
git diff --check
```

The `WakeHostTests` coverage must include clock-skew accept/reject boundaries,
active/previous/unknown key rotation behavior, expected host/device identity
binding, replay-store eviction, SecureOn raw-byte length validation, and
broadcast-target allowlist negative cases. Do not use `swift run`, Host
self-tests, loopback harnesses, ADB, TCC, Keychain, signing, or system settings
for the offline contract pass.

The `wake-host-current-base-gate` smoke is expected to exit nonzero while no
real sleeping-Mac evidence is supplied. Its retained JSON should contain
`verdict=blocked`, `can_close_wake_host_current_base_gate=false`, and
`can_claim_sleeping_mac_wake=false`.

## Current status

No real sleeping Mac, router broadcast or directed WOL delivery, NIC firmware
configuration, packet capture, or post-wake Host availability evidence is
recorded by this change. The current-base gate therefore remains blocked by
design.
