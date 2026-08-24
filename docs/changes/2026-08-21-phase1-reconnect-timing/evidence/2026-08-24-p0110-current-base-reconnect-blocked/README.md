# P0110 current-base reconnect timing blocked matrix owner

This directory records a current-base blocked readiness check for the Phase 1
reconnect-within-three-seconds timing gate. It is not a reconnect pass and must
not be used to close the README gate.

## Target

- Device target: nubia P0110 / pacific / Android 16 / SDK 36 / `EP0110PZ0B9110300B`
- Gate profile: `phase1-reconnect-within-3s`
- Required disruption scenarios: `client-kill`, `adb-reverse-disconnect`,
  `lan-network-interrupt`
- Repository base: latest `origin/main` at `6cdb34a1` plus the local reconnect
  timing verifier update on `codex/reconnect-timing-p0110-matrix`

## Readiness observations

Read-only device probes used explicit `adb -s EP0110PZ0B9110300B ...` commands.
`device-info.json` records manufacturer `nubia`, model `P0110`, device/product
`pacific`, Android `16`, and SDK `36`. `adb-reverse.txt` records the existing
USB reverse mapping `UsbFfs tcp:54321 tcp:54321`, and `android-pid.txt` plus
`window-dumpsys.txt` show that `dev.telemachus.display/.MainActivity` was
present and foreground during the readiness check.

The real timing matrix was not started because the current Host and LAN
conditions were blocked:

- `host-54321-listener.txt` records the `lsof -nP -iTCP:54321 -sTCP:LISTEN`
  probe, exit status `1`, and no process listening on TCP `54321`.
- `macos-dev-host-preflight.txt` reports the stable `Vibe Screen Dev` signing
  identity is unavailable in the current keychain. TCC state was therefore not
  evaluated for a stable Host binary.
- `trusted-lan-preflight.json` reports the P0110 Wi-Fi is not associated,
  `wlan0` is down or has no IPv4 address, and Android has no `wlan0` route to
  the Mac LAN IPv4 candidate. Its claims keep `reconnect=false` and
  `trusted_lan_encrypted=false`.

No `client-kill`, ADB reverse removal/restoration, or trusted-LAN network
interruption was run for this blocked record. ADB reverse presence and Android
foreground state are readiness context only; they are not Protocol v1 recovery
timing evidence.

## Summary

`reconnect-timing-summary.json` was generated with `make
evidence-reconnect-timing-blocked` and records:

- `verdict=blocked`
- `can_close_timing_gate=false`
- `can_close_requested_scope=false`
- `full_gate_missing_disruptions=[client-kill, adb-reverse-disconnect, lan-network-interrupt]`

The blocked summary deliberately points at retained artifacts rather than
promoting older reconnect smoke logs or Host accept lines.

## Validation

Focused verifier coverage was run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_reconnect_timing -v
```

The evidence JSON files were checked with `python3 -m json.tool`, and
`SHA256SUMS` records the retained artifact hashes.
