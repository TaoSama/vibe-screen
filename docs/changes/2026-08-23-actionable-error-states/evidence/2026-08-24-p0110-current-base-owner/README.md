# P0110 current-base actionable-error owner record

Date: 2026-08-24
Device: Nubia P0110 / pacific / Android 16 / SDK 36 / `<redacted-adb-serial>`
Repository: `TaoSama/vibe-screen`

This is a current-base owner record for the README Phase 1 actionable-error
states. It is intentionally a blocked record, not an acceptance pass.

## What was retained

- exact P0110 device identity;
- repository snapshot at device collection time and after fast-forwarding to the
  current base;
- ADB reverse state before and after the USB observation, showing
  `tcp:54321` remained present;
- macOS listener checks before and after the USB observation, showing no local
  TCP `54321` listener;
- Android USB waiting surface XML before connection;
- app-tag-filtered logcat and private diagnostic logs showing retryable
  `TRANSPORT_CLOSED` and bounded `reconnect_scheduled` events;
- sanitized LAN blocker showing Wi-Fi disconnected, `wlan0` down, and no route.

The raw LAN dumpsys excerpt is not committed because it included saved SSID
names. Screenshots and UI dumps from an accidental Internet/settings navigation
are also excluded from the committed checksum set and are not evidence for this
gate.

## Gate result

Run from the repository root:

```bash
make actionable-error-current-base-owner-record \
  EVIDENCE_DIR=docs/changes/2026-08-23-actionable-error-states/evidence/2026-08-24-p0110-current-base-owner
```

The generated `actionable-error-current-base-gate.json` reports:

- `verdict=blocked`
- `can_close_readme_phase1_actionable_errors_gate=false`
- blocked: Screen Recording denied, Accessibility denied/limited, TCP `54321`
  unavailable, ADB reverse missing, LAN route unavailable
- insufficient/not-run: USB disconnected, stale epoch/session errors

## Not proven

This record does not prove macOS TCC denial behavior, a missing ADB reverse
mutation/recovery, physical USB disconnect UI, encrypted-LAN retry behavior, or
stale epoch/session rejection. Those states require dedicated retained evidence
before the README Phase 1 actionable-errors gate can close.
