# 2026-08-30 Nubia P0110 latency camera current-base preflight: blocked

This record refreshes current-base ownership for the README USB/LAN glass-to-glass and
input P95 latency gates on origin/main commit
`87e16d8bea4446c1ca449045678f1bafc7fd6cb2`. The evidence date is 2026-08-30 in
Asia/Shanghai local time; machine-readable collection timestamps remain in UTC.
It uses the connected Android acceptance substitute recorded as
`nubia-p0110-pacific-device-1`.

## Verdict

BLOCKED for formal performance-gate closure. The Nubia P0110/pacific Android 16
/ SDK 36 device was reachable through the required explicit ADB target form and
its identity is recorded in `device-info.json`, but this evidence directory
intentionally contains no external-camera recording, no annotated latency
samples, no synchronized-clock proof, no formal latency manifest, and no
profile-specific transport or physical-input artifact. Therefore it does not
close any of these profiles:

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

The fail-closed preflight target returned exit `2`, which means blocked
readiness rather than malformed input or a failed latency measurement.

## Current-base owner boundary

- This record is based on the latest fetched `origin/main` commit
  `87e16d8bea4446c1ca449045678f1bafc7fd6cb2`.
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

## Blockers

- USB glass-to-glass: no external camera or optical single-timebase, no raw
  high-frame-rate camera recording, no annotated samples, no formal manifest,
  and no profile-specific USB active-stream latency artifact.
- LAN glass-to-glass: no external camera or optical single-timebase, no raw
  high-frame-rate camera recording, no annotated samples, no formal manifest,
  and no trusted-LAN active-stream latency artifact.
- Input P95: no external-camera package and no synchronized-clock package with
  before/after skew checks, drift check, and total error budget below 5 ms; no
  direct latency samples, formal manifest, physical input actuation record, or
  visible Mac-side result record.

The local camera preflight saw only the built-in MacBook Pro camera and no
retained 120 FPS+ package framing both endpoints. A scan of the Phase 0 evidence
tree found no `raw-camera.mov`, `manifest.json`, `samples.csv`, or
`latency-evidence-report.json` package for the three README latency profiles.

## Artifacts

- `device-info.json`: ADB identity for Nubia P0110/pacific with the raw serial
  replaced by `nubia-p0110-pacific-device-1` and local SDK paths redacted.
- `preflight-input.json`: declared readiness checks for the three README
  latency profiles.
- `latency-preflight.json`: machine-readable blocked preflight report generated
  by `make evidence-latency-preflight`.
- `latency-preflight-exit.txt`: captured target exit status, `2`.
- `camera-preflight.txt`: local external-camera/formal-package readiness notes.
- `commands.txt`: commands run during this preflight and their outcomes.
- `SHA256SUMS`: retained artifact digests.

## Boundary

This record is a preflight/blocker record only. It proves the Android target was
reachable and records exactly why the latency gates remain open; it does not
measure USB glass-to-glass, LAN glass-to-glass, or input latency. Host/client
telemetry, decoder timings, RTT, screenshots, screen recordings outside a valid
external-camera evidence package, and ADB-generated input remain diagnostics
only and cannot close these gates.
