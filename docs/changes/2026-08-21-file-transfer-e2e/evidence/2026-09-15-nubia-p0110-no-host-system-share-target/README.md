# 2026-09-15 Nubia P0110 no-Host system share target

This package records Android system-share entry and pending-draft readiness.
The physical device was a nubia
P0110 / pacific running Android 16 / SDK 36 with build fingerprint
`nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys`. Its ADB
serial is intentionally redacted.

## Result

The Android package manager resolved `dev.telemachus.display/.MainActivity` as
an `ACTION_SEND` single-file share target. A real system `am start` cold
launch keeps the file as a lightweight pending draft. The disconnected panel
shows `1 file ready to send`, explains that a capable Mac session is required,
and offers Cancel. Review stays hidden until a capable session exists. Portrait
and landscape screenshots show no clipping or overlap, and a real Cancel tap
removed the pending panel.

The focused `ShareFileIntentInstrumentedTest` passed 3/3 methods on the same
device. It proves that the no-Host path stores and restores the pending draft
without querying metadata, opening source bytes, or resolving MIME through
`ContentResolver`; it also
proves that a second deliberate share of the same `content://` URI is handled
as a new user action rather than being mistaken for an Activity recreation. A
single URI supplied only through `ClipData` is accepted, and an untrusted
`auto_connect=true` extra on the share intent cannot enable automatic USB.
Focused JVM coverage separately rejects text-only, multiple, malformed, and
non-`content://` shares, fails closed on malformed external extras, refuses an
active-transfer share before reading its URI, and keeps the existing
staged-file preflight and explicit-send confirmation pipeline. Before explicit
review, state retains only the URI, MIME hint, and action token. It does not
query, resolve, stage, or offer the source merely because a session appears.

## Boundary

- No macOS Host was started.
- No Screen Recording, Accessibility, Microphone, or other macOS TCC permission
  was requested or modified.
- No `tcp:54321` ADB reverse mapping or local listener existed before or after
  instrumentation or the system-entry run.
- The Android test package and app package were uninstalled after their
  respective runs, and `/tmp/vibe-screen-device-android.lock.d` was removed.
- The debug-only counting provider is confined to the Android debug source set.

## Limits

This proves Android system-share discovery, cold launch, no-Host pending-draft
guidance, Activity recreation, cancellation, duplicate user-action handling,
and zero source reads without an eligible session. It does not exercise a
file-transfer-capable Host session, the positive preflight action on device,
Protocol v1 transport, receiver
approval, macOS destination writes, endpoint byte equality, progress, or
cancel/disconnect cleanup over a real session.

`file_transfer_android_product_e2e=BLOCKED`. The Phase 0 stable-release
aggregate remains blocked.

## Retained files

- `android-test-results/TEST-P0110-16-app.xml`
- `screenshots/no-host-pending-share-portrait.png`
- `screenshots/no-host-pending-share-landscape.png`
