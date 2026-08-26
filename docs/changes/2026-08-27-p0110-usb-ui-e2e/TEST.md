# P0110 USB UI end-to-end verification

Status: current-base Android USB/UI evidence recorded; non-closing for stable release
Date: 2026-08-27
Base commit: 3b2ba11e832a3618eaedfc67f92414b161423a00
Device: nubia P0110 / pacific / Android 16 / SDK 36

## Test matrix

| Area | Command or action | Result | Evidence |
| --- | --- | --- | --- |
| Source freshness | git fetch origin --prune; compare HEAD with origin/main | PASS: both resolved to 3b2ba11e832a3618eaedfc67f92414b161423a00; worktree was clean before evidence docs were added | [device-baseline.txt](evidence/2026-08-27-p0110-pacific-usb-ui/device-baseline.txt) |
| Android build and static checks | cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug | PASS: unit tests, lint, and debug APK assembly completed | [android-gradle-check.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-gradle-check.txt) |
| APK install and launch | Install debug APK; launch dev.telemachus.display/.MainActivity with auto_connect=true | PASS: install succeeded and Activity reported Status: ok | [android-launch.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-launch.txt) |
| USB reverse | adb reverse tcp:54321 tcp:54321; adb reverse --list | PASS: UsbFfs tcp:54321 tcp:54321 present | [adb-reverse.txt](evidence/2026-08-27-p0110-pacific-usb-ui/adb-reverse.txt) |
| macOS Host readiness | Read-only shared prerequisite check | BLOCKED for gate closure: listener present, but current-source provenance, stable signing/TCC, virtual HID entitlement, and login/headless prerequisites were not satisfied | [host-readiness-summary.txt](evidence/2026-08-27-p0110-pacific-usb-ui/host-readiness-summary.txt), [host-readiness-sanitized.json](evidence/2026-08-27-p0110-pacific-usb-ui/host-readiness-sanitized.json) |
| Protocol v1 initial stream | Start Host/Android USB session and collect logcat/smoke summary | PASS for short live smoke: Protocol v1 accepted, display list arrived, HEVC decoder started, first frame and first output frame observed | [usb-live-smoke-sanitized.json](evidence/2026-08-27-p0110-pacific-usb-ui/usb-live-smoke-sanitized.json), [android-logcat-key-events.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-logcat-key-events.txt) |
| Control capsule | Reveal stream controls and inspect UI hierarchy | PASS: USB / ADB reverse state, display selector, window actions, settings, and disconnect controls were present | [ui/control-capsule.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/control-capsule.xml) |
| Display picker and switch | Open display dropdown; select external display | PASS: built-in, external, and virtual extended displays were listed; selecting the external display produced epoch 2 1920x1080 reconfiguration and confirmed active display 2 | [ui/display-dropdown.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/display-dropdown.xml), [android-logcat-key-events.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-logcat-key-events.txt) |
| Settings and video controls | Open settings; toggle stats; select Smooth; select 30 FPS; move bitrate to 100 Mbps | PASS: UI state and logcat showed authoritative video preferences for epochs 3, 4, and 5 | [ui/settings-dialog.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/settings-dialog.xml), [ui/video-preferences.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/video-preferences.xml), [android-logcat-key-events.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-logcat-key-events.txt) |
| Disconnect UX | Tap current disconnect bounds from UI hierarchy; confirm dialog | PASS: Disconnect? dialog with CANCEL and DISCONNECT actions appeared; confirming returned to launcher focus | [ui/disconnect-confirm.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/disconnect-confirm.xml) |
| Reconnect | Force-stop / relaunch cycles with ADB reverse restored | PASS for app relaunch reconnect: repeated Protocol v1 upgrade and decoder startup events observed, including final reconnected UI hierarchy | [ui/reconnected.xml](evidence/2026-08-27-p0110-pacific-usb-ui/ui/reconnected.xml), [android-logcat-key-events.txt](evidence/2026-08-27-p0110-pacific-usb-ui/android-logcat-key-events.txt) |

## Important observations

- The USB live-smoke summary is a short functional smoke, not a performance or
  stability gate. It observed stream frames and HEVC decode, but it does not
  prove sustained 60 FPS, latency, or no-growth RSS behavior.
- The missing-reverse and manual empty-state attempts were not used for gate
  closure because persisted auto-connect/startup settings produced noisy
  fallback and heartbeat-timeout loops rather than a clean actionable empty or
  error state capture.
- The initial automated disconnect taps missed because the capsule auto-hidden
  and because display-name width changed the button bounds. Reading the current
  UI hierarchy before tapping validated the product path without a code change.

## Open gates

- macOS Host current-source stable-signing and provenance readiness remains
  blocked by the readiness report.
- Host TCC, virtual HID entitlement, login/headless readiness, and Host RSS
  no-growth gates remain open.
- Xiaomi 13/fuxi hardware-specific acceptance remains open; this P0110 record
  is a substitute Android handset record only.
- Native physical HID mouse, physical stylus drawing, controller runtime,
  trusted-LAN, Internet, latency, and two-hour soak evidence were not collected.
- Clean Android no-reverse/manual empty-state UX evidence was not retained in
  this run and remains open for the actionable-error-state matrix.
