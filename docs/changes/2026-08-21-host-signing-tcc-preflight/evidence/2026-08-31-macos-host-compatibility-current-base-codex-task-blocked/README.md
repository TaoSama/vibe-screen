# 2026-08-31 macOS Host compatibility current-base blocked (Codex task)

## Scope

This package refreshes the macOS Host compatibility matrix current-base owner
record from clean `origin/main` commit
`28b9d1a59ef026b45ada3cd7e665ef09ea9a7523`. It covers only the local Apple
silicon Mac16,8 / Apple M4 Pro host on macOS 26.4.1 build 25E253 with a
multi-display topology: the built-in Color LCD plus one external DELL U2723QE
display detected by `system_profiler`.

No Android runtime probe was started. The row remains blocked before stream,
input, capture, and reconnect probes because the stable source-bound Host/TCC
prerequisites did not pass.

## Commands

```bash
git fetch origin main
git worktree add -b codex/macos-host-compat-codex-task-20260831 \
  <repo>/.claude/worktrees/macos-host-compat-codex-task-20260831 \
  origin/main
pgrep -x sfltool || true
make baseline-macos-host-readiness EVIDENCE_DIR=.build/evidence/macos-host-compat-codex-task-20260831-clean
make macos-hardware-compatibility-gate \
  EVIDENCE_DIR=docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-31-macos-host-compatibility-current-base-codex-task-blocked
```

The safety check found no `sfltool` process before collection. This run used
the default readiness path and did not execute `/usr/bin/sfltool dumpbtm`; it
also did not pass `--include-login-item-diagnostic`, `--inspect-login-items`,
`--probe-login-item`, or `--probe-login-items`.

`make baseline-macos-host-readiness` exited `2`.
`make macos-hardware-compatibility-gate` wrote
`macos-hardware-compatibility-gate.json` and exited non-zero because the row is
blocked.

## Result

`host-readiness.json` reports:

- `status=blocked`
- `signing_tcc_status=blocked`
- `listener_status=blocked`, with no Host listener observed on TCP port `54321`
- `virtual_hid_status=blocked`
- `login_headless_status=blocked`
- every `can_start_*` runtime gate flag is false

Observed blockers:

- The configured `Vibe Screen Dev` signing identity was not found in the
  keychain lookup used for rebuild/install readiness.
- `codesign` inspection of `/Applications/Vibe Screen.app` failed with sealing
  errors, so installed binary identity, source commit/tree provenance, and
  permitted TCC state could not be recorded for this run.
- Screen Recording and Accessibility authorization could not be verified from
  the read-only TCC evidence path.
- The Host listener was not observed on TCP port `54321`.
- The installed Host does not expose the virtual HID entitlement.
- Login/headless readiness is blocked because Launch at Login remains
  unverified in the default no-`sfltool` path.
- Full Xcode is unavailable because the active developer directory is Command
  Line Tools; automated macOS build/XCTest/self-test provenance cannot be
  retained for this row.

The retained compatibility summary reports `verdict=blocked`,
`invalid_claims=[]`, and `can_close_macos_host_compatibility_row=false`. Its
generated `closure_checklist` keeps the next work fail-closed:
`source_and_host_identity` is blocked by missing stable signing/TCC,
source/self-test provenance, full Xcode/Swift build evidence, and installed
Host identity; `runtime_acceptance` is blocked because no packaged Host launch,
Protocol v1 stream, display-selection, input, or reconnect probe ran;
`display_and_encoder_capability` and `scope_and_artifacts` are satisfied only as
recorded-readiness fields for this blocked package; and `extrapolation_guard`
passes with no invalid support claim.

## Boundaries

This record cannot close the macOS Host compatibility matrix. It does not prove
Intel Mac support, any macOS version range, additional Apple silicon model
families, built-in-only operation, single-external-only operation,
dummy/headless operation, Screen Sharing, packaged Host launch from this
source, capture backend behavior, VideoToolbox runtime encoding, Protocol v1
stream, display selection, input smoke, reconnect, Host RSS, native-pointer
HID, stylus, controller, or trusted-LAN behavior.

The exact next prerequisites are: install or expose the stable `Vibe Screen Dev`
codesign identity; rebuild/package the Host from clean current-base source so
source commit/tree provenance is embedded and the installed app passes strict
codesign inspection; grant and verify Screen Recording and Accessibility for
that exact installed Host identity; retain full Xcode build/test/self-test
output from the same commit; then collect a Host listener/runtime snapshot and
run the real USB or trusted-LAN Android Protocol v1 stream, display, input, and
reconnect probes for this exact row.
