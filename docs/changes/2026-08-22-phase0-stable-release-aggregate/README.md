# Phase 0 stable-release aggregate owner

Date: 2026-08-22
Base: origin/main at 4dc84505e6e0a07fa1052df12bca03824f161bf6
Status: open. This document does not close Phase 0 and does not change product
status.

## Purpose

Phase 0 closure is no longer decided by individual README sentences or by a
single sub-gate PR. The aggregate owner for the stable-release decision is the
machine-readable manifest in phase0-stable-release-manifest.json, evaluated by
vibescreen_evidence.phase0_stable_release.

README may describe Phase 0 as shipped, complete, closed, or a stable release
only after the aggregate checker reports aggregate_verdict=pass and
can_mark_phase0_stable_release=true.

Until then, README must keep the in-progress guard language at the top of the
file and in the Phase 0 section.

## Required aggregate gates

The aggregate manifest currently requires these Phase 0 gates to pass before a
stable-release claim is allowed:

| Gate | Current manifest status | Owner PRs | Why it cannot close today |
| --- | --- | --- | --- |
| Upstream provenance and license pin | pass | none | Closed by the Phase 0 provenance record. |
| Protocol v1 contract and CI gates | pass | none | Closed by current CI and Phase 0 test records. |
| Android tests and debug APK clean build | pass | none | Closed by current CI and Phase 0 test records. |
| macOS release build and full-Xcode unit tests | pass | none | Closed by current CI and Phase 0 test records. |
| Android USB stream, reconnect, stale epoch, and codec fallback | pass | none | Closed by retained real-device evidence. |
| Telemetry and external latency artifact archive | insufficient | #167, #192 | Raw telemetry exists, but no external-camera latency sample package or synchronized-clock physical-input proof is archived for this aggregate. |
| Host RSS two-hour no-growth | blocked | #158, #222, #230, #237 | The retained two-hour Xiaomi 13 run grew about 18.3 MB; no current-source host_rss_gate pass exists. |
| Native pointer HID mouse move/click acceptance | blocked | #232, #268 | No physical Android mouse/touchpad/trackball pass has retained Android, Host, and visible Mac evidence from one run. |
| Controller runtime acceptance | blocked | #217, #220, #270 | No physical controller plus entitled Host plus Mac-side response plus neutral disconnect release pass exists. |
| Phase 0 module ownership extraction | open | #211, #218, #221, #259 | Android TCP transport is extracted, but the remaining protocol/session/media/input/UI boundaries are not all enforced on current main. |

Trusted LAN current-worktree stream/reconnect, login-item/headless reboot, and
Developer ID notarized distribution remain important release-readiness items,
but this aggregate keeps them outside the Phase 0 source-baseline closure
decision unless the Phase 0 PRD is explicitly changed.

## Evaluation

Run the guard without claiming closure:

```bash
make phase0-stable-release-gate
```

The command writes
.build/evidence/phase0-stable-release/phase0-stable-release-summary.json and
exits zero when README guard language is consistent with the manifest, even if
the aggregate is still blocked.

Run the release-claim gate before changing README to any completed/stable Phase
0 wording:

```bash
make phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1
```

That command exits nonzero until every required manifest gate has verdict pass
with closing-strength evidence. Readiness, historical, offline, synthetic,
blocked, insufficient, or open evidence cannot close the aggregate.

## Update rules

1. Update a sub-gate's source evidence first, then update the manifest.
2. Keep blocked/open sub-gates listed with their real blocker; do not remove
   them to make the aggregate pass.
3. Treat P0110 evidence as P0110/pacific evidence. It may close general Android
   gates only when the exact criteria are satisfied, and it must not be
   relabeled as Xiaomi/fuxi, iOS, HarmonyOS, tablet, or missing-peripheral
   evidence.
4. README Phase 0 status changes must cite this manifest summary and the
   passing sub-gate evidence paths.
5. This aggregate owner must be refreshed after any merge that changes Phase 0
   acceptance criteria, relevant evidence tooling, or the owner PR set.
