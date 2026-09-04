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
The seven README-facing contract rows are the offline error-model source for
their code/title/body/action semantics; Android connection UI wiring can consume
that model after the active connection-UI work lands, without using this gate as
device or permission recovery evidence.
The current required current-base owner gate also tracks the feature-specific
Android Internet, codec, managed-policy, unsupported-peripheral, file-transfer,
and clipboard error states. Older owner manifests stay valid as blocked records:
missing newly required states are synthesized as blocked so history does not
become malformed, but those gaps still cannot close the README Phase 1 gate.

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

A current-base open-PR audit on 2026-08-24 also found adjacent active work that
does not close this matrix: #186 owns P0110 USB smoke readiness, #286 owns a
trusted-LAN route blocker, #288 owns shared macOS Host readiness preflight,
#302 owns macOS startup recovery, and #315 owns reconnect-timing scenarios. This
owner gate consumes those boundaries as adjacent context only; each row still
needs its own retained state evidence before the README actionable-errors gate
can close.

## Offline gate

Run the owner gate without a device or Mac Host:

    make actionable-error-states-gate

The gate validates all of the following:

- the matrix is explicitly marked as non-closing for the README Phase 1 gate;
- PRs #242, #243, and #272 remain recorded as reviewed adjacent work;
- at least eight Android and eight macOS Host states are owned;
- every state has a failed layer, UI surface, user action, retry behavior,
  offline evidence, device evidence status, and gate status;
- the seven README-facing contracts have stable code, title, body, and action
  fields and are marked gate_status=covered-offline: Screen Recording denied,
  Accessibility denied/limited, ADB reverse missing, USB disconnected, LAN route
  unavailable, TCP 54321 unavailable, and stale epoch/session errors;
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

## Current-base device owner gate

Use `actionable-error-current-base-gate` for acceptance. It exits non-zero unless
the report is a real pass. Use `actionable-error-current-base-owner-record` when
a run records real device or environment artifacts for the README-facing
actionable-error states, including blocked records that intentionally cannot
close the README gate:

    make actionable-error-current-base-owner-record \
      EVIDENCE_DIR=docs/changes/2026-08-23-actionable-error-states/evidence/2026-09-05-p0110-no-host-owner

The input manifest is `actionable-error-current-base.json`; the generated
report is `actionable-error-current-base-gate.json`. The gate is read-only and
validates all of the following:

- the retained device identity is exactly Nubia P0110 / pacific / Android 16 /
  SDK 36 with the public ADB serial redacted as `<redacted-adb-serial>`;
- every required current-base state is represented: Screen Recording denied,
  Accessibility denied/limited, TCP `54321` unavailable, ADB reverse missing,
  USB disconnected, LAN route unavailable, stale epoch/session errors, and the
  feature-specific Android Internet, codec, managed-policy, peripheral,
  file-transfer, and clipboard error states;
- every referenced local artifact exists inside the repository and matches its
  recorded SHA-256;
- a blocked, insufficient, or not-run state cannot set `can_close_state=true`;
- the README actionable-errors gate can close only when every required state is
  `pass` and the manifest explicitly opts into closure.

The 2026-08-24 P0110 record is intentionally `blocked`: it contains safe
read-only evidence for the exact device, the existing ADB reverse mapping, a
missing local TCP `54321` listener, Android bounded retry logs, and a sanitized
LAN route blocker. It does not include TCC denial, missing-reverse mutation,
physical USB-disconnect capture, or stale epoch/session acceptance. Do not use
that report to close the README Phase 1 actionable-errors item.

The 2026-08-27 P0110 record is also intentionally `blocked`: it is bound to
current `origin/main`, installs a current-source Android debug APK, confirms the
public evidence redacts the ADB serial, and safely exercises ADB reverse removal
with restoration afterwards. That run exposed a UI gap: after removing
`tcp:54321`, the app remained on the visible USB waiting/checklist surface rather
than showing the ADB-route-unavailable recovery copy, so the state is retained as
`insufficient` and the README gate remains open. The same run records that a
local TCP `54321` listener was present, so TCP-unavailable was not safely
reproduced on 2026-08-27.

The 2026-08-30 P0110 record is also intentionally `blocked`. It refreshes the
current-base owner on `origin/main` after #429, records the exact P0110 device
identity, safely removes and restores ADB reverse `tcp:54321`, and retains an
Android UI dump plus bounded retry logs. In this run removing the reverse rule
produced `ECONNREFUSED` and the app showed the `Mac app unavailable` guidance
with concrete ADB reverse recovery copy. That proves a user-visible actionable
missing-route state, but it is not yet a distinct ADB-route-unavailable copy or
closure for the README gate; the same run records that a local TCP `54321`
listener was present, so TCP-unavailable was not safely reproduced on
2026-08-30. Screen Recording/Accessibility denial, USB-disconnect capture, and
stale epoch/session rejection remain blocked/not-run. Because this manifest
predates the feature-specific Android UI rows, the current gate reports those
later rows as blocked when it is evaluated for owner-record compatibility.

The 2026-09-05 P0110 no-Host record is also intentionally `blocked`. It refreshes
the owner surface for the disconnected USB/no-Host path, records exact P0110
identity, shows no configured `tcp:54321` reverse route, and retains a screenshot
where Android presents `USB route unavailable`, `TCP 54321`, `restart Vibe Screen
on the Mac`, and `Mac server · Not ready` copy. That proves actionable copy for
the no-Host disconnected USB surface, but it does not prove Host-side USB repair,
successful Android/macOS product E2E recovery, macOS TCC denial behavior,
physical USB-disconnect capture, LAN retry, stale epoch/session rejection, or
the feature-specific Android error rows.

## Device evidence boundary

Future device runs may use Nubia P0110 / pacific / Android 16 / SDK 36 as a
general Android substitute only when the run records that exact identity. It
must not be relabeled as Xiaomi 13/fuxi evidence. Any device-specific gap in
the matrix remains blocked or open until its dedicated retained evidence is
present.
