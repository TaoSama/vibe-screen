# 2026-08-28 WakeHost current-base blocked audit

## Result

Status: blocked. Gate closed: false.

This package refreshes the WakeHost current-base owner against origin/main
`43d31c35d2bb4457c74218d179ba1406c2fda815`. The runtime baseline still
contains the authenticated Protocol v1 WakeHost request path and UDP
Wake-on-LAN magic-packet sender. Focused offline checks cover the evidence gate,
Android authorization and replay handling, Android product-session fail-closed
behavior, and the macOS release build.

The focused MacHost XCTest command was attempted but blocked by the local Swift
toolchain because `XCTest` was unavailable. The release build and Protocol v1
self-test still passed, and no hardware WakeHost acceptance is claimed from this
package.

## Safety boundary

`pgrep -x sfltool || true` produced no output before the run; no residual
`sfltool` process was observed. This audit did not run `/usr/bin/sfltool
dumpbtm`, `--include-login-item-diagnostic`, `--inspect-login-items`, or
`--probe-login-items`. WakeHost current-base evidence requires Host TCC and real
sleep/wake proof, but it does not require Launch at Login inspection.

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
