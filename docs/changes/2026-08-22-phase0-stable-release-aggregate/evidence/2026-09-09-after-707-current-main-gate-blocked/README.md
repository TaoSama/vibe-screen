# Phase 0 aggregate refresh after PR #707

Date: 2026-09-09 local
Audited source: origin/main / d8f108aaded3a05708587c721186cf0737bc4dfa
Device evidence scope: no new Host-backed product run. Existing Nubia records
remain Nubia P0110 / pacific / Android 16 / API 36 only.

This refresh updates the Phase 0 stable-release aggregate source guard, owner PR
guard, merged PR guard, and module-ownership source guard after PR #707 and PR
#705 were merged. It records PR #702, PR #703, PR #705, PR #706, and PR #707 as
newly audited main merges after the previous checked-in aggregate refresh, while
PR #708 remained open as a non-owner PR at refresh time.

## Result

After the gate summaries were regenerated, phase0-stable-release-summary.json
reports:

- aggregate_verdict=blocked
- can_mark_phase0_stable_release=false
- closed_required_gate_count=6
- required_gate_count=13
- source_guard.verdict=pass for d8f108aaded3a05708587c721186cf0737bc4dfa
- owner_pr_guard.verdict=pass with open non-owner PR #708 recorded
- merged_pr_guard.verdict=pass for PR #569 through #575, PR #577 through
  #626, and PR #628 through #707, excluding closed-unmerged PR #568, PR #576,
  PR #627, PR #646, PR #655, and PR #704

The strict release-claim invocation still exits nonzero, captured in
phase0-stable-release-expected-source-exit.txt, because the seven required
runtime/product gates remain open, blocked, or insufficient. The failure is not
caused by stale source, owner PR, or merged PR metadata.

## Newly audited PRs

- PR #702 refreshes the previous aggregate after PR #701.
- PR #703 refreshes P0110 no-Host UI/UX current-main evidence after PR #700.
- PR #705 hardens controller runtime artifact evidence paths.
- PR #706 hardens Host RSS readiness safety checks so readiness packages that
  install or replace the Host, claim to close runtime gates, or omit required
  structured source paths fail closed before they can be reused as Host RSS
  closure evidence.
- PR #707 clarifies macOS compatibility TCC requirements and aggregate
  source-guard test-file handling.

These are aggregate/source and fail-closed validation changes. They do not close
the macOS Host hardware compatibility matrix, telemetry/external latency
archive, Host RSS no-growth, native pointer HID, controller runtime,
Android/macOS clipboard product E2E, or Android/macOS file-transfer product E2E
gates.

## Current workflow snapshot

The current d8f108aaded3a05708587c721186cf0737bc4dfa main push workflow metadata
was retained as observed during this refresh:

- github-run-34269811139.json: Phase 0 checks, status=in_progress, no
  conclusion at capture time.
- github-run-34269811156.json: iOS engineering gates, status=completed,
  conclusion=success.
- github-run-34269811130.json: HarmonyOS portable checks, status=completed,
  conclusion=success.

The in-progress and completed workflow snapshots are current-state metadata
only. They are not counted as new passing stable-release signals in this
aggregate refresh.

## Remaining fail-closed gates

- macos_host_hardware_compatibility_matrix
- telemetry_and_latency_archive
- host_rss_2h_no_growth
- native_pointer_hid_mouse
- controller_runtime_acceptance
- clipboard_android_macos_product_e2e
- file_transfer_android_product_e2e

The next README open gate to advance remains
macos_host_hardware_compatibility_matrix. Under this task's constraints no GUI
Host launch, TCC/System Settings action, swift run, or adb reverse tcp:54321
tcp:54321 operation was allowed, so this refresh can only identify that next
gate and keep it open.

## Retained artifacts

- head.txt: remote main commit, audited commit assertion, and recent log
  context.
- open-prs.json: open PR snapshot, including non-owner PR #708 at refresh time.
- merged-prs-568-707.jsonl: audited merged PR range.
- closed-prs-568-707.json: closed-unmerged PRs in the audited range.
- pr-702-merged.json, pr-703-merged.json, pr-705-merged.json,
  pr-706-merged.json, and pr-707-merged.json: detailed merged PR snapshots for
  the newly audited range; pr-704-closed.json records the closed-unmerged
  exclusion.
- github-run-34269811139.json, github-run-34269811156.json, and
  github-run-34269811130.json: current-source workflow snapshots for the audited
  d8f108aaded3a05708587c721186cf0737bc4dfa main push as observed during this
  refresh.
- phase0-module-ownership-summary.json: module ownership sub-gate summary.
- phase0-stable-release-summary.json: aggregate summary.
- phase0-stable-release-expected-source-exit.txt: strict release-claim gate exit
  status.
- commands.txt: command ledger.
- SHA256SUMS: retained artifact checksums.

## Boundaries

No Vibe Screen, MacHost, or Telemachus GUI was launched. No swift run, Screen
Recording, Accessibility, Microphone, Keychain, TCC, System Settings, or adb
reverse tcp:54321 tcp:54321 operation was used.
