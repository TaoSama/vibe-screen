# Phase 0 stable-release aggregate owner

Date: 2026-08-29
Last refreshed: 2026-09-02
Base: origin/main at b81bd4ab93f3d2816c76d6395f061aa42b15d272
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
| Protocol v1 contract and CI gates | pass | none | PR #381 retained a successful Phase 0 checks run for the merge source; the later main push run at `1430c3cc18948b93b50b7054e992844f287b6fbc` was cancelled and is not counted as closing evidence. |
| Android tests and debug APK clean build | pass | none | PR #381 retained a successful Phase 0 checks run with Android passing for the merge source; the later main push run at `1430c3cc18948b93b50b7054e992844f287b6fbc` was cancelled and is not counted as closing evidence. |
| macOS release build and full-Xcode unit tests | pass | none | PR #381 retained a successful Phase 0 checks run with macOS passing for the merge source. Local 2026-08-28 full-Xcode readiness is blocked because this machine has Command Line Tools selected, so it is not a replacement XCTest pass. |
| macOS Host hardware compatibility matrix | open | none | Published current-base `macos-hardware-compatibility-gate` summaries exist for Mac16,8 readiness, but they are `blocked` by missing stable signing/TCC proof, source-bound Host provenance, full macOS checks, packaged runtime launch, Protocol v1 stream, input, and reconnect evidence. Intel Macs, additional Apple silicon models, macOS builds, and display topologies still need exact-row passing evidence. |
| Android USB stream, reconnect, stale epoch, and codec fallback | pass | none | Closed by retained historical real-device baseline evidence; current-base insufficient attempts remain boundary records and do not claim a fresh USB pass. |
| Telemetry and external latency artifact archive | insufficient | #167, #192 | Raw telemetry and the latest current-base latency preflight remain insufficient; no external-camera latency sample package or synchronized-clock physical-input proof is archived for this aggregate. |
| Host RSS two-hour no-growth | blocked | #158, #195, #222, #230, #237, #260, #329, #376, #387 | The retained two-hour Xiaomi 13 run grew about 18.3 MB. The latest 2026-08-31 current-base readiness record proves fail-closed diagnostics only and is still blocked before a stable-signed, TCC-ready, listener-observed current-source Host can produce native telemetry and a current-source two-hour `host_rss_gate` pass. |
| Native pointer HID mouse move/click acceptance | blocked | #232, #268, #361 | Latest current-base summaries remain blocked because no physical Android mouse/touchpad/trackball pass retains Android forwarding logs, Host pointer-injection logs, and visible Mac evidence from one run. |
| Controller runtime acceptance | blocked | #217, #220, #270 | Latest current-base readiness remains blocked: no physical controller, identity-signed Host with approved virtual HID entitlement, Mac-side response, and neutral disconnect release are recorded in one pass bundle. |
| Android/macOS clipboard product E2E | blocked | none | Local P0110 `ClipboardManager` smoke and offline/protocol checks pass, but Host readiness is blocked and no retained bidirectional Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence exists with exact endpoints, explicit user action, Protocol v1 session ownership, verified session epoch/origin, 16-byte change IDs, SHA-256 equality, bounded byte length, and distinct final markers. |
| Android/macOS file-transfer product E2E | blocked | none | Android control-bar instrumentation, focused JVM tests, and protocol fixtures pass, but Host readiness is blocked and no retained bidirectional product transfer evidence proves file offer/request/content packets, receiver approval, remote write, SHA-256 equality, session epoch, and cancel cleanup. |
| Phase 0 module ownership extraction | open | #218, #259, #372; #211 and #221 superseded by #259 | The current-base module ownership manifest closes Android TCP transport, several `StreamClient` owner slices, protocol/session ownership, file-transfer/WakeHost product ownership, and renderer ownership. Decoder and UI/product session boundaries remain partial. WakeHost real sleeping-Mac, router/NIC WOL, Host signing/TCC, and retained product evidence remain separate fail-closed gates. |

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

Evaluate the module ownership sub-gate directly with:

```bash
make phase0-module-ownership-gate
```

The command writes
.build/evidence/phase0-module-ownership/phase0-module-ownership-summary.json.
It exits zero while the manifest is well formed, even when the summary verdict
is blocked. Use `PHASE0_MODULE_OWNERSHIP_REQUIRE_PASS=1` only before attempting
to close the module ownership sub-gate; current main must fail that stricter
mode until every required boundary is closed with focused evidence.

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

The 2026-08-30 manifest refresh binds the aggregate source guard to
`4884d80813a7f674a10d574a96f8dfcf5723c6e7` and keeps the Android/macOS
clipboard product E2E gate as a required Phase 0 gate that is blocked. The last retained
summary bundle remains under `evidence/2026-08-28-current-main-gate-blocked/` and
should be regenerated after this manifest change is merged.

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
