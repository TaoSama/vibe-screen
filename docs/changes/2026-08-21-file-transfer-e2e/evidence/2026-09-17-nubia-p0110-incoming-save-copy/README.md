# 2026-09-17 Nubia P0110 incoming Save a copy smoke

This package records an Android-local no-Host runtime check of the completed
incoming-file surface and document-copy boundary. The physical device was a
nubia P0110 / pacific running Android 16 / SDK 36. Its ADB serial is redacted.
The accepted run used the pending source diff based on
`d2b3cb6d69c3578e214bc5a818cb088d9b8d5704`; the final merged commit is
recorded by the parent pull request rather than fabricated here.

## Result

The focused physical-device run passed 4/4 instrumentation methods with zero
failures, errors, or skips:

- the production Downloads saver published exact bytes and cleaned up a failed
  pending row;
- the production `IncomingFileDocumentExporter` copied 4,123 bytes between
  real `ContentResolver` URIs with exact-byte and SHA-256 equality;
- the production `MainActivity` rendered the latest completed filename in a
  persistent **Save a copy** panel, restored it after Activity recreation, kept
  both actions enabled with 48 dp minimum touch targets, and removed the panel
  after Dismiss.

The retained 1264 x 2800 screenshot was captured from the recreated production
Activity after its assertions passed. It shows the panel fully visible without
clipping, overlap, or obstruction of the disconnected USB connection flow.

## Boundary

- No macOS Host was started.
- No Screen Recording, Accessibility, Microphone, Camera, or other permission
  was requested or modified.
- The app was absent before the run and Camera app-op lookup returned `No UID`.
- No `tcp:54321` ADB reverse mapping or local listener existed before or after
  the accepted run.
- The system document picker was not clicked in the accepted no-Host run. Its
  launch/result ownership is covered offline; provider copying is covered on
  the physical device.

## Limits

This proves Android-local completion UI, recreation, dismissal, Downloads
publication, and copying between real MediaStore URIs through
`ContentResolver`. It does not prove a system picker or arbitrary
DocumentsProvider destination, nor a Host-origin
file arriving over USB, LAN, or Internet, nor macOS destination bytes,
bidirectional transfer, shared session identity, or cancel/disconnect cleanup
over a real transport. The Android/macOS file-transfer product E2E gate and
Phase 0 stable-release aggregate remain blocked.

## Evidence boundary

- Missing source: no current-source stable-signed TCC-ready macOS Host session;
  Host-backed conclusions are therefore excluded.
- Inferred values: none. Device identity, test count, copied byte count, image
  dimensions, and hashes are direct observations.
- Precision: screenshot layout is one 1264 x 2800 portrait sample; other font
  scales and form factors remain covered by existing layout instrumentation,
  not this image.
- Cross-check: Gradle reported 4 completed tests; retained JUnit XML reports
  `tests=4`, `failures=0`, `errors=0`, `skipped=0`.

## Retained files

- `android-test-results/TEST-P0110-16-app.xml`
- `screenshots/incoming-file-saved-panel.png`
- `SHA256SUMS`
