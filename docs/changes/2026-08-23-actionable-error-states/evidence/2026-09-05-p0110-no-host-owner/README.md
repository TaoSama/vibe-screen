# P0110 no-host actionable-error owner record

Date: 2026-09-05
Device: Nubia P0110 / pacific / Android 16 / SDK 36 / `<redacted-adb-serial>`
Repository: `TaoSama/vibe-screen`

This is a current-base owner record for the Android USB disconnected/no-host
actionable-error surface. It is intentionally not an acceptance pass for the
README Phase 1 actionable-errors gate.

## What Was Retained

- current repository snapshot from the feature worktree rebased onto latest
  `origin/main`;
- exact P0110 device identity with the public ADB serial redacted;
- read-only `adb reverse --list` output showing no `tcp:54321` route was
  configured before the no-host observation;
- Android screenshot of the USB disconnected state showing `USB route
  unavailable`, recovery copy that routes repair through the Mac app, `TCP
  54321`, `restart Vibe Screen on the Mac`, and `Mac server · Not ready`;
- operator note recording the no-Host/no-TCC/no-ADB-mutation collection
  boundary.

`uiautomator dump` did not produce an XML tree on this device during the run
because the framework could not obtain idle state, so the user-visible copy is
bound to the retained screenshot and operator observation rather than an XML
dump.

## Gate Result

Run from the repository root:

```bash
make actionable-error-current-base-owner-record \
  EVIDENCE_DIR=docs/changes/2026-08-23-actionable-error-states/evidence/2026-09-05-p0110-no-host-owner
```

The generated `actionable-error-current-base-gate.json` reports:

- `verdict=blocked`
- `can_close_readme_phase1_actionable_errors_gate=false`
- `adb_reverse_missing` is device-observed but still `insufficient` because
  the run does not prove Host-side USB repair or successful Android/macOS
  product E2E recovery
- Screen Recording, Accessibility, TCP `54321` unavailable, USB disconnect,
  LAN route, stale epoch/session, and the required feature-specific Android
  UI states remain blocked or not run

## Not Proven

This record does not prove macOS TCC denial behavior, physical USB-disconnect
UI after cable removal, Host listener repair, encrypted-LAN retry behavior,
stale epoch/session rejection, or any Android/macOS product E2E flow. Those
states require dedicated retained evidence before the README Phase 1
actionable-errors gate can close.
