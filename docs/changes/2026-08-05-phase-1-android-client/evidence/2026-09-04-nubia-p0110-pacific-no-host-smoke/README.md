# Nubia P0110 no-Host Android smoke

Date: 2026-09-04

Source base: `origin/main` at `3ab85697e17aef0e57549e1d47298c9eb831941d`

Device: nubia P0110 / pacific / Android 16 / SDK 36 / `REDACTED_P0110_USB_SERIAL`

Scope: Android client only. This run did not start Vibe Screen/MacHost, did not
run `swift run`, did not create `adb reverse`, did not inspect or mutate TCC, did
not use Keychain, and did not validate any macOS Host-backed E2E gate. The
record is a no-Host UI/UX smoke for the disconnected Android client.

## Commands

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:assembleDebug :app:testDebugUnitTest

adb -s REDACTED_P0110_USB_SERIAL install -r app/build/outputs/apk/debug/app-debug.apk
adb -s REDACTED_P0110_USB_SERIAL logcat -c
adb -s REDACTED_P0110_USB_SERIAL shell am start -n dev.telemachus.display/.MainActivity
adb -s REDACTED_P0110_USB_SERIAL exec-out screencap -p > android-no-host-final.png
adb -s REDACTED_P0110_USB_SERIAL shell input tap 630 1130
adb -s REDACTED_P0110_USB_SERIAL exec-out screencap -p > android-no-host-lan-tab.png
adb -s REDACTED_P0110_USB_SERIAL shell uiautomator dump /sdcard/window.xml
adb -s REDACTED_P0110_USB_SERIAL exec-out cat /sdcard/window.xml > ui-hierarchy-lan.xml
adb -s REDACTED_P0110_USB_SERIAL shell input tap 920 1130
adb -s REDACTED_P0110_USB_SERIAL exec-out screencap -p > android-no-host-internet-tab.png
adb -s REDACTED_P0110_USB_SERIAL shell uiautomator dump /sdcard/window.xml
adb -s REDACTED_P0110_USB_SERIAL exec-out cat /sdcard/window.xml > ui-hierarchy-internet.xml
adb -s REDACTED_P0110_USB_SERIAL logcat -d -v time --pid=$(cat app-pid-final.txt) > android-final-pid-logcat.log
shasum -a 256 android-no-host-final.png android-no-host-lan-tab.png android-no-host-internet-tab.png
```

USB-screen `uiautomator dump` returned `ERROR: could not get idle state.` on
this device and did not write `/sdcard/window.xml`, so the USB failure state is
retained as a screenshot artifact rather than a hierarchy artifact.

## Result

- `android-no-host-initial.png` captured the pre-fix USB failure state: the
  inline error said `Mac app unavailable`, while the checklist still said
  `Mac server · Checking`.
- `android-no-host-final.png` captures the fixed USB failure state: the inline
  error remains visible and the checklist now says `Mac server · Not ready`.
- `android-no-host-lan-tab.png` and `android-no-host-internet-tab.png` capture
  safe mode switching without a Host; their checksums differ, and the retained
  UI hierarchy confirms LAN and Internet tab selection. The screenshot SHA-256
  values are:
  - `android-no-host-final.png`: `fa7152f90b36bd1c6f891872662870d2784e75b039348aa95054b707c08d2fa5`
  - `android-no-host-lan-tab.png`: `88ae9597cc785a68b4b2d12778310f649182e8adf8bcba47c1715bf4d1a59662`
  - `android-no-host-internet-tab.png`: `a326c828e36e4a3cf556346182f97e08bbb128fda272dfa2edf082ecc2731744`
- `ui-hierarchy-lan.xml` shows `LAN` checked, and
  `ui-hierarchy-internet.xml` shows `Internet` checked.
- `window-focus-final.txt` and `window-focus-mode-toggle.txt` show
  `dev.telemachus.display/.MainActivity` remained focused.
- `android-final-pid-logcat.log` is filtered to the app PID and contains no
  crash, ANR, `AndroidRuntime` fatal exception, `IllegalStateException`, or
  `NullPointerException` entries.

This evidence does not close USB/LAN/Internet Host runtime gates because no
Host, transport route, capture, decoder stream, input injection, or macOS
permission state was exercised.
