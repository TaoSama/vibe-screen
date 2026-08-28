# P0110 current-base USB reconnect timing blocked readiness

This directory records a current-base blocked readiness check for the Phase 1
reconnect-within-three-seconds timing gate. It is not a reconnect pass and must
not be used to close the README gate.

## Target

- Device target: Nubia P0110 / pacific / Android 16 / SDK 36 / `EP0110PZ0B9110300B`
- Gate profile: `phase1-reconnect-within-3s`
- Required full-gate disruption scenarios: `client-kill`,
  `adb-reverse-disconnect`, and `lan-network-interrupt`
- Current source commit: `0c3e2e95d74ceedcd746a9c89d354d0ae102e794`, based
  on latest `origin/main` commit `0c1b3fd5a3d917acd5308b7ef10bc95900a45039`

## Readiness observations

Read-only device probes used explicit `adb -s EP0110PZ0B9110300B ...` commands.
`device-info.json` records manufacturer `nubia`, model `P0110`, device/product
`pacific`, Android `16`, and SDK `36`. `adb-reverse-before.txt` records the
existing USB reverse mapping `UsbFfs tcp:54321 tcp:54321`, and
`android-pid-before.txt` shows `dev.telemachus.display` was running.

The Host listener prerequisite improved compared with the 2026-08-24 blocked
record: `host-54321-listener.txt` records `/Applications/Vibe Screen.app` PID
`4810` listening on `127.0.0.1:54321`.

The real USB timing attempts were still blocked before disruption because the
source-bound stable Host prerequisite was not satisfied:

- `host-readiness.json` reports `status=blocked`.
- The configured `Vibe Screen Dev` signing identity could not be resolved from
  the current keychain for rebuilding a source-bound Host.
- The installed Host has no source commit/tree provenance, so it cannot be tied
  to current source commit `0c3e2e95d74ceedcd746a9c89d354d0ae102e794`.
- TCC Screen Recording and Accessibility could not be verified read-only for the
  installed Host because the user and system TCC database reads failed.

No `client-kill`, ADB reverse removal/restoration, or trusted-LAN network
interruption was run for this blocked record. The observed Host listener, ADB
reverse mapping, and running Android process are readiness context only; they
are not Protocol v1 recovery timing evidence.

No `/usr/bin/sfltool dumpbtm` command was executed. The only sfltool-related
commands were `pgrep -x sfltool`, recorded in `sfltool-pgrep-start.*` and
`sfltool-pgrep-end.*`.

## Summary

`reconnect-timing-summary.json` was generated with `make
evidence-reconnect-timing-blocked` and records:

- `verdict=blocked`
- `can_close_timing_gate=false`
- `can_close_requested_scope=false`
- `full_gate_missing_disruptions=[client-kill, adb-reverse-disconnect, lan-network-interrupt]`

The blocked summary deliberately points at retained prerequisite artifacts
rather than promoting listener, ADB reverse, retry, or foreground-state lines to
reconnect timing evidence.

## Validation

Focused verifier coverage was run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_reconnect_timing -v

PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest scripts.tests.test_release_tools -v
```

Both commands passed.
