# WakeHost current-base evidence runbook

Use this runbook after the #225 baseline is present in the source under test.
The collector is read-only and consumes retained evidence; it does not sleep or
wake the Mac itself.

## Preconditions

- Use the latest intended `origin/main` commit and record its SHA.
- Run an identity-signed installed Host build with Screen Recording and any
  required local permissions already granted.
- Enable macOS Wake for network access and confirm the target NIC or firmware
  can respond to Wake-on-LAN.
- Verify the router, switch, VLAN, or directed-broadcast path can deliver WOL
  packets to the sleeping Mac.
- Pair the client through the product flow and record the actual device
  identity used for the run.

## Required observations

Create a JSON object with explicit boolean observations matching the gate field
names. Include retained artifact paths for logs, packet captures, screenshots,
router output, and command transcripts. Then run:

```bash
make wake-host-current-base-gate \
  EVIDENCE_DIR=docs/changes/2026-08-23-wake-host-current-base/evidence/<run> \
  WAKE_HOST_CURRENT_BASE_JSON=docs/changes/2026-08-23-wake-host-current-base/evidence/<run>/wake-host-current-base-observations.json
```

The generated `wake-host-current-base-gate.json` exits zero only for `pass`.
`blocked`, `insufficient`, or `fail` outputs are still useful evidence, but they
do not close the WakeHost current-base gate.

## Blocking result for this owner update

This owner update has no access to a controlled sleeping Mac plus verified WOL
network path. Keep the gate blocked until a future run supplies all required
observations and retained artifacts.
