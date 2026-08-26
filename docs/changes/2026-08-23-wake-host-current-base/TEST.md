# WakeHost current-base verification

## Local checks

Run from the repository root:

```bash
PYTHONPATH=tools python3 -m unittest tools.tests.test_wake_host_current_base tools.tests.test_schemas
make wake-host-current-base-gate EVIDENCE_DIR=.build/evidence/wake-host-current-base-smoke-20260823; test $? -eq 2
jq -e '.verdict == "blocked" and (.can_close_wake_host_current_base_gate == false) and (.can_claim_sleeping_mac_wake == false)' .build/evidence/wake-host-current-base-smoke-20260823/wake-host-current-base-gate.json
python3 -m unittest contracts.tests.test_security_contract
cd baseline/MacHost && swift build -c release
cd baseline/MacHost && .build/release/Vibe\ Screen --protocol-v1-self-test
cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.WakeHostTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest
git diff --check
```

The `wake-host-current-base-gate` smoke is expected to exit nonzero while no
real sleeping-Mac evidence is supplied. Its retained JSON should contain
`verdict=blocked`, `can_close_wake_host_current_base_gate=false`, and
`can_claim_sleeping_mac_wake=false`.

## Current status

No real sleeping Mac, router broadcast or directed WOL delivery, NIC firmware
configuration, packet capture, or post-wake Host availability evidence is
recorded by this change. The current-base gate therefore remains blocked by
design.
