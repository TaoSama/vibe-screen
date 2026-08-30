# Nubia P0110 Internet Dialog Layout Evidence

## Scope

This focused Android instrumentation pass covers the Internet preview pairing
completion and session-profile import dialogs after the UI polish change. It
checks small-phone layouts, large text, readable signed request content, secure
input attributes, and scroll reachability for the acceptance field.

This evidence is limited to dialog layout and input-safety behavior. It does not
prove real Internet pairing, WebRTC transport, public Internet traversal, TURN
relay behavior, macOS ScreenCaptureKit capture, streaming media, reconnect soak,
or any README acceptance gate.

## Device

- Serial: `<redacted-adb-serial>`
- Manufacturer/model: `nubia P0110`
- Codename: `pacific`
- Android: `16`, API `36`

Nubia P0110/pacific is recorded only as a general Android substitute for this
focused UI run. It is not Xiaomi 13/fuxi evidence.

## Command

```bash
cd baseline/AndroidClient
ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest
```

The device was used under an exclusive `/tmp/vibe-screen-device-android.lock`
directory lock for the focused run.

## Result

```text
Starting 2 tests on P0110 - 16
Finished 2 tests on P0110 - 16
BUILD SUCCESSFUL
```

Gradle also wrote the connected-test result XML at:

```text
baseline/AndroidClient/app/build/outputs/androidTest-results/connected/debug/TEST-P0110 - 16-_app-.xml
```

That XML reported `tests=2` and `failures=0`.

## Screenshot Status

The test attempts best-effort layout evidence capture, but PNG artifacts were
not pulled from the device in this run. The retained artifact for this change is
therefore the focused instrumentation result, not a visual screenshot package.
The failed pull is recorded in `adb-pull-dialog-evidence.txt`.
