# 2026-09-06 Phase 0 stable-release aggregate current-main gate: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
`origin/main` commit `fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f`. It does not
close Phase 0 and does not change product status.

## Verdict

BLOCKED. The normal guard passes with README guard language and source metadata
consistent with the manifest, but the release-claim gate was run with the
manifest explicitly bound to the audited source commit and returned nonzero as
expected:

```sh
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f \
  PHASE0_STABLE_RELEASE_REQUIRE_PASS=1
```

The retained summary reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `required_gate_count=13`
- `closed_required_gate_count=6`
- `source_guard.verdict=pass` for commit
  `fbe1b2ec90fdc6e1ca1f7ccbbc20cc42d7886b3f`
- `readme_guard.verdict=pass`
- `owner_pr_guard.verdict=pass` with no active required-gate owner PRs
- `phase0-module-ownership-summary.json` reports
  `can_close_phase0_module_ownership_extraction=true` with 13 of 13 required
  boundaries closed

## Current-main inputs

GitHub reported current open PRs as `[]` at this refresh. PR #623 and PR #624
are now merged into the audited mainline base rather than listed as active
owner PRs. PR #569 through PR #575 and PR #577 through PR #624 are merged into
the audited mainline base. PR #568 and PR #576 were closed without merging and
are not counted as audited mainline inputs.

The merged PR range adds source/unit/offline or no-Host readiness around Android
clipboard controls, file-transfer readiness and cleanup, keyboard boundaries,
managed-policy handling, controller neutral release, AV1 admission probes,
AudioTrack no-Host smoke, UI/layout/accessibility evidence, and gate
documentation fixes, aggregate source-guard refreshes, and P0110 no-Host UI/UX
review evidence. PR #621 adds host-unreachable/route-unavailable guidance JVM
coverage only, PR #622/#624 refresh aggregate evidence, and PR #623 records
no-Host UI/UX review evidence; none counts as USB/LAN route, TCP 54321,
Host-backed product, or retained device evidence. These inputs do not replace
Host-backed product evidence.

Current main also passed GitHub Phase 0 checks run `34017313447`, including the
protocol, phase3, Android, evidence-tools, and macOS jobs.

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
  summary from the release-claim gate.
- `phase0-module-ownership-summary.json`: module ownership summary proving the
  module ownership sub-gate remains closed.
- `phase0-stable-release-exit.txt`: captured Make release-claim gate exit status,
  `2`, expected.
- `head.txt`: audited local HEAD and `origin/main` commit.
- `open-prs.json`: open PR snapshot, `[]`.
- `merged-prs-568-624.jsonl`: merged PR range audit input from GitHub.
- `closed-prs-568-624.json`: retained closed-unmerged PR range snapshot
  proving PR #568 and PR #576 did not land in the audited mainline base.
- `github-run-34017313447.json`: GitHub workflow snapshot for the audited
  commit.
- `commands.txt`: command ledger for this refresh.
- `SHA256SUMS`: artifact checksums.
