# Phase 0 stable-release aggregate owner

Date: 2026-08-29
Last refreshed: 2026-09-06 UTC / 2026-09-06 local
Base: origin/main at fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f
Status: open. Phase 0 remains in progress rather than a stable release. This
document does not close Phase 0 and does not change product status. Do not
treat roadmap items below as shipped features.
Open PR input: `gh pr list --repo TaoSama/vibe-screen --state open --limit 200
--json number,title,headRefName,baseRefName,isDraft,url | jq 'sort_by(.number)'`
returned `[]`. Merged PR #623 and PR #624 are now part of the audited
mainline input rather than open owner PRs. Merged PR #569 through PR #575 and
PR #577 through PR #624 were collected with `--base main`, `baseRefName`, and
`mergeCommit`; the checker verifies each recorded merge commit is an ancestor of the audited
mainline base before treating it as an audited input. PR #568 and PR #576 were
closed without merging and are not included in the audited mainline base. Merged
PR #569 through PR #575 and PR #577 through PR #624 include additional Android
no-Host UI/layout evidence,
clipboard baseline/control hardening, keyboard boundary coverage, AV1 and
managed-policy no-Host admission probes, controller hotplug neutral-release
coverage, AudioTrack no-Host smoke, file-transfer no-Host/runtime-loss/local-save
cleanup coverage, managed-policy control happy-path coverage,
transfer-readiness copy/heading/selectability, host-unreachable/route-unavailable
guidance JVM coverage, WakeHost or actionable-error gate documentation
fixes, aggregate source-guard refresh, and P0110 no-Host UI/UX review evidence.
These are recorded as source/unit/offline or no-Host readiness only. They
do not close any blocked
Host-backed real-device gate, bidirectional clipboard product E2E gate,
bidirectional file-transfer product E2E gate, physical HID pointer gate, physical
controller runtime gate, Host RSS gate, macOS Host compatibility matrix, or
external latency archive gate. There are no external active aggregate owner PRs
at this refresh.

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
| Protocol v1 contract and CI gates | pass | none | Current main at `fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f` passed the Phase 0 checks workflow run `34017313447`, including protocol, phase3, Android, evidence-tools, and macOS jobs. |
| Android tests and debug APK clean build | pass | none | Current main at `fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f` passed the Android job in Phase 0 checks workflow run `34017313447`; merged PR #569 through PR #575 and PR #577 through PR #624 add focused Android verification and no-Host/source readiness, including PR #621 host-unreachable/route-unavailable guidance JVM coverage, PR #622/#624 aggregate evidence refreshes, and PR #623 P0110 no-Host UI/UX review evidence, but are not treated as Host-backed product evidence. |
| macOS release build and full-Xcode unit tests | pass | none | Current main at `fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f` passed the macOS job in Phase 0 checks workflow run `34017313447`. Local 2026-08-28 full-Xcode readiness remains blocked because that machine had Command Line Tools selected, so it is not a replacement XCTest pass. |
| macOS Host hardware compatibility matrix | open | none | Published current-base `macos-hardware-compatibility-gate` summaries exist for Mac16,8 readiness, but they are `blocked`. PR #546 strengthened the preflight so Host readiness now fails closed without read-only Screen Recording, Accessibility, and Microphone TCC rows bound by `csreq` to the stable signing requirement, bundle id, install path, and source provenance. A real packaged Host launch, Protocol v1 stream, input, reconnect evidence, Intel Macs, additional Apple silicon models, macOS builds, and display topologies still need exact-row passing evidence. |
| Android USB stream, reconnect, stale epoch, and codec fallback | pass | none | Closed by retained historical real-device baseline evidence; current-base insufficient attempts remain boundary records and do not claim a fresh USB pass. Merged PR #569 through PR #575 and PR #577 through PR #624 add Android no-Host UI, keyboard, clipboard, audio, AV1, controller, managed-policy, file-transfer, aggregate evidence, host-unreachable guidance, and P0110 no-Host UI/UX review source/unit/offline readiness, but those records are not counted as stream/reconnect, LAN route, TCP 54321, Host-backed product, or retained device evidence. |
| Telemetry and external latency artifact archive | insufficient | none | PR #557 adds Android stream telemetry counters for dropped frames, decoder latency, session epoch, wire mode, and heartbeat source with focused JVM coverage, but those counters are diagnostic/source readiness only. PR #545 tightened the latency evidence gate, and raw telemetry plus the latest current-base latency preflight remain insufficient; no external-camera latency sample package, raw camera media, or synchronized-clock physical-input proof is archived for this aggregate. Former tooling PR references are merged or stale baselines, not active open owners. |
| Host RSS two-hour no-growth | blocked | none | The retained two-hour Xiaomi 13 run grew about 18.3 MB. The latest 2026-08-31 current-base readiness record proves fail-closed diagnostics only and is still blocked before a stable-signed, read-only TCC-proven, listener-observed current-source Host can produce native telemetry and a current-source two-hour `host_rss_gate` pass. Former Host RSS/readiness PR references are merged or closed baseline records, not active open owners. |
| Native pointer HID mouse move/click acceptance | blocked | none | PR #558 adds Android native pointer hover enter/exit mapping and fail-closed unsupported-button filtering with focused JVM coverage, but physical HID acceptance remains blocked because no physical Android mouse/touchpad/trackball pass retains Android forwarding logs, Host pointer-injection logs, and visible Mac evidence from one run. Former native-pointer owner PR references are no longer active open owners. |
| Controller runtime acceptance | blocked | none | Latest current-base readiness remains blocked: no physical controller, identity-signed Host with approved virtual HID entitlement, Mac-side response, and neutral disconnect release are recorded in one pass bundle. Former controller owner PR references are no longer active open owners. |
| Android/macOS clipboard product E2E | blocked | none | PR #547 adds Android-side explicit overwrite confirmation coverage before writing solicited or direct Mac clipboard content into `ClipboardManager`; PR #572 hardens the clipboard baseline gate; PR #605 shows pending Android clipboard status; PR #618 hardens clipboard control contracts; PR #620 covers the allowed managed-policy control happy path. Local P0110 smoke plus offline/protocol checks pass, but Host readiness is still blocked and no retained bidirectional Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence exists with exact endpoints, explicit user action, Protocol v1 session ownership, verified session epoch/origin, 16-byte change IDs, SHA-256 equality, bounded byte length, and distinct final markers. |
| Android/macOS file-transfer product E2E | blocked | none | PR #547 adds Android-side incoming transfer progress and user-cancel approval coverage for USB/LAN and Internet session paths; PR #551/#552/#553 and PR #560/#561 add no-Host readiness, outgoing progress, control reachability, and race-hardening coverage; PR #555, PR #562, and PR #566 record P0110 no-Host transfer UI smoke only; PR #563 keeps active outgoing transfer controls visible while sending; PR #564 treats Internet outgoing cancellation as locally successful after local owner cleanup while still failing the session if the reliable cancel frame is rejected; PR #567 routes accepted incoming file-transfer progress through the control bar, supports incoming cancellation cleanup, and keeps incoming/outgoing workflows mutually exclusive. PR #575, PR #584, PR #586, PR #590, PR #597, PR #598, PR #602, PR #609, PR #611, PR #612, PR #615, PR #616, and PR #619 add managed-policy/no-Host readiness, transfer progress/layout, duplicate-staging prevention, negative-length rejection, runtime-loss cleanup, settings guidance, and app-specific local-save cleanup coverage. Android control-bar instrumentation, focused JVM tests, protocol fixtures, no-Host UI evidence, and Internet cancel semantic tests pass, but Host readiness is blocked and no retained bidirectional product transfer evidence proves file offer/request/content packets, receiver approval, remote write, SHA-256 equality, session epoch, and cancel cleanup in one product run. |
| Phase 0 module ownership extraction | pass | none | The current-base module ownership manifest now closes the required Android TCP transport, `StreamClient`, protocol/session, file-transfer, WakeHost, decoder, renderer, input-envelope routing, media-frame routing, Android stream telemetry, and UI/product-session boundaries with focused source and offline contract evidence, including the latest file-transfer runtime-loss and local-save cleanup ownership coverage. WakeHost real sleeping-Mac, router/NIC WOL, Host signing/TCC, and retained product evidence remain separate fail-closed runtime gates. |

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

The 2026-09-06 UTC manifest refresh binds the aggregate source guard to
`fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f`, records the current open-PR
snapshot as empty while keeping all required gate `owner_prs` lists empty,
consumes current-main Phase 0 checks run `34017313447`, records merged PR #569
through PR #575 and PR #577 through PR #624 as `main`-targeted source/unit/offline
or no-Host readiness after validating each recorded
`mergeCommit.oid` is reachable from the audited main commit, and keeps the
Android/macOS clipboard and file-transfer product E2E gates as required Phase 0
gates that are blocked. PR #568 and PR #576 were closed without merging and are
not counted as audited mainline inputs. The retained current refresh summary
bundle is under `evidence/2026-09-06-current-main-gate-blocked/`; local
verification also writes the current summary under
`.build/evidence/phase0-stable-release/`.

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
