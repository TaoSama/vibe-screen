# 2026-09-15 Nubia P0110 no-Host outgoing staging runtime smoke

This package records a focused Android-local check of the production outgoing
file stager at source commit `e0ce35b9a`. The device was a nubia P0110 /
pacific running Android 16 / SDK 36. Its ADB serial is intentionally redacted.

## Result

Both focused instrumentation methods passed on the physical device:

- `productionStagerReadsContentUriIntoPrivateBytesMetadataAndCleansUp` created
  a real `MediaStore.Downloads` `content://` source, read it through the
  production `OutgoingFileStager`, and verified the app-private staged bytes,
  display name, MIME type, byte length, SHA-256, and explicit cleanup.
- `oversizeContentUriStagingFailureRemovesPrivateDirectory` verified that an
  over-limit source fails closed and removes its partial private staging
  directory.

The retained JUnit report records `tests=2`, `failures=0`, `errors=0`, and
`skipped=0`. Focused JVM tests additionally verify that a staged file produces
matching `FileOffer` metadata, strictly advancing first/final chunks with the
expected session epoch, and that the UI/session cleanup owner deletes the
staging directory after user cancellation and connection cleanup.

## Boundary

- No macOS Host was started.
- No Screen Recording, Accessibility, Microphone, or other macOS TCC permission
  was requested or modified.
- No `tcp:54321` ADB reverse mapping or local listener existed before or after
  the run.
- Device work was serialized with `/tmp/vibe-screen-device-android.lock.d`;
  the lock was removed and both test packages were uninstalled afterward.
- The device result proves the Android `content://` system boundary and local
  staging cleanup. Offer/chunk/cancel/disconnect assertions are focused JVM
  coverage over the production transfer owner, not a Host-backed device flow.

## Limits

This does not exercise a macOS Host, receiver approval, Protocol v1 transport,
remote destination writes, retained macOS bytes, a shared product session, or
bidirectional transfer. It does not close `file_transfer_android_product_e2e`
or the Phase 0 stable-release aggregate.

## Retained files

- `android-test-results/TEST-P0110-16-app.xml`
- `android-test-results/test-results.log`
- `metadata/source-provenance.txt`
- `metadata/device-identity.txt`
- `logs/no-host-boundary.txt`
- `verification.txt`
- `SHA256SUMS`
