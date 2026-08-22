# P0110 Live USB Clipboard E2E Attempt

Date: 2026-08-21 Asia/Shanghai
Branch: `codex/android-clipboard-e2e-evidence`
Baseline: `origin/main` at `9dfc7caa975f1e2b851302d7cee72a55ade0429e`
Source head at attempt start: `fb3538def306bc9ccc8d0aebb767af174f7257df`
Scope: Android `ClipboardManager` <-> macOS `NSPasteboard` Protocol v1 device E2E
Verdict: blocked before clipboard transfer; Android local clipboard marker setup passed

## Device and Lock

This run used the shared Android acceptance device only after taking the device
lock. The lock file was `/tmp/vibe-screen-device-android.lock` and recorded:

```text
task=pr157-clipboard-e2e-real-attempt
branch=codex/android-clipboard-e2e-evidence
serial=EP0110PZ0B9110300B
pid=16127
acquired_at=2026-08-21T17:10:32+0800
lock_method=python_fcntl_exclusive_sleep_holder
```

All device operations in this run used `adb -s EP0110PZ0B9110300B`. The target
device identity was recorded as:

- serial: `EP0110PZ0B9110300B`
- manufacturer: `nubia`
- model: `P0110`
- codename/device: `pacific`
- Android release: `16`
- SDK: `36`
- fingerprint: `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`

This is Nubia P0110/pacific Android handset evidence only. It is not Xiaomi
13/fuxi evidence and it is not tablet evidence.

## What Ran

The current Android debug app and androidTest APK were built and installed on
the P0110 device. The instrumentation helper then set the Android foreground
system clipboard marker:

```text
android_marker=vs-android-to-mac-1787303772
mac_marker=vs-mac-to-android-1787303772

adb -s EP0110PZ0B9110300B shell am instrument -w \
  -e class dev.telemachus.display.ClipboardManagerInstrumentedTest#setForegroundClipboardFromInstrumentationArgument \
  -e clipboard_marker vs-android-to-mac-1787303772 \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

The result was `OK (1 test)`, proving the foreground Android Activity can place
the marker in Android `ClipboardManager`. USB reverse was present and the
Android app was launched with `--ez auto_connect true`.

## Session Result

The installed Host was listening on `127.0.0.1:54321` and Android reached live
USB streaming over Protocol v1. The Android diagnostic log repeatedly recorded
Protocol v1 acceptance followed by a session binding without clipboard support:

```text
SC: Protocol v1 upgrade accepted
MA: onDisplaysAvailable: count=3 selected=1 negotiated=[CAPABILITY_TOUCH, CAPABILITY_KEYBOARD, CAPABILITY_POINTER, CAPABILITY_STYLUS, CAPABILITY_MULTI_DISPLAY, CAPABILITY_HOST_ACTIONS, CAPABILITY_CLIENT_VIDEO_CONTROL, CAPABILITY_STYLUS_EXTENDED] ...
MA: session binding promoted: displaySelection=true keyboard=true nativePointer=true controller=false hostActions=true clipboard=false
```

The Android UI dump after revealing the control bar showed `Window actions`,
`Settings`, and `Disconnect`, but no `controlClipboardButton`. That matches the
`clipboard=false` binding and blocks the runbook requirement that both peers
negotiate clipboard capability in the same Protocol v1 session before any
clipboard transfer is attempted.

No Android -> Mac or Mac -> Android system clipboard transfer was attempted
after this capability gate failed. The production controls are hidden when
clipboard capability is not negotiated, so continuing would not test the real
user-approved clipboard path.

## Host and Automation Blockers

The installed `/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen` binary
did not match the current locally built release binary:

```text
installed app sha256: c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996
current release sha256: 90dc772ea25a2071b6f258bc8fa52c2e5da275e3f560d25810797b061ccf2914
```

Current-branch Host preflight failed because the machine does not have the
stable signing identity configured for device acceptance:

```text
codesign identity 'Vibe Screen Dev' not found in the keychain...
```

Ad-hoc signing was not used as replacement evidence because it changes the
code-signing identity and can invalidate macOS Screen Recording and
Accessibility permissions. Mac status-menu automation was also not permission
ready: Wailmer reported Accessibility and screenshots permissions as
`not-granted`, and its menu-bar surface is unavailable.

## Gate Status

The Android `ClipboardManager` <-> macOS `NSPasteboard` E2E gate remains open.
This run proves a live P0110 USB Protocol v1 streaming session and Android
local clipboard marker setup, but it does not prove either cross-device
clipboard direction.

The next concrete step is to install or provide a current-branch, stable-signed
`/Applications/Vibe Screen.app` build with the normal Screen Recording and
Accessibility grants, confirm the live session negotiates `CAPABILITY_CLIPBOARD`
with Android `clipboard=true`, then rerun both user-approved marker transfers
from this runbook.

## Retained Files

- `commands.txt`: command transcript, branch, source head, markers, and lock metadata.
- `device-info.txt`: P0110 device identity from explicit `adb -s EP0110PZ0B9110300B` commands.
- `session-preflight.txt`: USB reverse, Host listener, and Android process state.
- `android-assemble-debug-android-test.txt`: Android build result.
- `android-install-debug.txt`: debug app install result.
- `android-install-debug-android-test.txt`: androidTest install result.
- `android-set-clipboard.txt`: Android marker setup instrumentation result.
- `android-start-main.txt`: Android app launch result.
- `android-diag-after-start.txt` and `android-diag-clipboard.txt`: app diagnostic logs showing Protocol v1 and `clipboard=false`.
- `android-window-after-no-clipboard-capability.xml` and `android-window-after-reveal-tap.xml`: UI hierarchy showing no clipboard control.
- `android-screen-after-no-clipboard-capability.png` and `android-screen-after-reveal-tap.png`: device screenshots.
- `host-session-after-start.log` and `host-clipboard.log`: Host connection log excerpts.
- `host-binary-identity.txt`: installed/current Host binary hash comparison.
- `host-binary-clipboard-capability-check.txt`: installed/current binary string probe.
- `mac-host-preflight-current.txt`: stable signing identity blocker.
- `mac-ui-automation-preflight.txt`: Mac UI automation permission blocker.
- `markers.env`: generated Android and Mac marker strings.
