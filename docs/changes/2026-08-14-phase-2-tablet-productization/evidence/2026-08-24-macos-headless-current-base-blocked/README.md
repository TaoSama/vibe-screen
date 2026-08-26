# 2026-08-24 macOS headless current-base blocked evidence

This record exercises the Phase 2 login-startup/headless Mac mini owner gate on
current-base commit `32798e81bbb84e2155905a8e08ea7cc7c1ff8e46`. It is blocked
readiness evidence only. No rebootable headless Mac mini, stable identity-signed
Host with retained TCC grants, approved Login Item, dummy/headless or Screen
Sharing display setup, client-rendered first frame, unattended recovery run, or
real window restoration artifact was available in this task.

Generated artifacts:

- `macos-startup-recovery-evidence.json` records the missing prerequisites.
- `macos-startup-recovery-gate.json` reports `verdict=blocked`,
  `can_close_login_headless_gate=false`, and
  `can_claim_headless_mac_mini_operation=false`.
- `phase2-aggregate-owner.json` consumes the blocked login/headless summary and
  keeps the README Phase 2 aggregate verdict blocked.

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.macos_startup_recovery_gate \
  --evidence docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-macos-headless-current-base-blocked/macos-startup-recovery-evidence.json \
  --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-macos-headless-current-base-blocked/macos-startup-recovery-gate.json
```

The command is expected to exit nonzero for this record because the evidence is
blocked. A future pass must be collected on the intended Mac hardware after
granting Screen Recording and Accessibility, approving the Login Item, rebooting
or logging out/in, proving automatic startup to a rendered client stream,
recording a capturable physical/dummy/headless or Screen Sharing display,
forcing bounded unattended recovery, restoring a real moved window, and retaining
the administrator intervention path for FileVault, first-login, TCC, and display
failures.
