# 2026-08-28 Nubia P0110 latency current-base preflight: blocked

This record refreshes current-base ownership for the README USB/LAN/input
latency gates on origin/main commit
`47361dd7f56fefef50da55a69e0368531c8ada33`. The evidence date is 2026-08-28 in
Asia/Shanghai local time; machine-readable collection timestamps remain in UTC.
It uses the connected Android acceptance substitute recorded as
`nubia-p0110-pacific-device-1`.

## Verdict

BLOCKED for formal performance-gate closure. The Nubia P0110/pacific Android 16
/ SDK 36 device was reachable through the required explicit ADB target form, and
the Mac host plus installed Host binary identity were recorded. USB reverse and
a local Host listener were visible, but this evidence directory intentionally
contains no external-camera recording, no annotated latency samples, no
synchronized-clock proof, no formal latency manifest, and no profile-specific
active stream or physical-input measurement artifact. Therefore it does not
close any of these profiles:

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

The fail-closed preflight target returned exit `2`, which means blocked
readiness rather than malformed input or a failed latency measurement.

## Current-base owner boundary

- This record is based on the latest fetched `origin/main` commit
  `47361dd7f56fefef50da55a69e0368531c8ada33`.
- The connected Android target was checked with the required explicit ADB target
  form. Public artifacts redact the raw Android serial to the stable evidence id
  `nubia-p0110-pacific-device-1`.
- This record owns only the current-base blocked/preflight state for the three
  README latency profiles. Actual closure still requires a passing formal
  latency evidence report with retained real measurement artifacts.

## Device preflight

The connected Android device reported:

- Manufacturer: `nubia`
- Model: `P0110`
- Codename/product: `pacific`
- OS: Android `16`, SDK `36`
- Evidence device id: `nubia-p0110-pacific-device-1`

This record is Nubia P0110/pacific evidence and must not be relabeled as Xiaomi
13/fuxi evidence.

## Host and transport preflight

- Host model: `Mac16,8`
- macOS: `26.4.1` build `25E253`
- Installed Host executable SHA-256:
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`
- Installed app bundle identifier: `dev.telemachus.display`
- Signing authorities: `Vibe Screen Dev`, `Vibe Screen Dev Root`;
  `TeamIdentifier=not set`
- USB reverse was present as `UsbFfs tcp:54321 tcp:54321`.
- `/Applications/Vibe Screen.app` was listening on `127.0.0.1:54321`.
- The Android application process was present, but this preflight did not retain
  formal active-stream latency artifacts.
- `wlan0` reported `NO-CARRIER` and `state DOWN`, with no route output, so no
  trusted-LAN latency run was available.

## Blockers

- USB glass-to-glass: no external camera or optical single-timebase, no raw
  camera recording, no annotated samples, no formal manifest, and no formal USB
  active-stream artifact retained in a latency evidence package.
- LAN glass-to-glass: no external camera or optical single-timebase, no raw
  camera recording, no annotated samples, no formal manifest, and no LAN
  network/active trusted-LAN stream artifact; the device Wi-Fi interface also
  had no carrier or route.
- Input P95: no external-camera package and no synchronized-clock package with
  before/after skew checks, drift check, and total error budget below 5 ms; no
  direct latency samples, formal manifest, physical input actuation record, or
  visible Mac-side result record.

A scan of the Phase 0 evidence tree found no retained `raw-camera.mov`,
`manifest.json`, `samples.csv`, or `latency-evidence-report.json` package for
the three README latency profiles.

## Artifacts

- `device-info.json`: ADB identity for Nubia P0110/pacific with the raw serial
  replaced by `nubia-p0110-pacific-device-1` and local SDK paths redacted.
- `host-identity.txt`: current Mac host and installed Host binary identity.
- `network-preflight.txt`: USB reverse, Host listener, Android app process, and
  wlan0/route observations.
- `camera-preflight.txt`: local camera/formal-package readiness notes.
- `preflight-input.json`: declared readiness checks for the three README
  latency profiles.
- `latency-preflight.json`: machine-readable blocked preflight report generated
  by `make evidence-latency-preflight`.
- `latency-preflight-exit.txt`: captured target exit status, `2`.
- `commands.txt`: commands run during this preflight and their outcomes.
- `SHA256SUMS`: retained artifact digests.

## Boundary

This record is a preflight/blocker record only. It proves the Android target,
Host identity, USB reverse, Host listener, and LAN route state observed during
the current-base check; it does not measure USB glass-to-glass, LAN
glass-to-glass, or input latency. Host/client telemetry, decoder timings, RTT,
screenshots, screen recordings outside a valid external-camera evidence package,
and ADB-generated input remain diagnostics only and cannot close these gates.
