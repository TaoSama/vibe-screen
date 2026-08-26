# Nubia P0110 fixed-binary touch-gesture rerun blocked preflight

Date: 2026-08-21 (Asia/Shanghai)

## Result

**BLOCKED.** This run did not execute the opt-in gesture driver and does not add
a fixed-binary touch-gesture pass. The read-only preflight was ready, but the
installed stable-signed Host could not reach a usable capture/listener state on
this desktop session: `SCShareableContent` returned zero displays and unattended
startup repeatedly failed with `Virtual display 1 not found after 5 attempts`.
The Android client therefore stayed on `Waiting for your Mac`, so there was no
synchronized Host gesture log or listen-only event-tap evidence to validate.

The prior 2026-08-20 Nubia P0110/pacific pass remains the retained evidence for
the fixed stable-signed binary touch rerun on a general Android substitute. This
blocked 2026-08-21 attempt does not replace it and does not claim Xiaomi 13/fuxi
evidence.

## Source and identity

- Source base: `a9b05002dde33b7b972f6bcf8131305bedd8548e`
  (`origin/main` after `git fetch origin --prune`).
- Worktree: `.claude/worktrees/touch-gesture-fixed-binary-rerun`.
- Android device: nubia P0110, codename `pacific`, serial
  `<device-serial>`.
- Android version: 16 / API 36.
- Host bundle: `/Applications/Vibe Screen.app`.
- Host identifier: `dev.telemachus.display`.
- Expected and installed Host binary SHA-256:
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`.

## Preflight

`touch-rerun-preflight.json` reported `result: ready` with no blockers. It
confirmed the stable-signed Host binary hash, Screen Recording and Accessibility
TCC grants for `dev.telemachus.display`, and the explicit P0110/pacific Android
16 identity.

## Blocker

The Host was launched from `/Applications/Vibe Screen.app`, but did not establish
a usable USB streaming session for the Android client. The retained Host log
shows the failure loop:

```text
SCShareableContent returned 0 displays: []
Virtual display 1 not found in attempt 1, retrying...
...
Unattended startup failed: Virtual display with ID 1 not found after 5 attempts
Scheduling unattended host recovery in 30s
```

The retained Android screenshot showed `Waiting for your Mac`. Because the
streaming UI was not connected, the opt-in
`TouchGestureAcceptanceDriverInstrumentedTest` was not run. The fail-closed
summary therefore reports `result: blocked` and `can_close_touch_rerun_gate:
false`.

## Commands

The run acquired `/tmp/vibe-screen-device-android.lock` before the first ADB
command and released it during cleanup. Every ADB command used the explicit
serial `<device-serial>`.

```bash
make evidence-touch-rerun-preflight \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_DIR=docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-21-p0110-pacific-fixed-binary-rerun \
  TOUCH_RERUN_EXPECTED_HOST_SHA256=c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996 \
  TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER=nubia \
  TOUCH_RERUN_EXPECTED_ANDROID_MODEL=P0110 \
  TOUCH_RERUN_EXPECTED_ANDROID_DEVICE=pacific \
  TOUCH_RERUN_EXPECTED_ANDROID_RELEASE=16 \
  TOUCH_RERUN_EXPECTED_ANDROID_SDK=36

cd baseline/AndroidClient
./gradlew --no-daemon assembleDebug assembleDebugAndroidTest

adb -s <device-serial> install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s <device-serial> install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s <device-serial> reverse tcp:54321 tcp:54321
adb -s <device-serial> shell am start -S -W \
  -n dev.telemachus.display/.MainActivity \
  --ez auto_connect true

make evidence-touch-rerun-summary \
  EVIDENCE_DIR=docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-21-p0110-pacific-fixed-binary-rerun \
  TOUCH_RERUN_HOST_LOG=docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/2026-08-21-p0110-pacific-fixed-binary-rerun/host-log-blocked-capture.log \
  TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER=nubia \
  TOUCH_RERUN_EXPECTED_ANDROID_MODEL=P0110 \
  TOUCH_RERUN_EXPECTED_ANDROID_DEVICE=pacific \
  TOUCH_RERUN_EXPECTED_ANDROID_RELEASE=16 \
  TOUCH_RERUN_EXPECTED_ANDROID_SDK=36
```

The summary command exited `2`, as expected for blocked evidence.

## Files

- `touch-rerun-preflight.json`: read-only fixed-binary readiness result.
- `result-summary.json`: fail-closed evidence summary for this blocked attempt.
- `device-identity.txt`: exact Android device identity.
- `apk-sha256.txt`: current debug and test APK hashes.
- `install-and-reverse.txt`: APK install, instrumentation registration, and ADB
  reverse output.
- `android-launch.txt`: Android client auto-connect launch result.
- `android-screen-before-rerun.png`: Android UI state showing the client waiting
  for the Mac.
- `host-restart-and-listen.txt`, `host-log-after-launch.log`, and
  `host-log-blocked-capture.log`: Host capture/listener blocker evidence.
- `touch-gesture-instrumentation.txt` and `listen-only-event-tap.log`: empty by
  design because the gesture driver was not run after the streaming precondition
  failed.
- `cleanup.txt` and `device-lock-after-cleanup.txt`: cleanup and lock-release
  state.
