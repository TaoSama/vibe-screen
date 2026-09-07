# 2026-09-07 Phase 0 stable-release aggregate after PR #664: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
origin/main commit 518f6f8512d7f47d36d444557ab841ea0d5e0b83, after PR #664
merged. It does not close Phase 0 and does not change product status.

## Verdict

BLOCKED. The normal guard passes with README guard language and source metadata
bound to the audited source commit, but the aggregate remains blocked because
seven required Phase 0 gates still lack closing evidence.

The retained summary reports aggregate_verdict=blocked,
can_mark_phase0_stable_release=false, required_gate_count=13,
closed_required_gate_count=6, source_guard.verdict=pass for commit
518f6f8512d7f47d36d444557ab841ea0d5e0b83, readme_guard.verdict=pass, and
owner_pr_guard.verdict=pass. The open PR snapshot contains PR #662 only, this
aggregate refresh PR itself, and no required aggregate gate lists an active
owner PR. The merged PR guard covers merged PR #569 through PR #575, PR #577
through PR #626, and PR #628 through PR #664, with PR #568, PR #576, PR #627,
PR #646, PR #655, and PR #662 explicitly excluded because they are not merged
in the audited mainline base. The module ownership summary still reports
can_close_phase0_module_ownership_extraction=true with 13 of 13 required
boundaries closed.

The release-claim command remains fail-closed. The user-requested command
without an expected source guard exits 2 because release-claim mode requires
PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT; the stricter variant with
PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=518f6f8512d7f47d36d444557ab841ea0d5e0b83
also exits 2 because the aggregate is still blocked.

## Current-main inputs

PR #654 refreshed the aggregate after PR #653 and merged as
2e6e0a773ba04770d36e2d6adfba6068b79fdb52. PR #656 hardened formal latency
archive validation, PR #657 improved incoming file-offer readability, PR #658
added Android audio readiness status in Settings, PR #659 improved clipboard
confirmation dialogs, PR #660 added outgoing file-transfer confirmation, PR
#661 required exact clipboard artifact roles, PR #663 required exact
file-transfer artifact roles, and PR #664 rejected reused clipboard retained
artifact paths across transfer directions before merging as
518f6f8512d7f47d36d444557ab841ea0d5e0b83. These are aggregate, tooling,
source/unit/offline, or no-Host readiness inputs only; they do not provide
Host-backed product evidence, external-latency media, Host RSS no-growth
evidence, physical HID pointer acceptance, physical controller runtime
acceptance, Android/macOS audio product E2E, or clipboard/file-transfer product
E2E evidence.

The open PR snapshot contained PR #662 only at query time. The merged PR
snapshot now covers PR #569 through PR #575, PR #577 through PR #626, and PR #628
through PR #664. PR #568, PR #576, PR #627, PR #646, and PR #655 were closed
without merging at query time, and PR #662 was open as this aggregate refresh PR,
so they are excluded from the complete PR #568 through PR #664 range. The
refresh keeps these inputs classified as
source/unit/offline/tooling or no-Host readiness unless a gate-specific retained
product evidence bundle says otherwise.

PR #661, PR #663, and PR #664 are intentionally recorded as evidence-tool
hardening for clipboard/file-transfer artifact validation only. They do not
close Host/TCC compatibility, Host RSS, native pointer HID, controller runtime,
Android/macOS audio product E2E, Android/macOS clipboard product E2E, or
Android/macOS file-transfer product E2E gates.

## Blocking required gates

The aggregate remains blocked by the same seven required gates. None of these is
converted to pass by this refresh.

- macos_host_hardware_compatibility_matrix: open. Stable-signed Host
  compatibility rows with read-only TCC, source provenance, stream/input,
  reconnect, Intel/additional Apple silicon, macOS build, and display topology
  coverage are still missing.
- telemetry_and_latency_archive: insufficient. PR #656 hardens the validator,
  but no external-camera latency sample package, raw camera media, annotated
  sample set, or synchronized-clock physical-input proof is archived.
- host_rss_2h_no_growth: blocked. The retained two-hour Xiaomi 13 run still
  shows Host RSS growth, and no current-source host_rss_gate pass is recorded.
- native_pointer_hid_mouse: blocked. No physical Android mouse, touchpad, or
  trackball run retains Android forwarding logs, Host injection logs, and
  visible Mac move/click evidence from the same window.
- controller_runtime_acceptance: blocked. No physical controller plus
  identity-signed entitled Host plus Mac-side response plus neutral disconnect
  release pass is recorded.
- clipboard_android_macos_product_e2e: blocked. PR #661 and PR #664 harden
  artifact validation, but no retained bidirectional Android ClipboardManager
  to macOS NSPasteboard product transfer evidence exists with exact endpoints,
  explicit user action, Protocol v1 session ownership, session epoch/origin,
  16-byte change ID, SHA-256 digest, bounded byte length, final marker equality,
  and distinct retained artifacts for every required role.
- file_transfer_android_product_e2e: blocked. PR #663 hardens artifact role
  validation, but no retained bidirectional Android to macOS product transfer
  evidence exists with file offer/request/content packets, explicit sender
  action, receiver approval, remote write, final SHA-256 equality, distinct
  IDs/names/payload digests, exact source/destination endpoints, progress, and
  cancel cleanup.

## Artifacts

- phase0-stable-release-summary.json: machine-readable blocked aggregate summary
  from the expected-source guard.
- phase0-module-ownership-summary.json: module ownership summary proving the
  module ownership sub-gate remains closed.
- phase0-stable-release-exit.txt: captured release-claim gate exit status,
  expected to be 2 while release-claim mode is fail-closed.
- phase0-stable-release-expected-source-exit.txt: captured strict expected-source
  release-claim gate exit status, expected to be 2 while the seven required
  gates remain blocked.
- head.txt: audited local HEAD, origin/main, and recent commits.
- open-prs.json: open PR snapshot containing PR #662 at query time.
- merged-prs-568-664.jsonl: merged PR range audit input from GitHub.
- closed-prs-568-664.json: retained closed-unmerged PR range snapshot proving PR
  #568, PR #576, PR #627, PR #646, and PR #655 did not land in the audited
  mainline base; open-prs.json separately records PR #662 as open.
- pr-654-merged.json, pr-656-merged.json, pr-657-merged.json,
  pr-658-merged.json, pr-659-merged.json, pr-660-merged.json,
  pr-661-merged.json, pr-663-merged.json, and pr-664-merged.json: merged-state
  snapshots for the post-#653 mainline inputs.
- pr-655-closed.json: closed-unmerged duplicate aggregate refresh snapshot.
- github-run-34107468153.json, github-run-34107468232.json, and
  github-run-34107468276.json: GitHub workflow run snapshots for the audited
  commit.
- github-runs-518f6f851.json: GitHub workflow snapshot for the audited commit.
- commands.txt: command ledger for this refresh.
- SHA256SUMS: artifact checksums.
