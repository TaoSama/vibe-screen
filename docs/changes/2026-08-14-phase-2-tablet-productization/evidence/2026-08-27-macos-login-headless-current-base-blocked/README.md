# 2026-08-27 macOS Login/Headless Current-Base Blocked Evidence

Result: blocked. This package records the current origin/main login-startup
and headless Mac mini readiness state for source commit
3b2ba11e832a3618eaedfc67f92414b161423a00. It is prerequisite evidence only;
no macOS logout/login, reboot, headless display run, Android reconnect run, or
window-recovery run was performed.

The read-only Host readiness preflight observed a local Vibe Screen listener on
TCP 54321, completed onboarding defaults, automatic startup enabled, USB
startup mode, and two online displays via the system_profiler fallback. The run
still failed closed because the machine and installed Host do not satisfy the
acceptance prerequisites.

## Blocking Conditions

- The configured Vibe Screen Dev signing identity is not available to this user
  session's keychain lookup, so future rebuild/install evidence cannot be tied
  to a stable signing identity from this environment.
- The installed Host has no source commit/tree provenance from
  scripts/package_macos.py; it cannot be treated as the current-source Host.
- Read-only TCC verification was unavailable for both the user and system
  privacy stores, so Screen Recording and Accessibility grants are unverified.
- The installed Host lacks the com.apple.developer.hid.virtual.device
  entitlement required by other runtime gates.
- Launch at Login could not be machine-verified because sfltool dumpbtm timed
  out; no System Settings approval artifact was collected.
- The local Mac model is not a Mac mini, and no dummy/headless or Screen Sharing
  reboot setup was available.
- No client-rendered first frame, bounded unattended recovery log, real window
  restoration artifact, or Android reconnect/render artifact was collected.

## Validation

Commands used:

    python3 scripts/macos_dev_host.py readiness --source-root ../../.. --report .build/evidence/login-headless-current-base-main-clean-2026-08-27/host-signing-and-permissions.txt --json-output .build/evidence/login-headless-current-base-main-clean-2026-08-27/host-readiness.json --port 54321
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.macos_startup_recovery_gate --evidence docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-evidence.json --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json
    make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked PHASE2_LOGIN_HEADLESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json

The readiness command exits 2 for the blocked Host prerequisites. The startup
recovery gate exits 1 for this package because verdict=blocked; zero is
reserved for a complete pass. The Phase 2 aggregate command exits 0 but keeps
verdict=blocked and can_close_readme_phase2_gates=false.

## Artifacts

- host-readiness.json - read-only prerequisite snapshot with local paths and
  user names redacted by the tooling.
- host-signing-and-permissions.txt - readable companion report for Host signing,
  source provenance, listener, and TCC readiness.
- macos-startup-recovery-evidence.json - passive login/headless evidence input
  recording the missing real-machine boundaries.
- macos-startup-recovery-gate.json - fail-closed startup/recovery gate summary.
- phase2-aggregate-owner.json - Phase 2 aggregate owner report consuming the
  blocked login/headless summary.
- commands.txt - commands used to collect and evaluate this package.
- SHA256SUMS - checksum manifest for retained artifacts.

## Next Pass Requirements

Re-run on the intended Mac mini or approved headless setup after installing a
current-source Host packaged with scripts/package_macos.py, making the stable
signing identity available, granting Screen Recording and Accessibility to that
exact Host identity, approving Launch at Login, verifying the administrator
fallback path, and then collecting reboot/login launch, client-rendered stream,
headless or Screen Sharing first-frame, bounded recovery, window restoration,
and Android reconnect evidence.
