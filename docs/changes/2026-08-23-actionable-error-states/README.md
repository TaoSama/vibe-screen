# Phase 1 actionable error state owner

Date: 2026-08-23
Base: origin/main at 5480ce6581c48689ca68eddd9dac7af4d25e116f
Scope: offline owner matrix and drift-prevention gate only. This change does
not close the README Phase 1 actionable-errors acceptance item.

## Scope

The Phase 1 roadmap asks for actionable errors across supported system states,
but the prior coverage was split across Android connection guidance, macOS Host
permission/runbook copy, troubleshooting notes, and feature-specific evidence.
This folder owns the cross-surface matrix that ties each state to its failed
layer, user-visible surface, recovery action, retry behavior, and current
evidence boundary.

The source of truth is actionable-error-states.json. Keep it updated whenever
Android SessionFailureKind cases, Host permission/startup/capture states, or
user-visible recovery actions change.

## PR overlap audit

The matrix explicitly records that open PRs #242, #243, and #272 were reviewed:

- #242 and #243 cover disconnected Android settings affordance behavior.
- #272 covers display-selection pending, confirmation, rollback, and one
  rejected-selection user-visible path.

Those PRs are adjacent UI slices, not an owner for the full supported-state
error matrix. This change avoids their runtime surfaces and does not duplicate
their evidence bundles.

## Offline gate

Run the owner gate without a device or Mac Host:

    make actionable-error-states-gate

The gate validates all of the following:

- the matrix is explicitly marked as non-closing for the README Phase 1 gate;
- PRs #242, #243, and #272 remain recorded as reviewed adjacent work;
- at least eight Android and eight macOS Host states are owned;
- every state has a failed layer, UI surface, user action, retry behavior,
  offline evidence, device evidence status, and gate status;
- every Android SessionFailureKind currently declared in source is covered by
  at least one matrix row;
- every local offline-evidence path referenced by the matrix exists in the
  repository;
- no state claims user-visible copy as a bare localizedDescription.

The generated report is .build/evidence/actionable-error-states-gate.json.
A pass means the owner matrix and offline contracts are complete for the current
source tree. It does not prove Android UI rendering, TalkBack/VoiceOver output,
real Host alert presentation, ADB behavior, Screen Recording/Accessibility
recovery, decoder behavior, LAN, Internet, or any README acceptance gate.

## Device evidence boundary

Future device runs may use Nubia P0110 / pacific / Android 16 / SDK 36 as a
general Android substitute only when the run records that exact identity. It
must not be relabeled as Xiaomi 13/fuxi evidence. Any device-specific gap in
the matrix remains blocked or open until its dedicated retained evidence is
present.
