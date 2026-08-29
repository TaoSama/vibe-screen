# 2026-08-28 Phase 0 stable-release aggregate current-main gate: blocked

This record refreshes the Phase 0 stable-release aggregate owner on current
`origin/main` commit `1430c3cc18948b93b50b7054e992844f287b6fbc`. It does not
close Phase 0 and does not change product status.

## Verdict

BLOCKED. The release-claim gate was run with the manifest explicitly bound to
the audited source commit and returned nonzero as expected:

```sh
make phase0-stable-release-gate \
  PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=1430c3cc18948b93b50b7054e992844f287b6fbc \
  PHASE0_STABLE_RELEASE_REQUIRE_PASS=1
```

The retained summary reports:

- `aggregate_verdict=blocked`
- `can_mark_phase0_stable_release=false`
- `closed_required_gate_count=5` of 11
- `source_guard.verdict=pass` for commit
  `1430c3cc18948b93b50b7054e992844f287b6fbc`
- `readme_guard.verdict=pass`

## Blocking required gates

The aggregate remains blocked by the same six required gates. None of these is
converted to pass by this refresh.

- `macos_host_hardware_compatibility_matrix`: open. The latest compatibility
  summary is blocked readiness, not a current-real-device compatibility matrix
  pass.
- `telemetry_and_latency_archive`: insufficient. The latest current-base
  latency preflight remains blocked readiness; no external-camera latency
  package or synchronized-clock physical-input proof is archived.
- `host_rss_2h_no_growth`: blocked. The retained two-hour Xiaomi 13 run still
  shows Host RSS growth, and the latest current-base short-window record proves
  only fail-closed diagnostics, not a short-window or formal two-hour pass.
- `native_pointer_hid_mouse`: blocked. No physical Android mouse/touchpad or
  trackball pass has retained Android forwarding logs, Host injection logs, and
  visible Mac move/click evidence from the same run.
- `controller_runtime_acceptance`: blocked. No physical controller plus
  identity-signed entitled Host plus Mac-side response plus neutral disconnect
  release pass is recorded.
- `module_ownership_extraction`: open. Additional StreamClient ownership slices
  are now extracted, but broader protocol/session, decoder, renderer, and UI
  boundaries are not fully enforced.

## Safety boundary

This refresh did not invoke `/usr/bin/sfltool dumpbtm`,
`--include-login-item-diagnostic`, `--inspect-login-items`, or
`--probe-login-items`. The start and end `pgrep -x sfltool || true` checks
returned no process IDs.

## Artifacts

- `phase0-stable-release-summary.json`: machine-readable blocked aggregate
  summary from the release-claim gate.
- `phase0-stable-release-exit.txt`: captured Make exit status, `2`.
- `head.txt`: audited source commit.
- `github-runs.txt`: GitHub workflow snapshot for the audited commit.
- `commands.txt`: command ledger for this refresh.
- `SHA256SUMS`: artifact checksums.
