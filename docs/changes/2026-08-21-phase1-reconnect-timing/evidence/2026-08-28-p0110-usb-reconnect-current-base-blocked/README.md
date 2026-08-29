# P0110 current-base USB reconnect timing blocked readiness

This directory records a current-base blocked readiness check for the Phase 1
reconnect-within-three-seconds timing gate. It is not a reconnect pass and must
not be used to close the README gate.

## Target

- Device target: nubia P0110 / pacific / Android 16 / SDK 36 / `EP0110PZ0B9110300B`
- Gate profile: `phase1-reconnect-within-3s`
- Required full-gate disruption scenarios: `client-kill`,
  `adb-reverse-disconnect`, and `lan-network-interrupt`
- Current source commit: `ce6d1a763179a46ae3598d71a92e10e9647aa4d9`, based
  on latest `origin/main` commit `07bb40e18074fd737c4a70714b4faf4499ea64ab`

## Readiness observations

Read-only device probes used explicit `adb -s EP0110PZ0B9110300B ...` commands.
`device-info.json` records manufacturer `nubia`, model `P0110`, device/product
`pacific`, Android `16`, and SDK `36`. `adb-reverse-before.txt` records the
existing USB reverse mapping `UsbFfs tcp:54321 tcp:54321`, and
`android-pid-before.txt` shows `dev.telemachus.display` was running.

The Host listener prerequisite was not ready in this refresh:
`host-54321-listener.txt` is empty, `host-54321-listener.exit` is `1`, and
`host-readiness.json` reports `listener_status=blocked`.

The real USB timing attempts were still blocked before disruption because the
source-bound stable Host prerequisite was not satisfied:

- `host-readiness.json` reports `status=blocked`.
- The configured `Vibe Screen Dev` signing identity could not be resolved from
  the current keychain for rebuilding a source-bound Host.
- Codesign inspection of `/Applications/Vibe Screen.app` failed because the
  embedded WebRTC framework has missing sealed-resource entries.
- No Host listener was observed on TCP `54321`.
- TCC permissions were not inspected after Host bundle signing inspection
  failed.

No `client-kill`, ADB reverse removal/restoration, or trusted-LAN network
interruption was run for this blocked record. The Host listener probe, ADB
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
