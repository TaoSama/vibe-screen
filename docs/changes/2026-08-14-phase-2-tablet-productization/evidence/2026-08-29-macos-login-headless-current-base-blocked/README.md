# 2026-08-29 macOS Login/Headless Current-Base Blocked Evidence

Result: blocked. This package refreshes the macOS login-startup, headless Mac
mini, and unattended-recovery readiness state from current `origin/main` commit
`32146152100477660eaf0ddb10befa8af48ea4fd`. It is prerequisite evidence only;
no macOS logout/login, reboot, headless display run, Android reconnect run, or
window-recovery run was performed.

The default Host readiness command was run without
`--include-login-item-diagnostic`, `--inspect-login-items`,
`--probe-login-item`, or `--probe-login-items`. The retained
`host-readiness.json` records `sfltool_dumpbtm_was_run=false`, and both the
start and end `pgrep -x sfltool || true` checks produced empty output. This
package therefore replaces the older 2026-08-27 record whose command log and
login-item diagnostic output disagreed about whether `sfltool dumpbtm` had been
run.

## Blocking Conditions

- The configured `Vibe Screen Dev` signing identity is not available to this
  user session's keychain lookup, so future rebuild/install evidence cannot be
  tied to a stable signing identity from this environment.
- The installed Host has no source commit/tree provenance from
  `scripts/package_macos.py`; it cannot be treated as the current-source Host.
- Read-only TCC verification was unavailable for both the user and system
  privacy stores, so Screen Recording and Accessibility grants are unverified.
- The installed Host lacks the `com.apple.developer.hid.virtual.device`
  entitlement required by other runtime gates.
- Launch at Login was deliberately not machine-probed on the default path and
  remains `unverified`; no System Settings approval artifact was collected.
- The local Mac model is not a Mac mini, and no dummy/headless or Screen Sharing
  reboot setup was available.
- No client-rendered first frame, bounded unattended recovery log, real window
  restoration artifact, or Android reconnect/render artifact was collected.

## Validation

Commands used are retained in `commands.txt`. Important outcomes:

- `pgrep -x sfltool || true` before readiness: empty output.
- `python3 scripts/macos_dev_host.py readiness ...` exited `2`, the expected
  blocked-readiness result.
- `host-readiness.json` reports `status=blocked`,
  `login_headless_status=blocked`, `can_start_headless_login_gate=false`, and
  `login_headless.login_item.sfltool_dumpbtm_was_run=false`.
- `phase2-macos-startup-recovery-gate` exited `1` with `verdict=blocked` and
  `can_close_login_headless_gate=false`; zero remains reserved for a complete
  pass.
- `phase2-aggregate-owner` exited `0` while keeping `verdict=blocked` and
  `can_close_readme_phase2_gates=false`.
- `pgrep -x sfltool || true` after readiness: empty output.

## Artifacts

- `sfltool-precheck.txt` and `sfltool-postcheck.txt` - empty process checks
  proving no residual `sfltool` process at the start or end of collection.
- `host-readiness.json` - read-only prerequisite snapshot with the explicit
  `sfltool_dumpbtm_was_run=false` login-item field.
- `host-signing-and-permissions.txt` - readable companion report for Host
  signing, source provenance, listener, and TCC readiness.
- `macos-startup-recovery-evidence.json` - passive login/headless evidence input
  recording missing real-machine boundaries.
- `macos-startup-recovery-gate.json` - fail-closed startup/recovery gate summary.
- `phase2-aggregate-owner.json` - Phase 2 aggregate owner report consuming the
  blocked login/headless summary.
- `*-command.txt`, `*-output.txt`, and `*.exit` files - command lines, captured
  output, and exit status for the retained checks.
- `SHA256SUMS` - checksum manifest for retained artifacts.

## Next Pass Requirements

Re-run on the intended Mac mini or approved headless setup after installing a
current-source Host packaged with `scripts/package_macos.py`, making the stable
signing identity available, granting Screen Recording and Accessibility to that
exact Host identity, approving Launch at Login through an explicit attended
diagnostic path, verifying the administrator fallback path, and then collecting
reboot/login launch, client-rendered stream, headless or Screen Sharing
first-frame, bounded recovery, window restoration, and Android reconnect
evidence.
