# Android no-Host transfer UI smoke

Date: 2026-09-04

Device: Nubia P0110 / pacific, Android 16 / SDK 36. USB serial is redacted as
REDACTED_P0110_USB_SERIAL. This is Nubia P0110 substitute-device evidence and
must not be relabeled as Xiaomi 13 / fuxi evidence.

Source base: origin/main at ef443351c6c812fcf55173ff33bd8ec1b09f7b60.

Working directory note: the user checkout had existing uncommitted changes
unrelated to this smoke. To avoid overwriting them, this run used a clean Codex
worktree for the same repository.

## Scope

This is Android client UI/UX smoke evidence only. It covers the post-PR #551,
#552, and #553 no-Host surfaces for USB connection failure/retry, Settings
transfer readiness, and clipboard/file-transfer control visibility without a
capability-negotiated session.

The macOS Host was not started. No product Host binary, swift run, Host
self-test, loopback, Host E2E, Screen Recording, Accessibility, Microphone, TCC,
Keychain, System Settings, signing, or install operation was run.

## Environment Boundary

- logs/adb-reverse-before.txt and logs/adb-reverse-after.txt both show
  pre-existing UsbFfs tcp:54321 tcp:54321 and UsbFfs tcp:8908 tcp:8908.
- No adb reverse add, remove, or remove-all command was run.
- logs/host-port-54321-listeners-before.txt and
  logs/host-port-54321-listeners-after.txt are empty, so no local Mac process
  was observed listening on TCP port 54321 during the checked windows.
- logs/host-processes-before.txt and logs/host-processes-after.txt are empty for
  the Host process-name probe used here.

## Acceptance Items

- PASS: The app installed and launched on the connected Nubia P0110.
- PASS: The auto-connect no-Host retry card screenshot shows Waiting to retry,
  Trying USB again in 1 s., RETRY NOW, Mac app unavailable, and
  Mac server · Not ready.
- PASS: The stable disconnected UI dump shows VIBE SCREEN, Waiting for your Mac,
  USB/LAN/Internet mode controls, CONNECT, and DISPLAY SETTINGS.
- PASS: The Settings screenshot and UI dump show Clipboard & files, Waiting for
  a compatible Mac session, and Clipboard and file controls appear after Protocol
  v1 negotiates those capabilities with the Mac between Sustained use and
  Viewport.
- PASS: logs/no-transfer-controls-grep.txt records no controlClipboardButton,
  controlFileTransferButton, controlBar, ACTION_OPEN_DOCUMENT, DocumentsUI, or
  com.android.documentsui hits in the retained disconnected and Settings UI
  dumps.
- PASS: logs/window-focus-current.txt shows the focused app/window remains
  dev.telemachus.display/.MainActivity.
- PASS: logs/android-final-pid-logcat.log has no FATAL EXCEPTION,
  AndroidRuntime, ANR, or Fatal signal crash marker for the app PID.
- PASS: logs/baseline-android-check.txt records make baseline-android-check
  passing after the evidence capture.

## Evidence Files

- screenshots/screen-01-usb-retry-card.png - no-Host automatic USB retry card.
- screenshots/screen-02-manual-disconnected.png - stable disconnected USB panel
  used for UIAutomator text capture.
- screenshots/screen-03-settings-transfer-readiness.png - Settings transfer
  readiness card.
- ui-dumps/ui-hierarchy-02-manual-disconnected.xml - stable disconnected UI
  hierarchy.
- ui-dumps/ui-hierarchy-03-settings.xml - Settings UI hierarchy.
- logs/uiautomator-01-retry-card.txt - expected retry-card dump failure:
  ERROR: could not get idle state.
- logs/app-diag-redacted.log - app-private diagnostics showing expected retryable
  TRANSPORT_CLOSED lines during no-Host auto-connect.
- logs/baseline-android-check.txt - Gradle Android check output.
- metadata.json, commands.txt, and SHA256SUMS - structured context, command log,
  and artifact integrity.

## Not Proven

- Real macOS Host readiness or stream establishment.
- Protocol v1 handshake with a real Host.
- Android ClipboardManager <-> macOS NSPasteboard transfer.
- Android <-> macOS file-transfer bytes, SHA-256 validation, or filesystem
  landing behavior.
- LAN, Internet, reconnect, video, decoder, Host RSS, controller, native pointer,
  or Phase 0 aggregate release gates.
