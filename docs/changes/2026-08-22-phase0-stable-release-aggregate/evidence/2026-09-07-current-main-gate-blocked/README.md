# 2026-09-07 Phase 0 stable-release aggregate after PR #647: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
`origin/main` commit `46e8b18eebe8f622d3ba71530df3f76c94197b79`, after PR
#647 merged after the previous aggregate refresh. It does
not close Phase 0 and does not change product status.

## Verdict

BLOCKED. The normal guard passes with README guard language and source metadata
bound to the audited source commit, but the aggregate remains blocked because
seven required Phase 0 gates still lack closing evidence:

```sh
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=46e8b18eebe8f622d3ba71530df3f76c94197b79 \
  PHASE0_STABLE_RELEASE_SUMMARY=docs/changes/2026-08-22-phase0-stable-release-aggregate/evidence/2026-09-07-current-main-gate-blocked/phase0-stable-release-summary.json
```

The retained summary reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `required_gate_count=13`
- `closed_required_gate_count=6`
- `source_guard.verdict=pass` for commit
  `46e8b18eebe8f622d3ba71530df3f76c94197b79`
- `readme_guard.verdict=pass`
- `owner_pr_guard.verdict=pass` with no active owner PRs; the retained open PR
  snapshot records PR #645 and PR #648 as open
- `merged_pr_guard.verdict=pass` for merged PR #569 through PR #575, PR #577
  through PR #626, PR #628 through PR #644, and PR #647, with PR #568, PR #576,
  PR #627, PR #645, and PR #646 explicitly excluded from the complete range
  because they are not merged in the audited mainline base
- `phase0-module-ownership-summary.json` reports
  `can_close_phase0_module_ownership_extraction=true` with 13 of 13 required
  boundaries closed

## Current-main inputs

PR #647 hardens evidence fail-closed validation across Host RSS, latency,
preflight, and Phase 0 stable-release tooling. This is source/tooling readiness
only; it does not provide Host-backed product evidence, external-latency media,
Host RSS no-growth evidence, physical HID pointer acceptance, physical
controller runtime acceptance, or clipboard/file-transfer product E2E evidence.

The previous aggregate refresh PR #643 and Android input dispatch boundary PR
#644 are also merged into the audited mainline base. The merged PR snapshot now
covers PR #569 through PR #575, PR #577 through PR #626, PR #628 through PR
#644, and PR #647. PR #645 remained open and PR #646 was closed without merging
at query time, so both are excluded from the complete PR #568 through PR #647
range together with PR #568, PR #576, and PR #627. The refresh keeps these
inputs classified as source/unit/offline/no-Host readiness unless a
gate-specific retained product evidence bundle says otherwise.

At query time, GitHub Actions for commit `46e8b18eebe8f622d3ba71530df3f76c94197b79`
reported HarmonyOS portable checks run `34057276648`, Phase 0 checks run
`34057276628`, and iOS engineering gates run `34057276655` as completed
successfully. The Phase 0 push workflow is retained as CI/source coverage only;
it does not replace the missing product, hardware, Host RSS, clipboard/file-
transfer E2E, or external-latency evidence required by the seven blocked
aggregate gates.

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
- `open-prs.json`: open PR snapshot containing PR #645 and PR #648.
- `merged-prs-568-647.jsonl`: merged PR range audit input from GitHub.
- `closed-prs-568-647.json`: retained closed-unmerged PR range snapshot proving
  PR #568, PR #576, PR #627, and PR #646 did not land in the audited mainline
  base. PR #645 is retained in `open-prs.json` as an open, unmerged PR in the
  complete audited range.
- `pr-647-merged.json`: merged-state snapshot for the target PR.
- `github-runs-46e8b18ee.json`: GitHub workflow snapshot for the audited commit
  at query time.
- `commands.txt`: command ledger for this refresh.
- `SHA256SUMS`: artifact checksums.
