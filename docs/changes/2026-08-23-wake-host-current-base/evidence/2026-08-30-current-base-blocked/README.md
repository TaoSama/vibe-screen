# 2026-08-30 WakeHost current-base blocked audit

## Result

Status: blocked. Gate closed: false.

This package refreshes the WakeHost current-base owner against origin/main
`a9791336a105d234609ab55dad0a2713957a142a`. The runtime baseline still
contains the authenticated Protocol v1 WakeHost request path and UDP
Wake-on-LAN magic-packet sender. Focused offline checks cover the evidence gate
and the fail-closed verification path.

No WakeHost hardware acceptance is claimed from this package. There is no
identity-signed installed Host with confirmed TCC readiness, no real Mac sleep
state, no Wake for network access / NIC WOL configuration, no verified router or
directed WOL delivery path, no packet capture or router logs, and no post-wake
Host availability evidence.

## Safety boundary

The explicit `pgrep -x sfltool` absence check observed no `sfltool` process
before the run; no residual `sfltool` process was observed. This audit did not
run `/usr/bin/sfltool dumpbtm`, `--include-login-item-diagnostic`,
`--inspect-login-items`, or `--probe-login-items`. WakeHost current-base
evidence requires Host TCC and real sleep/wake proof, but it does not require
Launch at Login inspection.

## Boundary

The retained `wake-host-current-base-gate.json` keeps
`can_close_wake_host_current_base_gate=false` and
`can_claim_sleeping_mac_wake=false`. This is intentional: no real sleeping Mac,
WOL-capable router or directed broadcast route, NIC wake setting, packet
capture, or post-wake Host availability artifact was collected in this run.

## Files

- `commands.txt` - commands used for this current-base audit.
- `wake-host-current-base-observations.json` - explicit observations supplied
  to the machine gate.
- `wake-host-current-base-gate.json` - derived fail-closed gate summary.
