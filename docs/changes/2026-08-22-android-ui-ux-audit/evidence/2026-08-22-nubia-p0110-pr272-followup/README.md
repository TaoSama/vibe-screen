# Nubia P0110 PR272 UI/UX Follow-up Evidence

This follow-up records additional Android UI/UX evidence for PR #272 on the connected device. It focuses on connection/error recovery states, disconnected settings, 600 dp-plus layout behavior through a reversible window-size override, and measurable touch targets. It does not replace the PR #272 display-selection confirmation record in the sibling `2026-08-22-nubia-p0110-pr272-e2e` directory.

## Device And Lock

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36
- Serial: EP0110PZ0B9110300B
- Physical size: 1264x2800
- Physical density: 560
- Device lock: `/tmp/vibe-screen-device-android.lock`, task `android-ui-ux-p0110-e2e-pr272-followup`

`commands.txt` contains the exact device identity, ADB serial listing, foreground window, installed package, and ADB reverse state. An emulator was also connected, so every ADB command in this run used `adb -s EP0110PZ0B9110300B`.

## Initial Blocker Captured

The first foreground window was Nubia permission-controller UI, not Vibe Screen:

```text
mCurrentFocus=Window{... com.android.permissioncontroller/com.android.permissioncontroller.permissionplus.ui.InterceptJumpDialogActivity}
```

This is preserved in `permission-controller-before.png` and `window-permission-controller-before.xml`. The dialog was dismissed with Back before collecting app UI evidence.

## Portrait Connection / Error-Recovery State

`app-after-start.png` and `window-app-after-start.xml` show Vibe Screen foreground in portrait with the USB waiting/retry state:

```text
VIBE SCREEN
Waiting for your Mac
Keep the USB cable connected and open Vibe Screen on your Mac. This device will connect automatically.
TRY AGAIN
Looking for Vibe Screen on your Mac
Connection details
DISPLAY SETTINGS
```

This is a disconnected/connecting recovery surface. It is not a streaming or latency gate.

## Portrait Settings State

`settings-portrait-disconnected.png` and `window-settings-portrait-disconnected.xml` show the settings dialog opened from the disconnected connection page. The captured content includes:

```text
Display settings
Show Stats
FPS, bitrate, resolution
Sustained use
```

The settings dialog was readable in portrait, and `touch-target-summary.txt` records the visible `showStatsSwitch` as exactly `48.0x48.0 dp`.

## 600 dp-plus Width Override

A reversible `wm size 2800x1264` override was used on the same Nubia device to exercise a 600 dp-plus wide layout bucket. At 560 dpi, the captured `connectionScroll` width was 2380 px, or 680.0 dp.

`disconnected-wm-override-800dp.png` and `window-disconnected-wm-override-800dp.xml` show the wide disconnected connection page. `touch-target-summary.txt` records these visible targets as passing the 48 dp minimum:

```text
modeUSB: 115.1x48.0 dp pass
modeWireless: 115.1x48.0 dp pass
modeInternet: 115.4x48.0 dp pass
connectButton: 343.4x56.0 dp pass
showAdvanced: 343.4x48.0 dp pass
```

`wm-after-restore.txt` confirms the device was restored to its physical size and density after the override. The attempted settings tap in the override did not open the settings dialog, so `settings-wm-override-800dp.png` is treated as another wide connection-page capture, not as settings evidence.

## Rotation Boundary

The run attempted `settings put system user_rotation 1`, but UIAutomator still reported `hierarchy rotation="0"` for `window-disconnected-landscape-w600.xml`. This run therefore does not claim a real orientation-rotation pass. The prior sibling PR272 E2E directory still contains the real stream/control-surface landscape evidence collected before this follow-up.

## Files

- `commands.txt` - lock, identity, foreground, package, ADB reverse
- `permission-controller-before.png`, `window-permission-controller-before.xml` - external Nubia permission dialog blocker
- `app-after-start.png`, `window-app-after-start.xml` - portrait disconnected/connecting UI
- `settings-portrait-disconnected.png`, `window-settings-portrait-disconnected.xml` - portrait settings dialog
- `disconnected-wm-override-800dp.png`, `window-disconnected-wm-override-800dp.xml` - 680 dp wide disconnected connection UI
- `touch-target-summary.txt` - computed target sizes from UIAutomator bounds at 560 dpi
- `diag-followup.log`, `diag-followup.stderr`, `logcat-tail.txt` - diagnostics captured after the walkthrough
- `wm-before-override.txt`, `wm-after-restore.txt` - reversible window-size override state

## Result

This follow-up strengthens PR #272 with repeatable Nubia P0110 evidence for disconnected/connecting UI, settings visibility, 600 dp-plus width connection layout, and 48 dp touch targets. It does not close any README gate, does not claim Xiaomi/fuxi evidence, and does not prove stream, latency, soak, final disconnect completion, TalkBack traversal, LAN, native-pointer, stylus, controller, or iOS acceptance.
