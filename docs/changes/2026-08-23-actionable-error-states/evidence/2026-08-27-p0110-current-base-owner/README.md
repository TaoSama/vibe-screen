# P0110 current-base actionable-error owner record

Date: 2026-08-27
Device: Nubia P0110 / pacific / Android 16 / SDK 36 / `<redacted-adb-serial>`
Repository: `TaoSama/vibe-screen`

This is a current-base owner record for the README Phase 1 actionable-error
states. It is intentionally not an acceptance pass.

## What was retained

- current repository snapshot after `origin/main` fetch and branch creation;
- exact P0110 device identity with the public ADB serial redacted;
- current-source Android debug build and install precondition;
- USB disconnected initial waiting-panel UI dump;
- controlled ADB reverse removal and restoration around a current-source device
  observation;
- post-fix ADB-reverse-missing UI dump showing the app remains on the visible USB
  waiting/checklist surface rather than a blank video-only surface;
- current Host listener precondition showing TCP `54321` was already occupied;
- sanitized LAN route summary that omits SSIDs and local network addresses.

Screenshots were used locally for visual inspection only and are not part of the
public checksum set. Raw dumpsys, route, and logcat outputs that may contain
network identifiers or account telemetry are not committed.

## Gate result

Run from the repository root:

```bash
make actionable-error-current-base-owner-record   EVIDENCE_DIR=docs/changes/2026-08-23-actionable-error-states/evidence/2026-08-27-p0110-current-base-owner
```

The generated `actionable-error-current-base-gate.json` reports:

- `verdict=blocked`
- `can_close_readme_phase1_actionable_errors_gate=false`
- blocked: Screen Recording denied, Accessibility denied/limited, TCP `54321`
  unavailable, LAN route unavailable
- insufficient/not-run: ADB reverse missing, USB disconnected, stale
  epoch/session errors

## Not proven

This record does not prove macOS TCC denial behavior, complete missing-ADB-route
recovery copy, physical USB disconnect UI, encrypted-LAN retry behavior, or stale
epoch/session rejection. Those states require dedicated retained evidence before
the README Phase 1 actionable-errors gate can close.
