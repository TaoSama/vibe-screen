# Gesture-to-action mapping blocked evidence

Date: 2026-08-21
Worktree: `.claude/worktrees/gesture-action-mapping`
Scope: Phase 5 gesture-to-action mapping boundary

## What was verified offline

This source slice verifies the fail-closed protocol and local-client boundary:

- MacHost advertises a finite `HostActionCatalog` only when host actions are
  negotiated and allowed by local managed policy.
- MacHost rejects unnegotiated, policy-denied, unknown, pre-stream,
  wrong-target, missing-invocation-id, and over-cap pending host-action
  invocations.
- Android filters host-action menu entries to the stable `move-window` and
  `return-windows` action IDs and keeps gesture mappings local.
- Android Protocol v1 clears stale previously available actions when a later
  catalog has no supported IDs and ignores unsolicited/replayed action results.
- iOS filters catalog IDs through the same finite action list and denies local
  gesture mappings unless both custom gestures and host actions are allowed.

## Blocked real-device evidence

No real gesture-to-action acceptance run was performed for this change. The
following gates remain open and must not be marked complete from this evidence:

- signed iPhone/iPad installation and gesture invocation against a live Host;
- fresh Android real-device gesture-to-action run;
- macOS TCC-confirmed action execution from physical gestures;
- physical accessory gesture/input confirmation;
- Internet transport behavior.

If an Android substitute is used later, evidence must identify it as
`nubia P0110 / pacific / Android 16 / SDK 36` when using serial
`EP0110PZ0B9110300B`. It must not be relabeled as Xiaomi/fuxi evidence.

## Required follow-up evidence

A closing package should include raw Host logs, client logs, negotiated
capability/catalog envelopes, the exact action invocation/result pair, device
identity, OS/build versions, signing/TCC state, and a short video or equivalent
external observation that the intended Host action occurred.
