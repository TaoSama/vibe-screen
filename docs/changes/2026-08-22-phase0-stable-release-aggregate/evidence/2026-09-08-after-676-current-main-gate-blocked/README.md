# Phase 0 aggregate refresh after PR #676

Date: 2026-09-08 local
Audited source: `origin/main` / `6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa`
Device evidence scope: no new Host-backed product run. Existing Nubia records remain Nubia P0110 / pacific / Android 16 / API 36 only.

This refresh updates the Phase 0 stable-release aggregate source guard, owner PR guard, merged PR guard, and retained evidence bundle after PR #676 was squash-merged into `origin/main`. PR #676 is the merged aggregate refresh after PR #681; this refresh removes PR #676 from the open PR snapshot and from the excluded merged range while keeping the audited merged PR range through PR #681.

## Result

`phase0-stable-release-summary.json` reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `closed_required_gate_count=6` of `required_gate_count=13`
- `source_guard.verdict=pass` for `6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa`
- `owner_pr_guard.verdict=pass` with no open PRs recorded at refresh time
- `merged_pr_guard.verdict=pass` for PR #569 through #575, PR #577 through #626, and PR #628 through #681, excluding only closed-unmerged PR #568, PR #576, PR #627, PR #646, and PR #655

The strict release-claim invocation still exits nonzero, captured in `phase0-stable-release-expected-source-exit.txt`, because the seven required runtime/product gates remain genuinely open, blocked, or insufficient. The failure is not caused by stale source, owner PR, or merged PR metadata.

## Still blocked

- macOS Host hardware compatibility matrix
- telemetry and external latency artifact archive
- Host RSS two-hour no-growth
- native pointer HID mouse move/click acceptance
- controller runtime acceptance
- Android/macOS clipboard product E2E
- Android/macOS file-transfer product E2E

## Newly audited PR

- PR #676 is the merged aggregate refresh after PR #681. It added the after-681 blocked aggregate evidence bundle and kept Phase 0 blocked. It does not close any runtime/product gate.

The retained PR #674 through PR #681 snapshots remain aggregate/source, tooling, or no-Host validation changes. They do not close the macOS Host hardware compatibility matrix, telemetry/external latency archive, Host RSS no-growth, native pointer HID, controller runtime, Android/macOS clipboard product E2E, or Android/macOS file-transfer product E2E gates.

## Workflow snapshots

- `github-run-34170285701.json`: successful PR #676 Phase 0 checks run for `ba2f092bb61341dd8c46292e3a0043db54caf50b`; that checked tree matches the merge commit tree.
- `github-run-34171279974.json`: successful main-push Phase 0 checks snapshot for `6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa`. This snapshot is retained for current-main source/build traceability and is not counted as Host-backed product evidence.
- `github-run-34171280028.json`: successful after-merge main-push iOS engineering workflow snapshot for `6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa`; it is engineering readiness only, not iPhone/iPad device acceptance.
- `github-run-34171279988.json`: successful after-merge main-push HarmonyOS portable workflow snapshot for `6fb5914029c24d1d78d3d0dd3dfbda3ac37455aa`; it is portable contract readiness only, not HarmonyOS device acceptance.

## Retained artifacts

- `head.txt`: remote `main` commit, audited commit assertion, and recent log context.
- `open-prs.json`: open PR snapshot, empty at refresh time.
- `merged-prs-568-681.jsonl`: audited merged PR range.
- `closed-prs-568-681.json`: closed-unmerged PRs in the audited range.
- `pr-674-merged.json` through `pr-681-merged.json`: detailed merged PR snapshots, including PR #676 as merged.
- `phase0-module-ownership-summary.json`: module ownership sub-gate summary.
- `phase0-stable-release-summary.json`: aggregate summary.
- `phase0-stable-release-exit.txt`: non-strict aggregate gate exit status.
- `phase0-stable-release-expected-source-exit.txt`: strict release-claim gate exit status.
- `commands.txt`: command ledger.
- `SHA256SUMS`: retained artifact checksums.

## Boundaries

No Vibe Screen, MacHost, or Telemachus GUI was launched. No `swift run`, Screen Recording, Accessibility, Microphone, Keychain, TCC, System Settings, or `adb reverse tcp:54321 tcp:54321` operation was used.
