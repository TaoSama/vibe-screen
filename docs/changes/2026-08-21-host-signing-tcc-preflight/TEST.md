# Host signing and TCC preflight

Status: current-base readiness tooling added; runtime gates still open
Date: 2026-08-25

## Goal

Provide one source-bound, read-only Host readiness artifact that downstream
LAN stream/reconnect, Host RSS, native-pointer, stylus, physical-keyboard,
controller runtime, login/headless, and macOS compatibility runs can consume
before starting evidence-grade runtime work.

## Current-base result

The readiness command records the installed Host bundle identity, codesign
metadata, embedded source commit/tree/dirty state, current checkout
commit/tree/dirty state, Screen Recording and Accessibility TCC rows, TCP
`54321` listener observation, and the virtual HID entitlement state in
`host-readiness.json`. It writes a companion
`host-signing-and-permissions.txt` text report and exits non-zero when any
prerequisite is missing.

The 2026-08-25 current-base local run remained blocked before any LAN,
reconnect, controller, Host RSS, or HID runtime evidence. The retained blocked
record is under
[`evidence/2026-08-25-current-base-host-readiness-blocked`](evidence/2026-08-25-current-base-host-readiness-blocked/README.md).

## Verification

The focused implementation checks for this change are:

```bash
python3 -m py_compile scripts/macos_dev_host.py scripts/tests/test_macos_dev_host.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_macos_dev_host -v
make baseline-macos-host-readiness EVIDENCE_DIR=.build/evidence/host-readiness-current-base-clean
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_trusted_lan_preflight tools.tests.test_controller_runtime -v
git diff --check
```

The Host readiness command is expected to exit `2` when the local machine lacks
the configured signing identity, installed source-bound Host, TCC grants,
listener, or virtual HID entitlement. That blocked output is valid readiness
evidence only; it does not close README-facing runtime gates.

## Open gates

- Real trusted-LAN stream and trusted-LAN reconnect on a current-source Host.
- Controller runtime acceptance with a physical Android controller, approved
  virtual HID entitlement, Host injection evidence, Mac-side observer output,
  and neutral release on disconnect.
- Host RSS no-growth, native-pointer HID, stylus, login/headless, and macOS
  compatibility runtime acceptance.
