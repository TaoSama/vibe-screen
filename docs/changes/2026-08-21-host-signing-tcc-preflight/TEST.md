# macOS Host signing and TCC preflight

Status: blocked before Host install or device gate
Date: 2026-08-21

## Goal

Give Android/macOS device-gate runs a small, repeatable prerequisite check for
the stable local Host signing identity before attempting to build, install,
launch, or request macOS privacy permissions. This prevents Host/TCC failures
from being mixed into LAN, native pointer, controller, stylus, soak, and touch
rerun evidence.

## Result

The current machine has no valid codesigning identities visible to
`/usr/bin/security find-identity -v -p codesigning`, so the default
`Vibe Screen Dev` identity is unavailable. The new signing-identity preflight
therefore wrote a blocked evidence bundle and exited `2` before any Host install,
Keychain mutation, TCC mutation, or device gate could run.

This blocked prerequisite does not close any README gate. A future device run
must still install a matching stable-signed `/Applications/Vibe Screen.app`,
verify Screen Recording and Accessibility with the Host preflight, and retain
the real Android or iOS device evidence required by the target gate.

Evidence:
[`evidence/2026-08-21-local-signing-identity-blocked/README.md`](evidence/2026-08-21-local-signing-identity-blocked/README.md).

## Verification

```bash
git fetch origin --prune
git rev-parse HEAD origin/main
python3 -m py_compile scripts/macos_signing_identity_preflight.py \
  scripts/tests/test_macos_signing_identity_preflight.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts/tests/test_macos_signing_identity_preflight.py -v
python3 scripts/macos_signing_identity_preflight.py \
  --output-dir docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-21-local-signing-identity-blocked
```

The final command exited `2` with:

```text
blocked: codesign identity 'Vibe Screen Dev' not found in the keychain
```
