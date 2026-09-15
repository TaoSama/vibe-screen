# Nubia P0110 no-Host ACTION_SEND_MULTIPLE single-file share smoke after PR #797

Date: 2026-09-15

Source base: `d3c11b6ca141c4fb5340970f3b7f477a88fc546b`

Device identity:

- Manufacturer/model: Nubia P0110
- Codename: pacific
- Android: 16
- SDK: 36
- Device serial observed by the runner: `EP0110PZ0B9110152B`

Command:

```bash
./gradlew :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ShareFileIntentInstrumentedTest
```

Result summary:

```text
Starting 7 tests on P0110 - 16
Finished 7 tests on P0110 - 16
BUILD SUCCESSFUL in 14s
```

Retained artifact:

- [android-test-results/TEST-P0110-16-app.xml](android-test-results/TEST-P0110-16-app.xml)
- [logs/no-host-preflight-before.txt](logs/no-host-preflight-before.txt)
- [logs/connected-share-file-instrumentation.log](logs/connected-share-file-instrumentation.log)
- [logs/no-host-preflight-after.txt](logs/no-host-preflight-after.txt)

The retained XML records `tests="7"`, `failures="0"`, `errors="0"`,
and `skipped="0"` for
`dev.telemachus.display.ShareFileIntentInstrumentedTest`. The seven passing
methods cover the existing single-file `ACTION_SEND` pending path,
single-URI `ClipData`, repeated share handling, `ACTION_SEND_MULTIPLE` with
exactly one `content://` item, `ACTION_SEND_MULTIPLE` with multiple items
rejected before pending state, malformed `ACTION_SEND_MULTIPLE` with a bare
`Uri` `EXTRA_STREAM` rejected before pending state, and package-manager
resolution of the `ACTION_SEND_MULTIPLE` `*/*` share target.

Boundary conditions:

- No macOS Host was started.
- No TCC state was changed.
- No `tcp:54321` adb reverse mapping existed before or after the test.
- No local listener was present on port `54321`.
- The no-Host pending/reject paths did not query provider metadata, open
  provider bytes, or resolve MIME through `ContentResolver`; the test provider
  counters stayed at zero on the covered paths.
- No screenshots, videos, packet logs, Host logs, source/destination byte dumps,
  or SHA-256 transfer equality artifacts are claimed in this evidence.

Gate impact:

This evidence proves Android-local readiness for accepting a single-file
`ACTION_SEND_MULTIPLE` system share as a pending draft while preserving
fail-closed handling for true multi-item shares and no-Host zero-read behavior.
It does not prove Host-backed bytes landing, receiver approval over a real
session, same-session USB/LAN transport, ordered transfer chunks, endpoint
SHA-256 equality, or cancel/disconnect cleanup.

`file_transfer_android_product_e2e=BLOCKED`
`can_close_file_transfer_android_smoke_gate=false`
