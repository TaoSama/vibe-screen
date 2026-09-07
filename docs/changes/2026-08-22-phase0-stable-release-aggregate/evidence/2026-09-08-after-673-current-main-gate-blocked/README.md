# Phase 0 aggregate refresh after PR #673

Date: 2026-09-08 local / 2026-09-07 UTC
Audited source: `origin/main` / `b363a05183d4330073266bfa06493ecd8d0dc7a9`
Device evidence scope: no new device run. Existing Nubia records remain Nubia P0110 / pacific / Android 16 / API 36 only.

This refresh updates the Phase 0 stable-release aggregate source guard, owner PR guard, and merged PR guard after PR #670, PR #672, and PR #673 were merged. It also records intervening merged PRs #667 through #673 in the audited `main` range.

## Result

`phase0-stable-release-summary.json` reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `closed_required_gate_count=6`
- `source_guard.verdict=pass` for `b363a05183d4330073266bfa06493ecd8d0dc7a9`
- `owner_pr_guard.verdict=pass` with no open owner PRs
- `merged_pr_guard.verdict=pass` for PR #569 through #575, PR #577 through #626, and PR #628 through #673, excluding closed-unmerged PR #568, PR #576, PR #627, PR #646, and PR #655

The strict release-claim invocation still exits nonzero, captured in `phase0-stable-release-expected-source-exit.txt`, because the seven required runtime/product gates remain genuinely open, blocked, or insufficient. The failure is not caused by stale source, owner PR, or merged PR metadata.

## Newly audited PRs

- PR #667 refreshes the previous aggregate after PR #666.
- PR #668 hardens file-transfer remote artifact validation.
- PR #669 hardens clipboard and TCC evidence gates.
- PR #670 hardens the file-transfer Android smoke evidence gate.
- PR #671 hardens Phase 0 RSS and telemetry gates.
- PR #672 hardens the macOS Host readiness gate.
- PR #673 hardens controller runtime artifact evidence validation.

These are source, tooling, readiness, or no-Host validation changes. They do not close the macOS Host hardware compatibility matrix, telemetry/external latency archive, Host RSS no-growth, native pointer HID, controller runtime, Android/macOS clipboard product E2E, or Android/macOS file-transfer product E2E gates.

## Retained artifacts

- `head.txt`: local and remote `main` commit plus recent log context.
- `open-prs.json`: open PR snapshot, empty at refresh time.
- `merged-prs-568-673.jsonl`: audited merged PR range.
- `closed-prs-568-673.json`: closed-unmerged PRs in the audited range.
- `pr-667-merged.json` through `pr-673-merged.json`: detailed merged PR snapshots.
- `github-run-34146375366.json`, `github-run-34146375370.json`, `github-run-34146375343.json`: main push workflow snapshots for the audited source.
- `phase0-module-ownership-summary.json`: module ownership sub-gate summary.
- `phase0-stable-release-summary.json`: aggregate summary.
- `phase0-stable-release-expected-source-exit.txt`: strict release-claim gate exit status.
- `commands.txt`: command ledger.
- `SHA256SUMS`: retained artifact checksums.

## Boundaries

No Vibe Screen, MacHost, or Telemachus GUI was launched. No `swift run`, Screen Recording, Accessibility, Microphone, Keychain, TCC, System Settings, or `adb reverse tcp:54321 tcp:54321` operation was used.
