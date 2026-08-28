# 2026-08-27 macOS Host compatibility readiness blocked

## Scope

This package records a fail-closed readiness pass for the macOS Host
compatibility matrix owner on current `origin/main`. It covers only one local
Host environment: Apple silicon Mac16,8 / Apple M4 Pro on macOS 26.4.1 build
25E253 with a built-in display plus one external display detected by
`system_profiler`.

No Android runtime probe was started for this record. If a later general
Android helper run is needed, the allowed substitute identity remains
`nubia P0110 / pacific / Android 16 / SDK 36`, and every device command must use
the explicit `adb -s ...` target without relabeling the evidence as Xiaomi/fuxi.

## Commands

```bash
git fetch origin --prune
git worktree add --detach \
  .claude/worktrees/macos-host-compat-readiness-clean origin/main
cd .claude/worktrees/macos-host-compat-readiness-clean
make baseline-macos-host-readiness \
  EVIDENCE_DIR=.build/evidence/macos-host-compatibility-readiness-2026-08-27-clean
# Return to the repository root so the evidence package path resolves
# to the committed tree, not the detached worktree.
cd ../..
# Copy the retained readiness artifacts into this evidence package, then run:
make macos-hardware-compatibility-gate \
  EVIDENCE_DIR=docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-27-macos-host-compatibility-readiness-blocked
```

Before the safety follow-up validation, `pgrep -x sfltool` returned no process
IDs. The default readiness path now skips the Launch at Login `sfltool dumpbtm`
probe to avoid macOS administrator prompts in tests and CI. The real login-item
probe is reserved for the explicit `--include-login-item-diagnostic` manual diagnostic path.

The readiness command exited `2`. The compatibility gate writes
`macos-hardware-compatibility-gate.json` and exits non-zero because the row is
blocked.

## Result

`host-readiness.json` reports:

- `status=blocked`
- `signing_tcc_status=blocked`
- `listener_status=blocked`
- `virtual_hid_status=blocked`
- `login_headless_status=blocked`
- every `can_start_*` runtime gate flag is `false`

The retained compatibility summary reports `verdict=blocked` and
`can_close_macos_host_compatibility_row=false`.

Observed blockers:

- The configured stable `Vibe Screen Dev` signing identity was not available to
  the current keychain lookup for rebuild/install readiness.
- The installed `/Applications/Vibe Screen.app` has the expected bundle id and a
  non-ad-hoc identity, but it lacks embedded source commit/tree provenance.
- Screen Recording and Accessibility authorization could not be verified from
  read-only privacy evidence.
- The Host listener was not observed on TCP port 54321.
- The installed Host bundle does not expose the virtual HID entitlement.
- Login/headless readiness is blocked because Launch at Login is unverified.

## Boundaries

This record cannot close the macOS Host compatibility matrix. It does not prove
Intel Mac support, the macOS 13+ range, additional Apple silicon model families,
dummy/headless operation, Screen Sharing, other display topologies, packaged
Host launch, Protocol v1 stream, display selection, input smoke, reconnect, Host
RSS, native-pointer HID, stylus, controller, or trusted-LAN behavior.

The evidence package intentionally keeps local privacy-store paths, local user
paths, Android serials, and secret material out of public artifacts.
