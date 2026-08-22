# 2026-08-21 login/headless readiness preflight - blocked

This is a read-only macOS Host readiness snapshot for the login startup,
headless Mac mini, and unattended recovery gates. It does not use an Android
device, does not reboot the Mac, does not launch or stop Vibe Screen, and does
not modify TCC, Keychain, login items, or user defaults.

## Result

login-headless-readiness.json reported result: blocked.

The installed /Applications/Vibe Screen.app was stable-signed as
dev.telemachus.display. The read-only TCC check timed out while reading both
the user and system TCC databases in this shell, so Screen Recording and
Accessibility were not verified by this snapshot. Startup defaults were
readable with automatic streaming enabled, startupMode=usb,
displaySource=selectedDisplay, and onboarding already completed.

The snapshot still blocked readiness because TCC could not be verified,
`sfltool dumpbtm` did not return within the 15 second diagnostic timeout, so
Launch at Login could not be verified as enabled or approved, and no active
CoreGraphics display was visible to the diagnostic subprocess.

The direct CoreGraphics display probe returned zero active displays in its
subprocess, then the diagnostic fallback recorded two attached displays through
`system_profiler`. That fallback is useful setup inventory only; it does not
prove that ScreenCaptureKit can capture a physical, dummy, headless, or Screen
Sharing display after login or reboot.

Recent Host log markers show auto-start was deferred until onboarding and
Screen Recording were complete. That marker is useful blocker diagnostics only:
this run did not deliberately force a fresh listener/capture/display failure
under controlled acceptance conditions, and it did not prove successful
unattended recovery.

## Commands

The source worktree was rebased onto origin/main at
22da26816465257b4a09f95de47be8567e448b74 before regenerating this evidence
package.

    git fetch origin --prune
    git rebase origin/main
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_macos_dev_host -v
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v
    python3 -m compileall -q scripts/macos_dev_host.py scripts/tests/test_macos_dev_host.py
    python3 scripts/macos_dev_host.py readiness \
      --report docs/changes/2026-08-05-phase-1-macos-host/evidence/2026-08-21-login-headless-readiness-blocked/login-headless-readiness.txt \
      --json-report docs/changes/2026-08-05-phase-1-macos-host/evidence/2026-08-21-login-headless-readiness-blocked/login-headless-readiness.json
    make baseline-macos-startup-readiness
    python3 -m json.tool docs/changes/2026-08-05-phase-1-macos-host/evidence/2026-08-21-login-headless-readiness-blocked/login-headless-readiness.json >/dev/null
    shasum -a 256 -c docs/changes/2026-08-05-phase-1-macos-host/evidence/2026-08-21-login-headless-readiness-blocked/SHA256SUMS
    make baseline-macos-self-test
    git diff --check origin/main...HEAD

The readiness command exited 2, which is the expected fail-closed code for a
blocked readiness snapshot.

## Artifacts

- login-headless-readiness.json: machine-readable readiness/blocker payload.
- login-headless-readiness.txt: human-readable readiness/blocker report.
- commands.txt: command log for this evidence package.
- SHA256SUMS: artifact checksums.

## Gates not closed

This evidence does not close login startup, headless Mac mini reboot, automatic
startup integration, or unattended listener/capture/display recovery. Those
still require a real macOS login or reboot pass, confirmed Login Items approval,
a usable headless/dummy/physical/Screen Sharing display inventory, and a
controlled unattended failure/recovery log showing either successful restart or
bounded exhaustion.
