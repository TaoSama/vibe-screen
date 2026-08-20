# Nubia P0110 fixed-binary touch-gesture rerun

Date: 2026-08-20 (Asia/Shanghai)

## Result

**PASS for the Nubia P0110/pacific Android substitute.** This run does not
claim Xiaomi 13/fuxi evidence. It verifies that the currently installed
stable-signed Host binary passed the fixed-binary touch rerun preflight, reached
an active Protocol v1 USB stream, and accepted the opt-in Android gesture matrix
through the production touch path.

The run covered the fixed `CGEventSource` modifier-isolation behavior: the
listen-only macOS event tap observed a plain left click with `command=false`
after an earlier completed pinch run, and the rerun's own pinch produced only
the expected Command-modified scroll event.

## Source and identity

- Source base: `b9d768e55c75f03cd3cb5d20939576bc8d24ff27`
  (`origin/main` at the start of the run).
- Android device: nubia P0110, codename `pacific`, serial
  `EP0110PZ0B9110300B`.
- Android version: 16 / API 36.
- Build fingerprint:
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- Host bundle: `/Applications/Vibe Screen.app`.
- Host identifier: `dev.telemachus.display`.
- Fixed Host binary SHA-256:
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`.
- Host signing authorities: `Vibe Screen Dev`, `Vibe Screen Dev Root`.
- Host CDHash: `2fe65fd5cd69c80249140da3f139cfa68037c5c2`.
- Debug APK SHA-256:
  `3f9fb90e66f08e208dd5fd2470b82c18915fd58cae3dfead635cf0c9691f6af6`.
- Test APK SHA-256:
  `e42e1e304722a01e4b6376a1f596d8e09755bc5536e87c4b12b641caa0230dd2`.

## Preflight

`touch-rerun-preflight.json` reported `result: ready` with no blockers. The
expected Host SHA-256 matched the installed binary, and both TCC rows were
authorized for `dev.telemachus.display` from the system TCC database:

```text
kTCCServiceScreenCapture auth_value=2 authorized=true
kTCCServiceAccessibility auth_value=2 authorized=true
```

The preflight also recorded the explicit P0110 device identity.

## Gesture evidence

`touch-gesture-instrumentation.txt` and the two follow-up instrumentation logs
all ended with `OK (1 test)`. The final event-tap run is the clearest
synchronized pass.

| Gesture | Result | Retained evidence |
| --- | --- | --- |
| Tap | PASS | `listen-only-event-tap-2.log` recorded `leftMouseDown` and `leftMouseUp` with `command=false`. |
| Long-press right-click | PASS | Host log recorded `Touch gesture: right click injected`; event tap recorded `rightMouseDown` and `rightMouseUp` with `command=false`. |
| Long-press drag | PASS | Host log recorded `Touch gesture: drag began` and `Touch gesture: drag ended`; event tap recorded `leftMouseDragged` with `command=false`. |
| Two-finger scroll | PASS | Host log recorded `Touch gesture: two-finger scroll began`; event tap recorded `scrollWheel command=false wheel1=20`. |
| Pinch | PASS | Host log recorded `Touch gesture: pinch began`; event tap recorded `scrollWheel command=true wheel1=9`. |
| Post-pinch plain tap isolation | PASS | The next observed plain tap after the previous completed pinch run recorded `leftMouseDown command=false` and `leftMouseUp command=false`. |

The Host log also recorded `Protocol v1 selected for connection epoch 7`,
`Starting input receive loop... (touch=on)`, and repeated `Pipeline` samples
near 60 FPS with zero drops during the gesture window. One connection reset was
the expected instrumentation Activity lifecycle teardown after the gesture
driver completed; it occurred after the gesture evidence had been recorded. The
later `Runtime display switch` line retained in `host-log-eventtap-run-2.log`
occurred after the synchronized touch gate window and is unrelated to this touch
rerun gate.

## Commands

The device was protected by `/tmp/vibe-screen-device-android.lock`, and every
ADB command used the explicit serial `EP0110PZ0B9110300B`. The core commands
were:

```bash
make evidence-touch-rerun-preflight \
  EVIDENCE_SERIAL=EP0110PZ0B9110300B \
  EVIDENCE_DIR=docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-20-p0110-pacific-fixed-binary-rerun \
  TOUCH_RERUN_EXPECTED_HOST_SHA256=c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996

cd baseline/AndroidClient
./gradlew --no-daemon assembleDebug assembleDebugAndroidTest

adb -s EP0110PZ0B9110300B install -r -t \
  app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B install -r -t \
  app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s EP0110PZ0B9110300B reverse tcp:54321 tcp:54321
adb -s EP0110PZ0B9110300B shell am start -S -W \
  -n dev.telemachus.display/.MainActivity \
  --ez auto_connect true
adb -s EP0110PZ0B9110300B shell am instrument -w -r \
  -e class dev.telemachus.display.TouchGestureAcceptanceDriverInstrumentedTest \
  -e vibeScreenTouchE2E true \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

Cleanup force-stopped the Android app, removed the ADB reverse mapping, requested
the Host app to quit, and released the Android device lock.

## Files

- `touch-rerun-preflight.json`: read-only fixed-binary readiness gate.
- `result-summary.json`: machine-readable summary of the retained pass checks.
- `device-identity.txt`: exact Android device identity.
- `apk-sha256.txt`: debug and test APK hashes.
- `install-and-reverse.txt`: install, instrumentation registration, and ADB
  reverse output.
- `android-launch.txt`: Android client auto-connect launch result.
- `touch-gesture-instrumentation*.txt`: opt-in gesture driver outputs.
- `host-log-after-launch.log`, `host-log-touch-gesture-window.log`,
  `host-log-eventtap-run.log`, and `host-log-eventtap-run-2.log`: Host-side
  Protocol v1, pipeline, and gesture excerpts.
- `listen-only-event-tap-2.log`: listen-only macOS CGEvent observations for the
  final synchronized run.
- `listen-only-event-tap-2.err`: empty stderr capture for the final event-tap
  run.
- `android-diag-focused.log` and `android-logcat-focused.txt`: privacy-reduced
  Android diagnostic excerpts.
- `android-screen-after-rerun.png` and `android-window-after-rerun.xml`: visible
  client state after the rerun.
- `cleanup.txt`, `device-lock-after-cleanup.txt`, and
  `post-cleanup-processes.txt`: cleanup state.

Raw full-system logcat captures were intentionally not retained in Git because
the focused excerpts above preserve the acceptance evidence without broad
device/system noise.
