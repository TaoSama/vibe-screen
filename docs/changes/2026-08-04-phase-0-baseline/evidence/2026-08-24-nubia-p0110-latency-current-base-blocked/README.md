# 2026-08-24 Nubia P0110 latency current-base preflight: blocked

This record refreshes the README Phase 1 USB/LAN glass-to-glass and input P95
latency gates on origin/main commit
`942fee8d1b8a4495c24dbe3a5aacf538e04bb6f0`. It uses the connected Android
acceptance substitute recorded as `nubia-p0110-pacific-device-1`.

## Verdict

BLOCKED for formal performance-gate closure. The Nubia P0110/pacific Android 16
device was reachable through the required explicit ADB serial and its identity is
recorded in `device-info.json`, but this evidence directory intentionally
contains no external-camera recording, no annotated latency samples, no
synchronized-clock proof, no formal latency manifest, and no profile-specific
transport or physical-input artifact. Therefore it does not close any of these
profiles:

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

The fail-closed preflight target returned exit `2`, which means blocked
readiness rather than a failed latency measurement.

## Current-base owner boundary

- PR #264 is open, draft, conflicting, and based on an older main commit. It
  remains fail-closed/readiness work, not real latency evidence.
- PR #192 is open, draft, stale/conflicting, and not merged. It remains an older
  latency coverage proposal and is not a current-base closure owner.
- This record owns the current-base blocked/preflight state for the three README
  latency profiles. Actual closure still requires a passing formal latency
  evidence report with retained real measurement artifacts.

## Device preflight

The connected Android device reported:

- Manufacturer: `nubia`
- Model: `P0110`
- Codename/product: `pacific`
- OS: Android `16`, SDK `36`
- Evidence device id: `nubia-p0110-pacific-device-1`

The live ADB checks used the required explicit serial form
`adb -s <device-serial> ...`; committed command transcripts and
machine-readable artifacts redact the raw ADB serial to either that placeholder
or the stable evidence id above. This record is Nubia P0110/pacific evidence and
must not be relabeled as Xiaomi 13/fuxi evidence.

## Blockers

- USB glass-to-glass: no Host/build identity for a measured run, no external
  camera timebase, no raw camera recording, no annotated samples, and no formal
  manifest. A later read-only live USB observation in this directory saw Host
  loopback listening, ADB reverse, foreground Android app state, and app-private
  Protocol v1/HEVC decode context, but the formal USB live-smoke helper still
  returned `insufficient` because current-process logcat did not contain the
  required telemetry and decoder evidence.
- LAN glass-to-glass: no Host/build identity for a measured run, no external
  camera timebase, no raw camera recording, no annotated samples, no formal
  manifest, and no LAN/active stream artifact.
- Input P95: no Host/build identity for a measured run, no external-camera or
  synchronized-clock timebase proof, no direct latency samples, no formal
  manifest, no physical input actuation record, and no visible Mac-side result
  record.

## Artifacts

- `device-info.json`: ADB identity for Nubia P0110/pacific with the raw serial
  replaced by `nubia-p0110-pacific-device-1`.
- `preflight-input.json`: declared readiness checks for the three README latency
  profiles.
- `latency-preflight.json`: machine-readable blocked preflight report generated
  by `make evidence-latency-preflight`.
- `latency-preflight-exit.txt`: captured target exit status, `2`.
- `live-usb-observation-summary.json`: read-only follow-up observation from the
  already-running USB window. It records Host listener, ADB reverse, foreground
  Android app, and diagnostic decode context, but keeps every README latency
  gate closed.
- `usb-live-smoke-wide.json` and `usb-live-smoke-wide.exit`: read-only USB
  smoke helper attempt with a wider log window. It exited `1` with verdict
  `insufficient`; its machine-readable serial fields are redacted to the
  evidence device id.
- `host-process.txt`, `host-listener.txt`, `host-app-sha256.txt`,
  `host-app-codesign.txt`, `adb-reverse.txt`, and `android-pid.txt`:
  read-only Host and Android process/transport observations.
- `android-diag-wide.txt` and `android-logcat-current-pid-decoder.txt`: context
  logs showing Protocol v1 upgrade / HEVC decoder activity from the live app.
  These are diagnostic only and are not latency evidence.
- `commands.txt`: commands run during this preflight and their outcomes.

## Boundary

This record is a preflight/blocker record only. It proves the Android target was
reachable, records a limited live USB transport observation, and records exactly
why the latency gates remain open; it does not measure USB glass-to-glass, LAN
glass-to-glass, or input latency.
