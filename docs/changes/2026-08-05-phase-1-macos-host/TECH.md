# Phase 1 macOS host technical design

## Display identity and lifecycle

Persist an existing display's CoreGraphics UUID, not its session-local
`CGDirectDisplayID`. Resolve the UUID against online displays for each start;
when it is absent, capture the current main display without overwriting the
saved selection.

Virtual display product identity includes logical and physical dimensions,
refresh rate, and density mode. Adoption checks the current mode's physical
pixel dimensions because `CGDisplayPixelsWide/High` report logical dimensions
on scaled displays. Extended-layout positions are keyed by that configuration;
mirror sessions neither read nor overwrite them. Mirror teardown explicitly
attempts to remove the per-session mirror configuration before releasing the
display and reports a system configuration failure.

Private class lookup is a diagnostic gate only. The authoritative success path
remains descriptor creation, settings application, online registration, and
capture setup. Failure directs the user to Current Mac Display or a
physical/dummy display.

## Window recovery

The first migration records the AX window, original frame, display UUID, and
display bounds. Recovery resolves that UUID and maps the relative placement
into its current bounds. If it is offline, the same placement is mapped and
clamped into the current main display. All windows are removed from the managed
set after one recovery pass; individual AX failures are reported without
preventing the rest.

## Input boundary

The Android legacy client supplies source-frame-normalized coordinates after
removing letterboxing. The host therefore applies no second rotation. It
rejects non-finite/out-of-range coordinates and unknown actions, maps valid
coordinates through `CGDisplayBounds` (including negative origins), and drops
main-queue callbacks from an obsolete connection generation.

Stopping, disconnecting, disabling input, or losing Accessibility cancels
timers and momentum, clears the gesture state, and releases an active drag when
permission still allows it. The current wire session has no keyboard or native
mouse event type, so those are not claimed as integrated capabilities.

## Startup and headless recovery

Automatic start requires the preference, Screen Recording permission, and
completed onboarding; explicit benchmark mode is the only onboarding bypass.
Concurrent start requests are coalesced by an in-progress guard. Recovery is
eligible only for unattended operation, uses the existing bounded backoff, and
rechecks all eligibility after sleeping. A user stop or disabling auto-start
cancels pending recovery.

Wireless status refresh does not schedule ADB device or reverse-rule probes,
and stale USB probe results cannot update Wireless state. Launch at Login
exposes `requiresApproval` and directs the user to Login Items. The
main-app login item does not provide crash KeepAlive or pre-login execution.
