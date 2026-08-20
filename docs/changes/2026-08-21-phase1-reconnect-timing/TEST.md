# Phase 1 reconnect timing evidence tooling

## Scope

This change adds fail-closed tooling and focused telemetry for the Phase 1
reconnect-within-three-seconds gate. It does not record a passing device run and
does not close the README timing gate.

The required full gate remains all three disruption scenarios on a real
Protocol v1 session:

- `client-kill`
- `adb-reverse-disconnect`
- `lan-network-interrupt`

Each attempt must retain a disruption start timestamp, stable Host PID, Host
Protocol v1 connection epoch, Android session/config epochs, first received
frame, and Android decoder first output frame. LAN attempts also must prove the
trusted-LAN encrypted record path and rule out legacy plaintext fallback.

## Current blocked result

Current worktree evidence is under
[`evidence/2026-08-21-p0110-reconnect-timing-blocked`](evidence/2026-08-21-p0110-reconnect-timing-blocked/README.md).

The intended Android target is Nubia P0110 / pacific / Android 16 /
`EP0110PZ0B9110300B`. No ADB disruption command was run for this blocked record.
The real timing run was blocked before session setup because:

- `scripts/macos_dev_host.py preflight` reported the `Vibe Screen Dev` signing
  identity is unavailable in the current keychain.
- No Host listener was present on TCP `54321` in this worktree.

The generated `reconnect-timing-summary.json` reports `verdict=blocked` and
`can_close_timing_gate=false`.

## Validation

Run the focused evidence-tool tests:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_reconnect_timing -v
```

Run the Android telemetry regression:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest.firstFrameTelemetryIsEmittedOncePerProtocolSession
```

Run the Host build check after touching `StreamingServer.swift`:

```bash
cd baseline/MacHost
swift build
```
