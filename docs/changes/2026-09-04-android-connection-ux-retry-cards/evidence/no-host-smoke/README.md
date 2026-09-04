# Android no-Host retry-card smoke

Date: 2026-09-04

Device: Nubia P0110 / pacific, Android 16. USB serial is redacted as
`REDACTED_P0110_USB_SERIAL`.

Scope: Android client UI smoke only. The macOS Host was not started, `adb reverse`
was not configured, and no macOS Screen Recording, Accessibility, TCC, signing,
Keychain, or System Settings state was touched.

Build under test:

- `baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk`
- Installed with `adb install -r` on the connected Android device.
- Launched with `am start -n dev.telemachus.display/.MainActivity --ez auto_connect true`.

Evidence:

- `usb-no-host-retry-card-final.png` shows the USB automatic retry state with
  `Waiting to retry`, `Trying USB again in 1 s.`, an enabled `Retry now` action,
  the inline `Mac app unavailable` guidance card, and the expanded checklist
  showing `Mac server · Not ready`.
- `app-diag-redacted.log` is copied from the app-private `DiagLog` file and keeps
  only Vibe Screen diagnostic lines. It shows repeated retryable
  `TRANSPORT_CLOSED` session endings while no Host listener is available.

Notes:

- `uiautomator dump` for the final retry screen failed with
  `ERROR: could not get idle state`, consistent with the active progress/countdown
  animation on this screen.
- A previous full-device logcat capture was discarded because it contained
  unrelated system and third-party process data. No global logcat is retained in
  this evidence set.
