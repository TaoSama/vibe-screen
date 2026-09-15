# Nubia P0110 Internet empty-state revoke action

Date: 2026-09-15

This no-Host Android run verifies that the Internet empty state does not expose
the destructive Revoke Mac action until a pairing or pairing-only repair record
exists. The source base was current origin/main commit
a51759a2f9f03ba0efb57824d24eda0be37fc760 (PR #791).

## Result

- With no Internet pairing profile or verified pairing, Revoke Mac is gone
  rather than disabled. It cannot receive focus or consume secondary-action
  layout space.
- Display Settings reflows to the available full action width in portrait.
- The landscape two-column layout remains readable without overlap or clipping.
- The product acceptance test exercised two real AndroidKeyStore-backed pairing
  and local-revoke cycles. Revoke Mac appeared after each pairing and
  disappeared after each revoke, including cleanup of the test credentials.
- The selected no-Host UI/UX suite passed 137/137 on the same P0110 with zero
  failures, errors, or skipped tests.
- The no-Host boundary remained intact before and after the run: no TCP 54321
  ADB reverse mapping and no local listener on TCP 54321.

## Source change

MainActivity.refreshInternetProfileUi derives one canRevokePairing decision
from either a current public profile or hasVerifiedPairing. That same decision
controls visibility and enabled state, preserving the pairing-only repair path
while removing the unavailable action from the true empty state. The existing
responsive connection-panel layout is reapplied after the visibility change.

The focused JVM contract protects those invariants. Product acceptance verifies
the actual empty, paired, revoked, repaired, and revoked-again UI transitions.

## Device

    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    fingerprint=nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys
    wm_size=1264x2800
    wm_density=560
    font_scale=1.0

This is Nubia P0110 / pacific evidence only. It must not be reported as Xiaomi
13 / fuxi evidence.

## Verification

The focused JVM test and AndroidTest compile passed. The connected run selected
the following 12 classes:

    ConnectionGuidanceLayoutInstrumentedTest (35)
    SettingsDialogLayoutInstrumentedTest (30)
    ConnectionStateAccessibilityInstrumentedTest (18)
    ControlBarLayoutInstrumentedTest (17)
    QRScannerLayoutInstrumentedTest (10)
    InternetPairingDialogLayoutInstrumentedTest (8)
    FileTransferOfferDialogLayoutInstrumentedTest (7)
    ClipboardConfirmationDialogLayoutInstrumentedTest (5)
    TrustedNetworkDialogLayoutInstrumentedTest (3)
    InternetControlStateColorsInstrumentedTest (2)
    GestureShortcutPreferencesInstrumentedTest (1)
    InternetMainActivityAcceptanceInstrumentedTest (1)

Total: 137 tests. The retained JUnit XML records 137 tests with zero failures,
errors, or skipped tests. The Gradle runner records BUILD SUCCESSFUL in 2m 14s.

## Screenshots

- screenshots/internet-empty-portrait.png (1264x2800)
- screenshots/internet-empty-landscape.png (2800x1264)

Both screenshots show the no-profile Internet state after the production app
was installed and launched. No Camera, Screen Recording, Accessibility, or
Microphone permission was granted for this capture.

## Boundary

No macOS Host was started. This run did not request macOS Screen Recording,
Accessibility, or Microphone permission and did not create an ADB reverse
mapping. It does not prove QR decoding, production Authority issuance, public
Internet direct or TURN traversal, Host-backed display capture, Android
MediaCodec output, Internet audio or bulk transfer, cross-service revocation,
soak stability, or any iOS acceptance.

Verify retained artifacts with shasum -a 256 -c SHA256SUMS from this directory.
