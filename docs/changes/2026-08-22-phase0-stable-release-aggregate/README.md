# Phase 0 stable-release aggregate owner

Date: 2026-08-29
Last refreshed: 2026-09-09 local
Base: origin/main at ce4a3f1e74f45d286a1ab8118849bbbc27865fc5
Status: open. Phase 0 remains in progress rather than a stable release. This
document does not close Phase 0 and does not change product status. Do not
treat roadmap items below as shipped features.
Open PR input: `gh pr list --repo TaoSama/vibe-screen --state open --limit 200
--json number,title,headRefName,headRefOid,baseRefName,updatedAt,isDraft,mergeStateStatus,url | jq 'sort_by(.number)'`
recorded no open PRs at refresh time. No required Phase 0 aggregate gate lists
an active owner PR in this refresh. PR #714 through PR #721 are now merged into
the audited mainline input after the previous checked-in aggregate refresh. PR
#714 refreshes the aggregate after PR #713, PR #715 hardens macOS TCC latest-row
preflight coverage, PR #716 refreshes P0110 no-Host UI/UX evidence, PR #717
fixes after-713 UI/UX evidence notes, PR #718 preserves wireless and QR UI
safeguards, PR #719 refreshes the aggregate after PR #720, PR #720 preserves
no-Host UI accessibility coverage, and PR #721 covers no-Host wireless LAN UI
state/accessibility contracts without adding Host-backed product evidence.
Merged PR #569 through PR #575, PR #577 through PR #626, and PR #628 through PR #721
were collected with `--base main`,
`baseRefName`, and `mergeCommit`; the checker verifies each recorded merge
commit is an ancestor of the audited mainline base before treating it as an
audited input. PR #568, PR #576, PR #627, PR #646, and PR #655 were closed
without merging, and PR #704 was closed without merging, so they are explicitly
excluded from the audited merged range.
Audited merged PRs in this range include PR #569 through PR #575, PR #577
through PR #626, and PR #628 through PR #721 after the unmerged exclusions
above. They add additional Android no-Host
UI/layout evidence,
clipboard baseline/control hardening, keyboard boundary coverage, AV1 and
managed-policy no-Host admission probes, controller hotplug neutral-release
coverage, AudioTrack no-Host smoke, file-transfer no-Host/runtime-loss/local-save
cleanup coverage, managed-policy control happy-path coverage,
transfer-readiness copy/heading/selectability, host-unreachable/route-unavailable
guidance JVM coverage, Host TCC identity preflight tightening, WakeHost or
actionable-error gate documentation fixes, aggregate source-guard refreshes,
telemetry latency evidence gate hardening, Host RSS telemetry coverage gate
hardening, no-Host Android UI check stabilization, phase0 evidence guidance
hardening, Android audio protocol contract hardening, input move coalescing
domain isolation, Android network-down/Host setup connection guidance,
peripheral input payload snapshotting, Android audio jitter gap recovery,
aggregate source-guard refresh evidence, Android input dispatch boundary
validation, evidence fail-closed validation hardening, P0110 no-Host UI/UX
review evidence, Phase 0 aggregate refresh evidence, PCM audio protocol
boundary hardening, clipboard/file-transfer product evidence gate hardening,
peripheral input diagnostics and pointer guards, aggregate refresh evidence,
formal latency archive validator hardening, Android file-offer readability,
audio readiness Settings status, clipboard confirmation-dialog handling, outgoing
file-transfer confirmation, exact clipboard/file-transfer artifact role
validation, reused clipboard artifact rejection, file-transfer smoke evidence
gate hardening, current-main no-Host clipboard/file-transfer dialog evidence,
remote file-transfer artifact validation, clipboard/TCC gate hardening, Phase 0
RSS and telemetry gate hardening, macOS Host readiness gate hardening,
controller runtime artifact evidence gate hardening, no-Host UI/UX current-main
evidence, latency artifact-role reuse validation hardening, Android clipboard
preview policy hardening, Android file-transfer cleanup recovery hardening,
Android clipboard no-Host baseline hardening, additional no-Host UI/UX and
audio readiness evidence, README capability-gap audit records, Settings
accessibility source coverage, further fail-closed hardening for file-transfer
product E2E, clipboard E2E, native pointer HID, macOS Host compatibility,
controller runtime, Host RSS, telemetry latency archive evidence gates, a formal
macOS Host compatibility passing-row requirement, Host RSS readiness safety
metadata validation, macOS compatibility TCC documentation/source-guard
clarification, aggregate refresh evidence, clipboard/file-transfer product E2E
artifact validation hardening, native-pointer HID/controller runtime formal
report hardening, current-main aggregate refresh evidence, clipboard product
E2E source/evidence plus aggregate revalidation hardening, macOS TCC latest-row
preflight coverage, P0110 no-Host UI/UX evidence note refreshes, no-Host UI
accessibility coverage, and wireless LAN UI state/accessibility contract
coverage.
These are recorded as source/unit/offline or no-Host readiness only. They
do not close any blocked
Host-backed real-device gate, bidirectional clipboard product E2E gate,
bidirectional file-transfer product E2E gate, physical HID pointer gate, physical
controller runtime gate, Host RSS gate, macOS Host compatibility matrix, or
external latency archive gate.

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
| Protocol v1 contract and CI gates | pass | none | Current main at `ce4a3f1e74f45d286a1ab8118849bbbc27865fc5` is bound by this source audit. Previously retained successful CI snapshots remain source/build evidence; the after-721 evidence bundle also records completed main workflow metadata for this audited source. These CI snapshots are not counted as new Host-backed product evidence. |
| Android tests and debug APK clean build | pass | none | Current main at `ce4a3f1e74f45d286a1ab8118849bbbc27865fc5` includes the earlier source/unit/offline/tooling and no-Host readiness updates plus PR #714 through PR #721. The new PR range contributes aggregate refresh evidence, macOS TCC latest-row preflight coverage, no-Host UI/UX evidence note refreshes, wireless and QR UI safeguards, accessibility coverage, wireless LAN UI state/accessibility contracts, and fail-closed evidence-tool hardening. These updates are not treated as Host-backed product evidence. |
| macOS release build and full-Xcode unit tests | pass | none | Current main at `ce4a3f1e74f45d286a1ab8118849bbbc27865fc5` is bound by this source audit. Previously retained successful CI snapshots remain source/build evidence, while local 2026-08-28 full-Xcode readiness remains blocked because that machine had Command Line Tools selected and is not a replacement XCTest pass. |
| macOS Host hardware compatibility matrix | open | none | Published current-base `macos-hardware-compatibility-gate` summaries exist for Mac16,8 readiness, but they are `blocked`. PR #546 strengthened the preflight so Host readiness now fails closed without read-only Screen Recording, Accessibility, and Microphone TCC rows bound by `csreq` to the stable signing requirement, bundle id, install path, and source provenance. Merged PR #625 tightens Host TCC identity preflight, PR #672 further hardens the macOS Host readiness gate with source tree, install path, pinned signing leaf, canonical designated requirement, Microphone TCC, TCC auth_reason, TCC csreq identity-bound checks, and TCP listener process identity, PR #699 requires retained artifact roles, and PR #700 requires the Phase 0 aggregate to cite a formal passing macOS Host compatibility matrix row before closing this gate; these are fail-closed validation updates only. Closed-unmerged PR #627 does not provide passing hardware compatibility matrix evidence. A real packaged Host launch, Protocol v1 stream, input, reconnect evidence, Intel Macs, additional Apple silicon models, macOS builds, and display topologies still need exact-row passing evidence. |
| Android USB stream, reconnect, stale epoch, and codec fallback | pass | none | Closed by retained historical real-device baseline evidence; current-base insufficient attempts remain boundary records and do not claim a fresh USB pass. Merged PR #569 through PR #575, PR #577 through PR #626, and PR #628 through PR #721 add source/unit/offline, tooling, aggregate, or no-Host readiness evidence, but those records are not counted as stream/reconnect, LAN route, TCP 54321, Host-backed product, physical HID pointer, controller, or retained device evidence. |
| Telemetry and external latency artifact archive | insufficient | none | PR #557 adds Android stream telemetry counters for dropped frames, decoder latency, session epoch, wire mode, and heartbeat source with focused JVM coverage, but those counters are diagnostic/source readiness only. PR #545 tightened the latency evidence gate, and PR #656, PR #671, and PR #701 further harden formal latency/telemetry archive validation so malformed, insufficient, non-revalidating, or textually non-closing packages fail closed; PR #706 hardens Host RSS readiness safety checks only, and PR #707 clarifies macOS compatibility TCC documentation/source-guard behavior only. Raw telemetry plus the latest current-base latency preflight remain insufficient. No external-camera latency sample package, raw camera media, or synchronized-clock physical-input proof is archived for this aggregate. The aggregate checker fails closed if this gate is marked `pass` without repo-local structured JSON evidence containing both a passing formal `latency_evidence_gate` report and a passing `android_usb_live_smoke` report with stream telemetry and decoder counters. The formal report must revalidate its `source.manifest`; summary-only latency JSON, telemetry-stage diagnostics, preflight JSON, screenshots, screen recordings, decoder counters, prose-only artifacts, and retained text admitting no-Host, diagnostic-only, preflight-only, summary-only, missing synchronized-clock, or missing physical-input context cannot substitute for closing evidence. Former tooling PR references are merged or stale baselines, not active open owners. |
| Host RSS two-hour no-growth | blocked | none | The retained two-hour Xiaomi 13 run grew about 18.3 MB. The latest 2026-08-31 current-base readiness record proves fail-closed diagnostics only and is still blocked before a stable-signed, read-only TCC-proven, listener-observed current-source Host can produce native telemetry and a current-source two-hour `host_rss_gate` pass. PR #706 hardens Host RSS readiness safety metadata validation so readiness packages that install or replace the Host, claim to close runtime gates, or omit required structured source paths fail closed; PR #707 only clarifies macOS compatibility TCC documentation/source-guard behavior. Former Host RSS/readiness PR references are merged or closed baseline records, not active open owners. |
| Native pointer HID mouse move/click acceptance | blocked | none | PR #558 adds Android native pointer hover enter/exit mapping and fail-closed unsupported-button filtering with focused JVM coverage, and PR #711 hardens the formal retained-report validation for native-pointer HID evidence. Physical HID acceptance remains blocked because no physical Android mouse/touchpad/trackball pass retains Android forwarding logs, Host pointer-injection logs, and visible Mac evidence from one run. Former native-pointer owner PR references are no longer active open owners. |
| Controller runtime acceptance | blocked | none | Latest current-base readiness remains blocked: no physical controller, identity-signed Host with approved virtual HID entitlement, Mac-side response, and neutral disconnect release are recorded in one pass bundle. PR #711 hardens the formal retained-report validation for controller runtime evidence only. Former controller owner PR references are no longer active open owners. |
| Android/macOS clipboard product E2E | blocked | none | PR #547 adds Android-side explicit overwrite confirmation coverage before writing solicited or direct Mac clipboard content into `ClipboardManager`; PR #572 hardens the clipboard baseline gate; PR #605 shows pending Android clipboard status; PR #618 hardens clipboard control contracts; PR #620 covers the allowed managed-policy control happy path; PR #659 improves Android clipboard confirmation dialogs; PR #661 requires exact clipboard artifact roles; PR #664 rejects reused retained artifact paths across transfer directions. The 2026-09-08 P0110 current-main no-Host refresh expands Android `ClipboardManagerInstrumentedTest` to 8 executed tests covering ordinary foreground text, instrumentation set/read, 256 KiB and 320 KiB UTF-8 text, empty clipboard clearing, non-text Intent `ClipData`, and multi-item first-non-text handling, plus 2 clipboard dialog layout tests; it also records that 512 KiB and 1 MiB local Android system-clipboard writes hit Binder transaction-size limits on this device, so the Protocol v1 1 MiB ceiling remains JVM/protocol evidence only. Local P0110 smoke plus offline/protocol checks pass, but Host readiness is still blocked and no retained bidirectional Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence exists with exact endpoints, explicit user action, Protocol v1 session ownership, verified session epoch/origin, 16-byte change IDs, SHA-256 equality, bounded byte length, distinct final markers, and evidence-relative non-empty retained artifacts for source read, sender action, receiver approval, protocol packets, destination write, final verification, and negative boundary verification, with each role backed by a distinct file whose declared direction, recorded byte length, and SHA-256 match the retained bytes, whose destination-write artifact matches the direction-level payload size and digest, and whose protocol-packet JSONL contains offer/request/content records matching the direction change ID, session epoch, and origin. |
| Android/macOS file-transfer product E2E | blocked | none | PR #547 adds Android-side incoming transfer progress and user-cancel approval coverage for USB/LAN and Internet session paths; PR #551/#552/#553 and PR #560/#561 add no-Host readiness, outgoing progress, control reachability, and race-hardening coverage; PR #555, PR #562, and PR #566 record P0110 no-Host transfer UI smoke only; PR #563 keeps active outgoing transfer controls visible while sending; PR #564 treats Internet outgoing cancellation as locally successful after local owner cleanup while still failing the session if the reliable cancel frame is rejected; PR #567 routes accepted incoming file-transfer progress through the control bar, supports incoming cancellation cleanup, and keeps incoming/outgoing transfer workflows mutually exclusive. PR #575, PR #584, PR #586, PR #590, PR #597, PR #598, PR #602, PR #609, PR #611, PR #612, PR #615, PR #616, PR #619, PR #657, PR #660, PR #663, PR #665, PR #666, PR #668, and PR #670 add managed-policy/no-Host readiness, transfer progress/layout, duplicate-staging prevention, negative-length rejection, runtime-loss cleanup, settings guidance, app-specific local-save cleanup coverage, incoming file-offer readability, outgoing file-transfer confirmation, exact required artifact role validation, current-main no-Host dialog evidence, remote file-transfer artifact validation, and file-transfer smoke evidence gate hardening. Android control-bar instrumentation, focused JVM tests, protocol fixtures, no-Host UI evidence, and Internet cancel semantic tests pass, but Host readiness is blocked and no retained bidirectional product transfer evidence proves file offer/request/content packets, receiver approval, remote write, verified 16-byte session ID/epoch, distinct 16-byte transfer IDs, distinct file names and SHA-256 payload digests, ordered chunk offsets with final markers, observed progress, exact source/destination endpoints, evidence-relative non-empty artifacts with distinct files per role, and cancel/disconnect cleanup in one product run. |
| Phase 0 module ownership extraction | pass | none | The current-base module ownership manifest now closes the required Android TCP transport, `StreamClient`, protocol/session, file-transfer, WakeHost, decoder, renderer, input-envelope routing, media-frame routing, Android stream telemetry, and UI/product-session boundaries with focused source and offline contract evidence, including the latest file-transfer runtime-loss and local-save cleanup ownership coverage. WakeHost real sleeping-Mac, router/NIC WOL, Host signing/TCC, and retained product evidence remain separate fail-closed runtime gates. |

PR #656 and PR #671 are included as evidence-tool hardening for the formal
latency, telemetry, and Host RSS archive validators only. PR #657, PR #659, and
PR #660 are included as Android source/UI readiness for file-offer readability,
clipboard confirmation dialogs, and outgoing file-transfer confirmation only. PR
#658 is included as Android audio readiness Settings source/UI coverage only. PR
#661, PR #663, PR #664, PR #668, and PR #670 are included as clipboard/file-transfer
evidence-tool hardening only. PR #666 is included as no-Host clipboard/file-transfer
dialog evidence only. PR #669 is included as clipboard/TCC evidence-tool
hardening only. PR #672 is included as macOS Host readiness gate hardening only.
PR #673 contributes controller runtime artifact evidence gate hardening only. PR
#675 contributes no-Host Android UI/UX current-main evidence only. PR #676 and
PR #682 contribute aggregate refresh evidence only. PR #677 and PR #694
contribute telemetry latency archive validator hardening only. PR #678
contributes Android clipboard preview policy hardening only. PR #679 contributes
Android file-transfer cleanup recovery hardening only. PR #680 contributes
Android clipboard no-Host baseline hardening only. PR #681 and PR #684
contribute README evidence-link, boundary wording, and capability-gap audit
records only. PR #683 and PR #692 contribute Nubia P0110/pacific no-Host
UI/UX evidence only. PR #685 contributes Android AudioTrack no-Host smoke
evidence only. PR #686 contributes Android Settings accessibility source coverage
only. PR #687 and PR #697 contribute file-transfer product E2E evidence-tool
hardening only. PR #688 and PR #696 contribute clipboard E2E evidence-tool
hardening only. PR #689 and PR #695 contribute native pointer HID fail-closed
evidence-tool hardening only. PR #690 contributes macOS Host compatibility
runtime gate hardening only. PR #691 contributes controller runtime evidence
mapping hardening only. PR #693 contributes Host RSS readiness evidence binding
hardening only. PR #698 contributes aggregate refresh evidence only. PR #699
contributes macOS Host compatibility artifact-role gate hardening only. PR #700
contributes Phase 0 aggregate macOS compatibility passing-row gate hardening only.
PR #701 contributes latency artifact closure text validation hardening only. PR
#702, PR #708, and PR #712 contribute aggregate refresh evidence only. PR #703
contributes Nubia P0110/pacific no-Host UI/UX current-main evidence only. PR
#706 contributes Host RSS readiness safety-check hardening only. PR #709
contributes clipboard product E2E evidence-tool hardening only. PR #710
contributes file-transfer product E2E evidence-tool hardening only. PR #711
contributes native-pointer HID and controller runtime evidence-tool hardening
only. PR #713 contributes clipboard product E2E source/evidence and aggregate
revalidation hardening only. PR #714 contributes aggregate refresh evidence
only. PR #715 contributes macOS TCC latest-row preflight source coverage only.
PR #716 and PR #717 contribute P0110 no-Host UI/UX evidence refresh and
documentation correction only. PR #718 contributes wireless and QR UI safeguard
tests only. PR #719 contributes aggregate refresh evidence only. PR #720
contributes no-Host Android UI accessibility coverage only. PR #721 contributes
no-Host wireless LAN UI state/accessibility contract coverage only.
These updates do not convert any
Host-backed, physical HID, controller, clipboard, file-transfer, Host RSS,
compatibility-matrix, or external-latency gate to pass.

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

The 2026-09-09 local manifest refresh binds the aggregate source guard to
`ce4a3f1e74f45d286a1ab8118849bbbc27865fc5`, records no open PRs, records merged
PR #569 through PR #575, PR #577 through PR #626, and
PR #628 through PR #721 as `main`-targeted source/unit/offline, tooling,
aggregate, or no-Host readiness after validating each recorded `mergeCommit.oid`
is reachable from the audited main commit, and keeps the Android/macOS clipboard
and file-transfer product E2E gates as required Phase 0 gates that are blocked.
PR #658 contributes Android audio readiness Settings source/UI coverage only; PR
#661, PR #663, PR #664, PR #665, PR #668, and PR #670 contribute
clipboard/file-transfer evidence-tool hardening only. PR #666 contributes
no-Host dialog evidence only. PR #669 and PR #672 contribute clipboard/TCC and
macOS Host readiness gate hardening only. PR #671 and PR #701 contribute telemetry
latency archive validator hardening only. PR #673 contributes controller runtime artifact evidence
gate hardening only. PR #675 contributes no-Host Android UI/UX current-main
evidence only, PR #676 contributes aggregate refresh evidence only, PR #677 contributes latency artifact-role reuse validation
hardening only, PR #678 contributes Android clipboard preview policy hardening
only, PR #679 contributes Android file-transfer cleanup recovery hardening only,
PR #680 contributes Android clipboard no-Host baseline hardening only, PR #681
through PR #721 contribute only aggregate, README, source, tooling,
fail-closed validation, or no-Host readiness evidence, and PR #704 was closed
without merging and excluded from this audited mainline base. They do not close
Host/TCC, Host RSS, native pointer HID, controller runtime, clipboard product
E2E, file-transfer product E2E, or real Android/macOS audio E2E gates. PR #568,
PR #576, PR #627, PR #646, PR #655, and PR #704 are explicitly excluded from the
complete audited PR #568 through PR #721 range because they are not merged in the
audited mainline base. The retained current
refresh summary bundle is under
`evidence/2026-09-09-after-721-current-main-gate-blocked/`; local verification
also writes the current summary under `.build/evidence/phase0-stable-release/`.

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
