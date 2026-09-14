# Nubia P0110 Internet camera permission recovery

Date: 2026-09-15

This no-Host Android run verifies the Internet profile QR scanner permission
recovery flow from source commit `8d526cfc5e13e37f635641273f8241dfb7811250`.
The device was a Nubia P0110 (`pacific`) running Android 16 / API 36.

## Result

- The first Camera denial returned to Vibe Screen and showed inline recovery
  guidance below the Scan QR and Import actions.
- A second denial showed a dedicated panel with a visible 48 dp `Open Settings`
  action. Vibe Screen did not open Android Settings automatically.
- Tapping `Open Settings` opened the Vibe Screen application settings page.
- After Camera was changed from denied to allowed, returning to Vibe Screen
  automatically opened `QRScannerActivity` once.
- Pressing Back from the scanner returned to the Internet screen without
  launching the scanner again, proving the pending return action was consumed.
- Focused device instrumentation passed 1/1 on the same P0110. The no-Host
  boundary remained intact before and after the run: no `tcp:54321` ADB reverse
  mapping and no local listener on TCP 54321.

## Screenshots

- `screenshots/01-first-denial-inline-guidance.png`
- `screenshots/02-permanent-denial-settings-action.png`
- `screenshots/03-explicit-app-settings.png`
- `screenshots/04-authorized-settings-return-scanner.png`

Android blocks camera pixels from ordinary screenshots, so the scanner capture
is black by platform policy. The foreground Activity check recorded
`dev.telemachus.display/.QRScannerActivity`; this record verifies scanner
launch, not QR decoding or Internet pairing.

## Verification

The following checks passed from the source worktree:

    ./gradlew --no-daemon --console=plain :app:testDebugUnitTest \
      --tests dev.telemachus.display.InternetCameraPermissionRecoveryPolicyTest \
      --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest
    ./gradlew --no-daemon --console=plain :app:compileDebugAndroidTestKotlin
    ./gradlew --no-daemon --console=plain :app:lintDebug
    make baseline-android-check
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon --console=plain \
      :app:connectedDebugAndroidTest \
      '-Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest#internetCameraPermissionPanelKeepsRecoveryCopyAndSettingsActionReadable'

The focused device test reported `Finished 1 tests on P0110 - 16` and
`BUILD SUCCESSFUL`. `make baseline-android-check` passed the transport
module checks, full Android JVM suite, lint, debug APK assembly, and release
dependency audit.

## Boundary

No macOS Host was started. This run did not request macOS Screen Recording,
Accessibility, or Microphone permission, did not create an ADB reverse mapping,
and did not prove a real QR decode, pairing profile exchange, public-Internet
transport, or Host-backed stream.

Device and source metadata are retained under `metadata/`. Verify the package
with `shasum -a 256 -c SHA256SUMS` from this directory.
