# 2026-08-27 WakeHost current-base blocked audit

## Result

Status: blocked. Gate closed: false.

This package refreshes the WakeHost current-base owner against origin/main
3b2ba11e832a3618eaedfc67f92414b161423a00. The runtime baseline still contains
the authenticated Protocol v1 WakeHost request path and UDP Wake-on-LAN magic
packet sender, and focused offline checks cover authorization, replay rejection,
policy denial, target validation, and completion responses.

## Boundary

The retained wake-host-current-base-gate.json keeps
can_close_wake_host_current_base_gate=false and
can_claim_sleeping_mac_wake=false. This is intentional: no real sleeping Mac,
WOL-capable router or directed broadcast route, NIC wake setting, packet capture,
or post-wake Host availability artifact was collected in this run.

## Files

- commands.txt - commands used for this current-base audit.
- wake-host-current-base-observations.json - explicit observations supplied to
  the machine gate.
- wake-host-current-base-gate.json - derived fail-closed gate summary.
