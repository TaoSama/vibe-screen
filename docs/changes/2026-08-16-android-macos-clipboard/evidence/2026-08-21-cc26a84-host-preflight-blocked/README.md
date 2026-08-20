# Clipboard E2E Host Preflight Blocked

Date: 2026-08-20 UTC / 2026-08-21 Asia/Shanghai
Branch: codex/android-clipboard-e2e-evidence
Source head at preflight: 8b70fa3e2b58ffa7f06b175147ccf6ff2e315ce7
Baseline: origin/main at cc26a84c829016fa61c721f73a128284fdf64f92
Scope: Android ClipboardManager <-> macOS NSPasteboard Protocol v1 device E2E
Verdict: blocked before Host launch; E2E gate remains open

## Context

PR #157 was rebased after origin/main advanced to
cc26a84c829016fa61c721f73a128284fdf64f92. The P0110 device was online and the
Android device lock was absent, but the runbook requires a current-branch,
stable-signed Host with macOS Screen Recording and Accessibility permissions
before starting a clipboard E2E session.

## Blocker

The Host preflight failed before any Host listener, ADB reverse, app launch, or
clipboard transfer attempt:

```text
codesign identity 'Vibe Screen Dev' not found in the keychain. Create the
'Vibe Screen Dev' self-signed identity (or set $VIBE_SCREEN_SIGN_IDENTITY to an
existing identity), or pass '--sign-identity -' for an ad-hoc build. Ad-hoc
signing changes the code-signing hash on every rebuild and invalidates macOS
Screen Recording/Accessibility grants.
exit_code=1
```

Using ad-hoc signing would change the code-signing hash and would not preserve
the permission state required for evidence-grade macOS NSPasteboard and input
validation, so the E2E run stopped here.

## Commands

See [commands.txt](commands.txt).
The raw Host preflight output is retained in [host-preflight.txt](host-preflight.txt).

## Gate Status

The Android ClipboardManager <-> macOS NSPasteboard E2E gate remains open. This
record does not prove Protocol v1 clipboard negotiation, Android -> Mac
transfer, Mac -> Android transfer, or real macOS NSPasteboard writes/reads.
