# Android UI/UX current-base audit

Date: 2026-08-30
Source branch: `codex/android-ui-ux-current-base-subagent`
Base: origin/main at `757e5ccae`
Scope: offline Android client UI/UX and README consistency audit only. No
device run, Host signing/TCC, stream, or acceptance gate is claimed.

## Finding and fix

The root `README.md` Target Architecture Clients section said the Android client
uses Kotlin, Compose, and MediaCodec. The current Android client builds with
Kotlin, XML Views/ViewBinding, and MediaCodec; `app/build.gradle.kts` has no
Compose dependency and the main source has no Compose UI implementation.

Updated the README to describe the current Android UI stack accurately while
keeping Compose as the target direction, and added a static consistency test at
`tests/phase3/test_android_ui_docs_consistency.py` so the README cannot silently
drift back to presenting Compose as current until the client actually adopts it.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/phase3/test_android_ui_docs_consistency.py -v`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/phase3/test_android_ui_docs_consistency.py tests/phase3/test_internet_preview_copy.py tests/phase3/test_authority_production_gates.py -v`
- `git diff --check`

All focused tests passed.

## Open gates

This record does not close any device UI gate. Android real-device UI paths,
Host readiness, actionable-error current-base closure, native HID, stylus,
controller, trusted-LAN, Internet, and tablet acceptance remain governed by
their existing owner records.
