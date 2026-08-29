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

Current-base reconnect matrix owner evidence is under
[`evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked`](evidence/2026-08-28-p0110-usb-reconnect-current-base-blocked/README.md).
It records the latest `origin/main`-based worktree state at
current source commit `1f572c3aa0fcbc558683feb94b33525e6a688a23`, based on
`origin/main` commit `9e6621b7194bf5aa051a07944afb6e2b1ccf2232`. The P0110 target identity was
confirmed as nubia P0110 / pacific / Android 16 / SDK 36, ADB reverse still
showed `tcp:54321 tcp:54321`, and `dev.telemachus.display` was running on
Android, but the real USB timing attempts were blocked before disruption
because the source-bound stable Host prerequisites were not satisfied: the
configured `Vibe Screen Dev` signing identity was unavailable for rebuild,
codesign inspection of `/Applications/Vibe Screen.app` failed, no Host listener
was observed on TCP `54321`, and TCC permissions were not inspected after Host
bundle signing inspection failed. The generated summary reports `verdict=blocked`,
`can_close_timing_gate=false`, and all three full-gate disruptions missing. No
client kill, ADB reverse removal/restoration, or trusted-LAN interruption was
run.

Earlier current-base blocked matrix evidence remains under
[`evidence/2026-08-24-p0110-current-base-reconnect-blocked`](evidence/2026-08-24-p0110-current-base-reconnect-blocked/README.md).

Current worktree evidence is under
[`evidence/2026-08-21-p0110-reconnect-timing-blocked`](evidence/2026-08-21-p0110-reconnect-timing-blocked/README.md).

The intended Android target is Nubia P0110 / pacific / Android 16 /
`<device-serial>`. No ADB disruption command was run for this blocked record.
The real timing run was blocked before session setup because:

- `scripts/macos_dev_host.py preflight` reported the `Vibe Screen Dev` signing
  identity is unavailable in the current keychain.
- No Host listener was present on TCP `54321` in this worktree.

The generated `reconnect-timing-summary.json` reports `verdict=blocked` and
`can_close_timing_gate=false`.

Future current-base reconnect attempts must first retain the shared Host
readiness snapshot with:

```bash
make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>
```

The run may proceed only for scenarios whose prerequisites are ready. For the
trusted-LAN interruption scenario, `host-readiness.json` must report
`can_start_trusted_lan_gate=true`; for USB reconnect scenarios it must at least
show the source-bound stable-signed Host, TCC, and listener prerequisites ready.
A blocked Host readiness snapshot is retained as prerequisite evidence and does
not close the reconnect timing gate.

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
