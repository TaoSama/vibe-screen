# Android transfer-readiness Settings

Date: 2026-09-04

This change adds a read-only Clipboard & files readiness section to the Android
Settings dialog. The section reports whether the current session has exposed
clipboard and file-transfer controls, including waiting, unavailable, partial,
and ready states.

Implementation notes:

- TransferReadinessPresentationPolicy maps connection and negotiated transfer
  capability state to Settings copy and status color resources.
- MainActivity renders the Settings block from the existing
  ProductSessionCoordinator.renderState() plus read-only Internet file-transfer
  availability.
- Opening Settings does not read Android ClipboardManager, does not launch the
  Android file picker, and does not send transfer commands.
- The new block is placed after device health and before viewport controls so it
  is visible on the first Settings screen on the P0110 smoke device.

Evidence:

- evidence/no-host-p0110-smoke/ records a no-Host Android UI smoke on Nubia
  P0110 / pacific / Android 16 / SDK 36.
- The smoke did not start the macOS Host and did not create, remove, or modify
  adb reverse entries.
- The captured Settings screenshot and UI dump show Clipboard & files, Waiting
  for a compatible Mac session, and the Protocol v1 capability copy.

Verification:

- ./gradlew --no-daemon :app:testDebugUnitTest
- ./gradlew --no-daemon :app:lintDebug
- ./gradlew --no-daemon :app:assembleDebug
- make baseline-android-check
- git diff --check
- shasum -a 256 -c evidence/no-host-p0110-smoke/SHA256SUMS

Not proven by this change or evidence:

- Real macOS Host readiness or stream establishment.
- Protocol v1 handshake with a real Host.
- Android ClipboardManager <-> macOS NSPasteboard transfer.
- Android <-> macOS file-transfer bytes, digest validation, or filesystem
  landing behavior.
- LAN, Internet, reconnect, video, decoder, or Phase 0 aggregate release gates.
