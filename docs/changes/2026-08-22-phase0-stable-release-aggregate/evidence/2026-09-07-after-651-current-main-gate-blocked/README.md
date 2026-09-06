# 2026-09-07 Phase 0 stable-release aggregate after PR #651: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
`origin/main` commit `ac804cb98adbb061cd01e8f6a9db93adb78ca9c5`, after PR
#651 merged. It does not close Phase 0 and does not change product status.

## Verdict

BLOCKED. The normal guard passes with README guard language and source metadata
bound to the audited source commit, but the aggregate remains blocked because
seven required Phase 0 gates still lack closing evidence:

```sh
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=ac804cb98adbb061cd01e8f6a9db93adb78ca9c5 \
  PHASE0_STABLE_RELEASE_SUMMARY=docs/changes/2026-08-22-phase0-stable-release-aggregate/evidence/2026-09-07-after-651-current-main-gate-blocked/phase0-stable-release-summary.json
```

The retained summary reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `required_gate_count=13`
- `closed_required_gate_count=6`
- `source_guard.verdict=pass` for commit
  `ac804cb98adbb061cd01e8f6a9db93adb78ca9c5`
- `readme_guard.verdict=pass`
- `owner_pr_guard.verdict=pass`; the retained open PR snapshot records open PR
  #652 and PR #653, but no required aggregate gate lists either as an active
  owner
- `merged_pr_guard.verdict=pass` for merged PR #569 through PR #575, PR #577
  through PR #626, and PR #628 through PR #651, with PR #568, PR #576, PR
  #627, and PR #646 explicitly excluded from the complete range because they
  are not merged in the audited mainline base
- `phase0-module-ownership-summary.json` reports
  `can_close_phase0_module_ownership_extraction=true` with 13 of 13 required
  boundaries closed

## Current-main inputs

PR #649 refreshed the aggregate after PR #645. PR #650 hardened the clipboard
and file-transfer product E2E evidence gates. PR #651 then added Android
peripheral-input diagnostics and pointer guards. These are tooling/source/
offline/no-Host readiness changes only; they do not provide Host-backed product
evidence, external-latency media, Host RSS no-growth evidence, physical HID
pointer acceptance, physical controller runtime acceptance, or
clipboard/file-transfer product E2E evidence.

For clipboard, PR #650 makes the product gate reject absolute paths, `..`
escapes, symlink escapes, missing files, empty files, and duplicate artifact
reuse. A closing product evidence bundle must retain distinct non-empty
evidence-relative files for `source_clipboard_read`, `sender_action`,
`receiver_approval`, `protocol_packets`, `destination_clipboard_write`,
`final_verification`, and `negative_boundary_verification`.

For file transfer, PR #650 makes the product gate require exact endpoints,
session ID/epoch, observed progress, exact direction labels, distinct
32-character transfer IDs, distinct file names, distinct SHA-256 payload
digests, and distinct non-empty evidence-relative artifacts for
`sender_action`, `receiver_approval`, `protocol_packets`, `remote_file`, and
`sha256_verification`.

Open PR #652 and PR #653 were present at query time. Neither is counted as
merged current-main evidence and neither is listed as an active owner for any
required Phase 0 aggregate gate in this manifest.

The merged PR snapshot now covers PR #569 through PR #575, PR #577 through PR
#626, and PR #628 through PR #651. PR #568, PR #576, PR #627, and PR #646 were
closed without merging at query time, so they are excluded from the complete PR
#568 through PR #651 range. The refresh keeps these inputs classified as
source/unit/offline/tooling/no-Host readiness unless a gate-specific retained
product evidence bundle says otherwise.

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
  exists with exact endpoints, explicit user action, Protocol v1 session
  ownership, session epoch/origin, 16-byte change ID, SHA-256 digest, bounded
  byte length, final marker equality, and distinct retained artifacts for every
  required role.
- `file_transfer_android_product_e2e`: blocked. No retained bidirectional
  Android <-> macOS product transfer evidence exists with file
  offer/request/content packets, explicit sender action, receiver approval,
  remote write, final SHA-256 equality, distinct IDs/names/payload digests, exact
  source/destination endpoints, progress, and cancel cleanup.

## Artifacts

- `phase0-stable-release-summary.json`: machine-readable blocked aggregate
  summary from the expected-source guard.
- `phase0-module-ownership-summary.json`: module ownership summary proving the
  module ownership sub-gate remains closed.
- `phase0-stable-release-exit.txt`: captured Make release-claim gate exit
  status, expected to be `2` while the seven required gates remain blocked.
- `head.txt`: audited local HEAD, `origin/main`, and recent commits.
- `open-prs.json`: open PR snapshot, containing PR #652 and PR #653 at query
  time.
- `merged-prs-568-651.jsonl`: merged PR range audit input from GitHub.
- `closed-prs-568-651.json`: retained closed-unmerged PR range snapshot proving
  PR #568, PR #576, PR #627, and PR #646 did not land in the audited mainline
  base.
- `pr-649-merged.json`: merged-state snapshot for the previous aggregate
  refresh PR.
- `pr-650-merged.json`: merged-state snapshot for the clipboard/file-transfer
  evidence hardening PR.
- `pr-651-merged.json`: merged-state snapshot for the Android peripheral-input
  diagnostics and pointer guard PR.
- `pr-652-open.json` and `pr-653-open.json`: open-state snapshots retained to
  prove they are outside this merged-main audit input.
- `github-runs-ac804cb98.json`: GitHub workflow snapshot for the audited commit
  after all retained workflow runs reach success.
- `commands.txt`: command ledger for this refresh.
- `SHA256SUMS`: artifact checksums.
