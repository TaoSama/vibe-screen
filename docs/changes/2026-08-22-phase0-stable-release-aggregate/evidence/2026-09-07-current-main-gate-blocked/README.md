# 2026-09-07 Phase 0 stable-release aggregate after PR #640/#641/#642: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
`origin/main` commit `fdf87a225127d2b2f43b201e3c44dda8d49e64d7`, after PR
#640, PR #641, and PR #642 merged after the previous aggregate refresh. It does
not close Phase 0 and does not change product status.

## Verdict

BLOCKED. The normal guard passes with README guard language and source metadata
bound to the audited source commit, but the aggregate remains blocked because
seven required Phase 0 gates still lack closing evidence:

```sh
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=fdf87a225127d2b2f43b201e3c44dda8d49e64d7 \
  PHASE0_STABLE_RELEASE_SUMMARY=docs/changes/2026-08-22-phase0-stable-release-aggregate/evidence/2026-09-07-current-main-gate-blocked/phase0-stable-release-summary.json
```

The retained summary reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `required_gate_count=13`
- `closed_required_gate_count=6`
- `source_guard.verdict=pass` for commit
  `fdf87a225127d2b2f43b201e3c44dda8d49e64d7`
- `readme_guard.verdict=pass`
- `owner_pr_guard.verdict=pass` with no active owner PRs and no open PRs in the
  retained snapshot
- `merged_pr_guard.verdict=pass` for merged PR #569 through PR #575, PR #577
  through PR #626, and PR #628 through PR #642, with PR #568, PR #576, and PR
  #627 explicitly excluded as closed-unmerged records
- `phase0-module-ownership-summary.json` reports
  `can_close_phase0_module_ownership_extraction=true` with 13 of 13 required
  boundaries closed

## Current-main inputs

PR #640 snapshots peripheral input payloads before asynchronous dispatch reaches
the Android input sender. This hardens source/unit behavior only and does not
provide physical HID pointer acceptance.

PR #642 classifies Host setup connection guidance for Host-unreachable or
route-unavailable states. This is Android guidance/source readiness only and is
not a LAN route, TCP 54321, Host listener, or product-session evidence record.

PR #641 hardens Android audio jitter gap recovery with offline playback stream
and AudioTrack-facing tests. This does not prove real Android/macOS audio E2E,
Host microphone capture, or any Phase 0 stable-release runtime gate.

The previous aggregate refresh PR #639 is also merged into the audited mainline
base. The merged PR snapshot now covers PR #569 through PR #575, PR #577 through
PR #626, and PR #628 through PR #642. The refresh keeps these inputs classified
as source/unit/offline/no-Host readiness unless a gate-specific retained product
evidence bundle says otherwise.

At query time, GitHub Actions for commit `fdf87a225127d2b2f43b201e3c44dda8d49e64d7`
reported HarmonyOS portable checks as completed successfully, while Phase 0
checks and iOS engineering gates were still in progress. This aggregate refresh
therefore does not replace prior current-CI evidence with those in-progress runs.

## Blocking required gates

The aggregate remains blocked by the same seven required gates. None of these is
converted to pass by this refresh.

- `macos_host_hardware_compatibility_matrix`: open. Stable-signed Host
  compatibility rows with read-only TCC, source provenance, stream/input,
  reconnect, Intel/additional Apple silicon, macOS build, and display topology
  coverage are still missing.
- `telemetry_and_latency_archive`: insufficient. No external-camera latency
  sample package, raw camera media, annotated sample set, or synchronized-clock
  physical-input proof is archived.
- `host_rss_2h_no_growth`: blocked. The retained two-hour Xiaomi 13 run still
  shows Host RSS growth, and no current-source two-hour `host_rss_gate` pass is
  recorded.
- `native_pointer_hid_mouse`: blocked. No physical Android mouse, touchpad, or
  trackball run retains Android forwarding logs, Host injection logs, and visible
  Mac move/click evidence from the same window.
- `controller_runtime_acceptance`: blocked. No physical controller plus
  identity-signed entitled Host plus Mac-side response plus neutral disconnect
  release pass is recorded.
- `clipboard_android_macos_product_e2e`: blocked. No retained bidirectional
  Android `ClipboardManager` <-> macOS `NSPasteboard` product transfer evidence
  exists with session epoch/origin, 16-byte change ID, SHA-256 digest, bounded
  byte length, and final marker equality.
- `file_transfer_android_product_e2e`: blocked. No retained bidirectional
  Android <-> macOS product transfer evidence exists with file
  offer/request/content packets, explicit sender action, receiver approval,
  remote write, final SHA-256 equality, positive session epoch, and cancel
  cleanup.

## Artifacts

- `phase0-stable-release-summary.json`: machine-readable blocked aggregate
  summary from the expected-source guard.
- `phase0-module-ownership-summary.json`: module ownership summary proving the
  module ownership sub-gate remains closed.
- `phase0-stable-release-exit.txt`: captured Make release-claim gate exit
  status, expected to be `2` while the seven required gates remain blocked.
- `head.txt`: audited local HEAD, `origin/main`, and recent commits.
- `open-prs.json`: open PR snapshot, empty at this refresh.
- `merged-prs-568-642.jsonl`: merged PR range audit input from GitHub.
- `closed-prs-568-642.json`: retained closed-unmerged PR range snapshot
  proving PR #568, PR #576, and PR #627 did not land in the audited mainline
  base.
- `pr-640-merged.json`, `pr-641-merged.json`, `pr-642-merged.json`: merged-state
  snapshots for the post-refresh non-aggregate PRs.
- `github-runs-fdf87a225.json`: GitHub workflow snapshot for the audited commit
  at query time.
- `commands.txt`: command ledger for this refresh.
- `SHA256SUMS`: artifact checksums.
