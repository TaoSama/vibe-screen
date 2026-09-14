# 2026-09-15 Nubia P0110 no-Host MediaStore Downloads runtime smoke

This package records a focused Android-local runtime check of the production
incoming-file Downloads saver at source commit
`4d258122b5e58f88e1a83d35b0aa0e330bc7e962`. The device was a nubia P0110 /
pacific running Android 16 / SDK 36. Its ADB serial is redacted.

## Result

Both focused instrumentation methods passed on the physical device:

- `productionSaverPublishesIncomingFileToMediaStoreDownloads` inserted a
  pending `MediaStore.Downloads` row through the same saver used by
  `MainActivity`, copied a synthetic payload, published it with
  `IS_PENDING=0`, read it back, verified exact bytes and SHA-256, and removed
  the test row.
- `failedMediaStorePublishDeletesInsertedEntryAndKeepsStagingForCallerCleanup`
  injected an output-open failure after a real row insertion, verified the
  production saver deleted that row, and confirmed the private staging file
  remained owned by the caller for `onIncomingFileCompleted` cleanup.

The retained raw stream contains paired start/pass records for 2 tests,
`OK (2 tests)`, and `INSTRUMENTATION_CODE: -1`. The JUnit report records
`tests=2`, `failures=0`, `errors=0`, and `skipped=0`.

## Boundary

- No macOS Host was started.
- No Screen Recording, Accessibility, Microphone, or other macOS TCC
  permission was requested or modified.
- No `tcp:54321` ADB reverse mapping or local listener existed before or
  after the accepted run.
- Device work was serialized with `/tmp/vibe-screen-device-android.lock`.
- The first attempt exposed Android MIME normalization for a synthetic vendor
  MIME type. The accepted rerun uses the stable `text/plain` plus `.txt`
  pair and is the only run represented by the retained test artifacts.

## Limits

This proves only the Android-local `MediaStore.Downloads` publication and
failure-cleanup system boundary. It does not exercise a macOS Host, Protocol v1
transport, sender selection, receiver approval, chunks, bidirectional bytes
landing, or cancel/disconnect cleanup. The Android/macOS file-transfer product
E2E gate and Phase 0 stable-release aggregate remain blocked.

## Retained files

- `android-test-results/TEST-P0110-16-app.xml`
- `android-test-results/test-results.log`
- `metadata/source-provenance.txt`
- `metadata/device-identity.txt`
- `logs/no-host-boundary.txt`
- `verification.txt`
- `SHA256SUMS`
