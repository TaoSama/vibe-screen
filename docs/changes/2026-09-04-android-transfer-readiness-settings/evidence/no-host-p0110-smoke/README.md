# Android transfer-readiness Settings no-Host smoke

Date: 2026-09-04

Device: Nubia P0110 / pacific, Android 16 / SDK 36. USB serial is redacted as
REDACTED_P0110_USB_SERIAL.

Scope: Android client UI smoke only. The macOS Host was not started, no product
MacHost binary was launched, no Host self-test was run, and no macOS Screen
Recording, Accessibility, TCC, signing, Keychain, or System Settings state was
touched.

Transport boundary: adb reverse --list already contained UsbFfs tcp:54321
tcp:54321 and UsbFfs tcp:8908 tcp:8908 before this smoke run. The captured
command list contains no adb reverse add, remove, or remove-all command. The
local Mac had no listener on TCP port 54321 during the capture.

Build under test:

- baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
- Installed with adb install -r on the connected Android device.
- Launched with am start -n dev.telemachus.display/.MainActivity --ez auto_connect false.

Evidence:

- device-info.txt records the redacted P0110 identity, Android version, screen
  size, and density.
- logs/adb-reverse-before.txt records the pre-run reverse entries observed
  before the smoke.
- logs/host-port-54321-listeners.txt records that lsof -nP -iTCP:54321
  -sTCP:LISTEN produced no output, proving no local Mac process was listening on
  TCP port 54321 when checked.
- screenshots/screen-01-initial-usb-disconnected.png captures the no-Host USB
  disconnected state.
- screenshots/screen-02-settings-transfer-readiness.png captures the Settings
  dialog with Clipboard & files visible on the first screen and the status
  Waiting for a compatible Mac session.
- ui-dumps/ui-hierarchy-02-settings.xml contains Clipboard &amp; files, Waiting for
  a compatible Mac session, and the Protocol v1 capability summary while the
  dialog is open.
- logs/app-diag-redacted.log is copied from the app-private diagnostic log and
  keeps only Vibe Screen diagnostic lines.

Result:

- PASS: The Settings dialog surfaces transfer readiness without requiring a Host
  session.
- PASS: The no-Host copy says the controls appear only after a compatible
  Protocol v1 Mac session negotiates the capabilities.
- PASS: The capture preserves device identity as Nubia P0110 / pacific and does
  not relabel the evidence as another Android device.

Not proven by this evidence:

- Real macOS Host readiness or stream establishment.
- Protocol v1 handshake with a real Host.
- Android ClipboardManager <-> macOS NSPasteboard transfer.
- Android <-> macOS file-transfer bytes, digest validation, or filesystem
  landing behavior.
- LAN, Internet, reconnect, video, decoder, or Phase 0 aggregate release gates.
