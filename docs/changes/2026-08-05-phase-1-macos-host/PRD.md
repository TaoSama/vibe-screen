# Phase 1 macOS host capabilities

Status: implemented; gated integration evidence remains
Owner: Vibe Screen core team
Started: 2026-08-05

## Goal

Complete the macOS-only portion of the local display experience without
changing the Android UI or Protocol v1 application contract, and without
claiming private macOS behavior that has not run successfully.

## In scope

- Experimental virtual extension and main-display mirroring with a supported
  current/existing-display fallback.
- Stable existing-display selection, HiDPI configuration, and bounded stream
  sizing.
- Focused-window migration and deterministic recovery after disconnect, stop,
  startup failure, display removal, or app termination.
- Validated touch-derived pointer injection and cancellation on disconnect,
  permission loss, input disable, or stop.
- Screen Recording/Accessibility guidance, Launch at Login status, startup
  de-duplication, and bounded unattended listener recovery.
- XCTest sources, pure host self-tests, release build/package evidence, and
  explicitly gated local integration steps.

## Non-goals

- Android or Protocol v1 changes.
- Keyboard/native-mouse product transport; the legacy client sends touch only.
- Claiming that private `CGVirtualDisplay` symbols imply successful display
  creation, mirroring, or capture.
- Taking over or invalidating the coordinated Android soak.
- Crash relaunch, pre-login/FileVault operation, notarization, or App Store
  compatibility.

## Acceptance boundary

The host implementation is accepted when the release build and pure self-test
pass, XCTest sources cover the policies, the app artifact verifies, and all
unrun system/device gates remain recorded as unproved. Private display,
real-window, login-item, and end-to-end behavior require separate evidence on
the exact machine/session where they are exercised.
