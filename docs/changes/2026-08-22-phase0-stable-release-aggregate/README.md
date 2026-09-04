# Phase 0 stable-release aggregate owner

Date: 2026-08-29
Last refreshed: 2026-09-04 UTC / 2026-09-04 local
Base: origin/main at e4d7861b8af3ffa8d32fff99b022e92193acc071
Status: open. Phase 0 remains in progress rather than a stable release. This
document does not close Phase 0 and does not change product status. Do not
treat roadmap items below as shipped features.
Open PR input: `gh pr list --repo TaoSama/vibe-screen --state open --limit 200
--json number,title,headRefName,headRefOid,baseRefName,updatedAt,isDraft,mergeStateStatus,url`
returned no open PRs after PR #559, PR #560, PR #561, PR #562, PR #563, and
PR #564 merged. PR #535, PR #536, PR #545, PR #546, PR #547, PR #548,
PR #551, PR #552, PR #553, PR #554, PR #555, PR #556, PR #557, PR #558,
PR #559, PR #560, PR #561, PR #562, PR #563, and PR #564 are now included in
the audited mainline base. PR #555 and PR #562 P0110 no-Host Android UI
evidence is recorded as readiness only and is not bidirectional Host-backed
product-transfer evidence.
PR #557 Android stream telemetry counters, PR #558 native pointer hover-boundary
hardening, PR #560/#561/#563 transfer-control progress and visibility, PR #562
no-Host transfer UI smoke, and PR #564 Internet outgoing cancel semantics are
recorded as source/unit/offline readiness only. There are no external active
aggregate owner PRs at this refresh.

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

| Gate | Current manifest status | Active owner PRs | Why it cannot close today |
| --- | --- | --- | --- |
| Upstream provenance and license pin | pass | none | Closed by the Phase 0 provenance record. |
| Protocol v1 contract and CI gates | pass | none | Current main at `e4d7861b8af3ffa8d32fff99b022e92193acc071` passed the Phase 0 checks workflow run `33879459753`. |
| Android tests and debug APK clean build | pass | none | Current main at `e4d7861b8af3ffa8d32fff99b022e92193acc071` passed the Android job in Phase 0 checks workflow run `33879459753`; PR #563 and PR #564 report focused Android verification in their PR records but are not treated as Host-backed product evidence. |
| macOS release build and full-Xcode unit tests | pass | none | Current main at `e4d7861b8af3ffa8d32fff99b022e92193acc071` passed the macOS job in Phase 0 checks workflow run `33879459753`. Local 2026-08-28 full-Xcode readiness remains blocked because that machine had Command Line Tools selected, so it is not a replacement XCTest pass. |
| macOS Host hardware compatibility matrix | open | none | Published current-base `macos-hardware-compatibility-gate` summaries exist for Mac16,8 readiness, but they are `blocked`. PR #546 strengthened the preflight so Host readiness now fails closed without read-only Screen Recording, Accessibility, and Microphone TCC rows bound by `csreq` to the stable signing requirement, bundle id, install path, and source provenance. A real packaged Host launch, Protocol v1 stream, input, reconnect evidence, Intel Macs, additional Apple silicon models, macOS builds, and display topologies still need exact-row passing evidence. |
| Android USB stream, reconnect, stale epoch, and codec fallback | pass | none | Closed by retained historical real-device baseline evidence; current-base insufficient attempts remain boundary records and do not claim a fresh USB pass. PR #548's no-Host retry-card smoke, PR #551/#552/#553/#563 transfer UI/progress changes, PR #557 stream telemetry counters, and PR #564 Internet cancel semantics are Android UI/source/offline readiness only and are not counted as stream/reconnect evidence. |
| Telemetry and external latency artifact archive | insufficient | none | PR #557 adds Android stream telemetry counters for dropped frames, decoder latency, session epoch, wire mode, and heartbeat source with focused JVM coverage, but those counters are diagnostic/source readiness only. PR #545 tightened the latency evidence gate, and raw telemetry plus the latest current-base latency preflight remain insufficient; no external-camera latency sample package, raw camera media, or synchronized-clock physical-input proof is archived for this aggregate. Former tooling PR references are merged or stale baselines, not active open owners. |
| Host RSS two-hour no-growth | blocked | none | The retained two-hour Xiaomi 13 run grew about 18.3 MB. The latest 2026-08-31 current-base readiness record proves fail-closed diagnostics only and is still blocked before a stable-signed, read-only TCC-proven, listener-observed current-source Host can produce native telemetry and a current-source two-hour `host_rss_gate` pass. Former Host RSS/readiness PR references are merged or closed baseline records, not active open owners. |
| Native pointer HID mouse move/click acceptance | blocked | none | PR #558 adds Android native pointer hover enter/exit mapping and fail-closed unsupported-button filtering with focused JVM coverage, but physical HID acceptance remains blocked because no physical Android mouse/touchpad/trackball pass retains Android forwarding logs, Host pointer-injection logs, and visible Mac evidence from one run. Former native-pointer owner PR references are no longer active open owners. |
| Controller runtime acceptance | blocked | none | Latest current-base readiness remains blocked: no physical controller, identity-signed Host with approved virtual HID entitlement, Mac-side response, and neutral disconnect release are recorded in one pass bundle. Former controller owner PR references are no longer active open owners. |
| Android/macOS clipboard product E2E | blocked | none | PR #547 adds Android-side explicit overwrite confirmation coverage before writing solicited or direct Mac clipboard content into `ClipboardManager`, and local P0110 smoke plus offline/protocol checks pass. Host readiness is still blocked, and no retained bidirectional Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence exists with exact endpoints, explicit user action, Protocol v1 session ownership, verified session epoch/origin, 16-byte change IDs, SHA-256 equality, bounded byte length, and distinct final markers. |
| Android/macOS file-transfer product E2E | blocked | none | PR #547 adds Android-side incoming transfer progress and user-cancel approval coverage for USB/LAN and Internet session paths; PR #551/#552/#553 add no-Host readiness, outgoing progress, and race-hardening coverage; PR #555 and PR #562 record P0110 no-Host transfer UI smoke only; PR #563 keeps active outgoing transfer controls visible while sending; PR #564 treats Internet outgoing cancellation as locally successful after local owner cleanup while still failing the session if the reliable cancel frame is rejected. Android control-bar instrumentation, focused JVM tests, protocol fixtures, no-Host UI evidence, and Internet cancel semantic tests pass, but Host readiness is blocked and no retained bidirectional product transfer evidence proves file offer/request/content packets, receiver approval, remote write, SHA-256 equality, session epoch, and cancel cleanup in one product run. |
| Phase 0 module ownership extraction | pass | none | The current-base module ownership manifest now closes the required Android TCP transport, `StreamClient`, protocol/session, file-transfer, WakeHost, decoder, renderer, input-envelope routing, media-frame routing, Android stream telemetry, and UI/product-session boundaries with focused source and offline contract evidence. WakeHost real sleeping-Mac, router/NIC WOL, Host signing/TCC, and retained product evidence remain separate fail-closed runtime gates. |

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
The checker also fails closed if any active `owner_prs` entry in the manifest is
absent from the recorded `open_pr_snapshot`, so closed or merged PRs cannot keep
appearing as current owners.

Evaluate the module ownership sub-gate directly with:

```bash
make phase0-module-ownership-gate
```

The command writes
.build/evidence/phase0-module-ownership/phase0-module-ownership-summary.json.
On this current base it exits zero and reports
`can_close_phase0_module_ownership_extraction=true` because every required
source boundary in the module manifest is closed with focused offline evidence.
This does not close separate real-device/runtime gates such as Host RSS, native
pointer HID, controller runtime, clipboard/file-transfer product E2E, WakeHost
hardware WOL, Host signing/TCC, or retained product evidence.

Run the release-claim gate before changing README to any completed/stable Phase
0 wording:

```bash
make phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1
```

That command exits nonzero until every required manifest gate has verdict pass
with closing-strength evidence. Readiness, historical, offline, synthetic,
blocked, insufficient, or open evidence cannot close the aggregate.

Aggregate owner refreshes may additionally bind the manifest to the audited base
commit so stale manifests fail closed instead of being mistaken for a current
source decision:

```bash
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=$(git rev-parse origin/main) \
  PHASE0_STABLE_RELEASE_REQUIRE_PASS=1
```

The 2026-09-04 UTC manifest refresh binds the aggregate source guard to
`e4d7861b8af3ffa8d32fff99b022e92193acc071`, records the current open-PR
snapshot as empty, keeps all required gate `owner_prs` lists empty, consumes
the successful current-main Phase 0 checks run `33879459753`, records PR #557, PR #558, PR
#560, PR #561, PR #562, PR #563, and PR #564 as source/unit/offline readiness,
and keeps the Android/macOS clipboard and file-transfer product E2E gates as
required Phase 0 gates that are blocked. The last retained summary bundle remains under
`evidence/2026-08-28-current-main-gate-blocked/`; local verification for this
refresh writes the current summary under `.build/evidence/phase0-stable-release/`.

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
   acceptance criteria, relevant evidence tooling, or the active open owner PR
   set.
