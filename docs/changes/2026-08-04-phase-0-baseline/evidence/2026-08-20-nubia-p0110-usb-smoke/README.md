# 2026-08-20 Nubia P0110 USB smoke

This evidence record covers a short USB end-to-end smoke on the connected
Nubia P0110 (pacific) device, serial EP0110PZ0B9110300B, running Android
16 / SDK 36. It is P0110/pacific evidence only; it is not Xiaomi 13/fuxi
evidence.

## Verdict

PASS for the short USB smoke only. The current origin/main source at commit
0844991ea6ca55905349abb5f57291990454f0ad built and ran a macOS Host and
Android debug APK. With adb reverse tcp:54321 tcp:54321, the Android client
connected over loopback USB, negotiated Protocol v1, received the virtual
display catalog, initialized Qualcomm hardware HEVC decode, produced first
output, and sustained short-window 60 FPS decode counters with zero reported
decoder drops. A force-stop/cold-start reconnect kept the same Host listener
PID and established a fresh Protocol v1 connection.

This record does not close the two-hour soak, host RSS no-growth, native
pointer HID mouse, physical stylus, controller runtime, rotated host-display,
external-camera latency, input-latency, login-startup, or headless Mac gates.
No Accessibility/input result is claimed.

## Recorded facts

- Repository commit: 0844991ea6ca55905349abb5f57291990454f0ad (origin/main,
  branch codex/p0110-usb-smoke-evidence).
- Device: nubia P0110, codename/product pacific, Android 16, SDK 36,
  fingerprint
  nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys.
- Display and battery during capture: 1264x2800, density 560, AC powered,
  battery 100%, temperature 31.0 C.
- A second Android emulator was connected, so every device command used
  adb -s EP0110PZ0B9110300B explicitly.
- Current-tree Host executable: baseline/MacHost/.build/release/Vibe Screen,
  SHA-256 89af29b97e314ac510f79128cdd975e810bea33bce2e5062fe3a5db3524411a9.
- Current-tree debug APK: baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk,
  SHA-256 987c6ee5bfc05fd4fbaeabf090db95ae78f0f277f530478ce257c292b171fe4b.
- A pre-existing Host from another worktree, PID 89494, was occupying
  127.0.0.1:54321; it was recorded and stopped before the current-tree Host
  was launched.
- Current-tree Host PID/listener: 97995 on 127.0.0.1:54321.
- ADB reverse: UsbFfs tcp:54321 tcp:54321.
- Initial client launch: Android PID 29380; reconnect launch: Android PID
  32410.
- Reconnect: Host PID stayed 97995 before and after force-stopping
  dev.telemachus.display and cold-starting MainActivity.

## Evidence highlights

- Host startup and capture:
  - Screen recording permission granted (CGPreflight).
  - SCShareableContent returned 3 displays: [6, 1, 3].
  - Capturing virtual display: 2000x1200 (ID: 6).
  - TCP server listening on port 54321.
  - VideoToolbox encoder configured (H.265, 35Mbps, 60fps, ULTRALOW).
- Initial USB session:
  - Host: Client connected via loopback (USB) - skipping auth, and Protocol v1
    selected for connection epoch 1.
  - Android: Protocol v1 upgrade accepted, Connected to 127.0.0.1:54321,
    onDisplaysAvailable: count=3 selected=6, and negotiated Protocol v1
    capabilities including touch, keyboard, pointer, stylus, multi-display,
    host actions, client video control, file transfer, clipboard, and color
    management.
  - Android: setupDecoder: 2000x1200, decoder=c2.qti.hevc.decoder, first media
    frame, First output frame!, and repeated Decode stats / Output counters
    through output #720 with dropped=0 and typical decoder latency around
    4.5-6.5ms per 60-sample window.
  - Host pipeline after startup settled to approximately 59.6-62.3fps with
    dropped: 0; the single initial dropped: 1 occurred before the first settled
    pipeline window.
- Reconnect session:
  - Host: fresh Client connected via loopback (USB) and Protocol v1 selected
    for connection epoch 2 with the same listener PID.
  - Android: Qualcomm c2.qti.hevc.decoder, first frame/output, and repeated
    output counters through #840 with dropped=0 and typical decoder latency
    around 5.4-6.5ms per 60-sample window.
- Foreground/UI state:
  - dumpsys window reports mCurrentFocus and mFocusedApp as
    dev.telemachus.display/.MainActivity.
  - SurfaceFlinger lists a Vibe Screen SurfaceView / BLAST surface for
    dev.telemachus.display/dev.telemachus.display.MainActivity.
  - streaming-ui-screencap.png is retained as an Android foreground-state
    artifact only. The connected screen uses screenshot protection, so the
    proof of stream content is the Host and Android media logs above.

## Files

- acceptance.json - machine-readable short-smoke result and explicit non-claims.
- device-info.json, device-state.txt, environment.txt - device and local
  environment identity.
- artifact-sha256.txt, current-host-start.txt, pre-run-host-state.txt,
  post-cleanup-host-state.txt - build artifacts, Host signing/listener, and
  stale Host cleanup record.
- adb-reverse.txt, adb-install.txt, android-start.txt,
  reconnect-android-start.txt, reconnect-summary.txt - install, launch, and
  reconnect command results.
- host-log-focused.txt, host-log-after-reconnect-focused.txt - Host log
  excerpts for the initial and reconnect windows.
- android-logcat-app-focused.txt, reconnect-logcat-app-focused.txt -
  PID-filtered Android app log excerpts. Full-device logcat was not retained in
  docs because it included unrelated application traffic.
- android-diag.log, reconnect-android-diag.log - app diagnostic logs from
  run-as dev.telemachus.display.
- window-focus.txt, surfaceflinger-vibe.txt, window.xml,
  streaming-ui-screencap.png - foreground Activity and SurfaceView artifacts.

## Commands

Representative commands used for this evidence:

    make evidence-device-info EVIDENCE_SERIAL=EP0110PZ0B9110300B EVIDENCE_DIR=docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-20-nubia-p0110-usb-smoke
    cd baseline/MacHost && swift build -c release
    cd baseline/AndroidClient && ./gradlew --no-daemon assembleDebug
    adb -s EP0110PZ0B9110300B reverse tcp:54321 tcp:54321
    adb -s EP0110PZ0B9110300B install -r -t baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
    adb -s EP0110PZ0B9110300B shell am start -S -W -n dev.telemachus.display/.MainActivity --ez auto_connect true
    adb -s EP0110PZ0B9110300B shell am force-stop dev.telemachus.display
    adb -s EP0110PZ0B9110300B shell am start -W -n dev.telemachus.display/.MainActivity --ez auto_connect true

The full command/output ledger is split across the files listed above.

## Boundaries

- The device is a Nubia P0110/pacific substitute for general Android USB smoke;
  it must not be reported as Xiaomi 13/fuxi evidence.
- The run is intentionally short and cannot support no-growth or soak claims.
- No physical HID mouse, physical stylus, physical controller, external camera,
  rotated host-display, LAN, Internet, window migration, display switching, or
  video-preference matrix was exercised.
- Protocol v1 capabilities were negotiated, but this smoke did not verify each
  negotiated capability's user-visible behavior.
- Accessibility status and Mac input injection were not verified.
