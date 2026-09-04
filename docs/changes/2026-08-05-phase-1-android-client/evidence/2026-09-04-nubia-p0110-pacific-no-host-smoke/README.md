# Nubia P0110 no-Host Android smoke

Date: 2026-09-04

Source base: `origin/main` at `3ab85697e17aef0e57549e1d47298c9eb831941d`

Device: nubia P0110 / pacific / Android 16 / SDK 36 / `EP0110PZ0B9110300B`

Scope: Android client only. This run did not start Vibe Screen/MacHost, did not
run `swift run`, did not create `adb reverse`, did not inspect or mutate TCC, did
not use Keychain, and did not validate any macOS Host-backed E2E gate. The
record is a no-Host UI/UX smoke for the disconnected Android client.

## Commands

```bash
cd baseline/AndroidClient
./gradlew --no-daemon :app:assembleDebug :app:testDebugUnitTest

adb -s EP0110PZ0B9110300B install -r app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B logcat -c
adb -s EP0110PZ0B9110300B shell am start -n dev.telemachus.display/.MainActivity
adb -s EP0110PZ0B9110300B exec-out screencap -p > android-no-host-final.png
adb -s EP0110PZ0B9110300B shell input tap 630 1130
adb -s EP0110PZ0B9110300B exec-out screencap -p > android-no-host-lan-tab.png
adb -s EP0110PZ0B9110300B shell input tap 920 1130
adb -s EP0110PZ0B9110300B exec-out screencap -p > android-no-host-internet-tab.png
adb -s EP0110PZ0B9110300B logcat -d -v time --pid=$(cat app-pid-final.txt) > android-final-pid-logcat.log
```

## Result

- `android-no-host-initial.png` captured the pre-fix USB failure state: the
  inline error said `Mac app unavailable`, while the checklist still said
  `Mac server · Checking`.
- `android-no-host-final.png` captures the fixed USB failure state: the inline
  error remains visible and the checklist now says `Mac server · Not ready`.
- `android-no-host-lan-tab.png` and `android-no-host-internet-tab.png` capture
  safe mode switching without a Host.
- `window-focus-final.txt` and `window-focus-mode-toggle.txt` show
  `dev.telemachus.display/.MainActivity` remained focused.
- `android-final-pid-logcat.log` is filtered to the app PID and contains no
  crash, ANR, `AndroidRuntime` fatal exception, `IllegalStateException`, or
  `NullPointerException` entries.

This evidence does not close USB/LAN/Internet Host runtime gates because no
Host, transport route, capture, decoder stream, input injection, or macOS
permission state was exercised.
