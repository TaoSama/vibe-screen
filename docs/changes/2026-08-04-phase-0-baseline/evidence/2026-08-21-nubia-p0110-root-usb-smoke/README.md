# 2026-08-21 Nubia P0110 root USB smoke

This evidence record covers a short root-orchestrated USB smoke on the connected
Nubia P0110 (pacific) device, running Android 16 / SDK 36. It is
P0110/pacific evidence only; it is not Xiaomi 13/fuxi evidence. The exact
device serial is retained in the raw evidence files.

## Verdict

PASS for the short USB stream smoke only. At 2026-08-21 22:35 Asia/Shanghai,
adb reverse was present, /Applications/Vibe Screen.app PID 92943 was listening
on 127.0.0.1:54321, and launching dev.telemachus.display/.MainActivity
produced an adb-to-Host ESTABLISHED connection at every sample from 5 seconds
through 60 seconds.

This record supersedes the earlier same-day readiness-only blocker for the
specific Host-listener and USB-connection start condition. It does not close the
long soak, host RSS no-growth, external-camera latency, input-latency,
Accessibility/input, UI foreground, lifecycle, native pointer HID, physical
stylus, controller runtime, LAN, Internet, login-startup, or headless Mac gates.

## Recorded facts

- Device identity: nubia P0110, codename/product pacific, Android 16, SDK 36;
  the exact serial is retained in the raw evidence files.
- ADB reverse: UsbFfs tcp:54321 tcp:54321 before the run.
- Host listener: /Applications/Vibe Screen.app PID 92943 listening on
  127.0.0.1:54321 before the client launch.
- Android launch: the documented command for
  `dev.telemachus.display/.MainActivity` started the Activity; app PID 22447
  was observed.
- USB stream connection: established_after_5s.txt through
  established_after_60s.txt all show adb PID 11477 connected to Host PID 92943
  over 127.0.0.1:54321.
- Stream telemetry: logcat_filtered.txt contains 9 VibeScreenTelemetry
  stream_stats events with FPS from 56.97 to 60.22 and Mbps from 0.36 to
  0.37.
- Decoder telemetry: focused logcat excerpts show Qualcomm HEVC decode stats
  with input/output around 57-60 FPS, rendered output around 55-60 FPS, and
  dropped=0 in the retained 60-sample windows.
- Crash check: the retained filtered logcat excerpts contain no FATAL or
  AndroidRuntime crash records for the smoke window.
- Cleanup: after sampling, no adb-to-Host ESTABLISHED socket and no
  dev.telemachus.display PID were observed.

## Limits

- The run lasted 60 seconds and is not a soak or RSS no-growth result.
- The run did not include external-camera glass-to-glass latency or synchronized
  input-latency measurement.
- The run did not exercise Accessibility input, touch, keyboard, native pointer,
  stylus, controller, file transfer, clipboard, window migration, display
  switching, reconnect, LAN, or Internet behavior.
- screen.png and activity_top_after.txt show the Nubia launcher in the
  foreground while the app process continued streaming in the background. Treat
  this as a UI/lifecycle follow-up, not a UI pass.
- host_lsof_before.txt shows 45 CLOSED TCP 54321 file descriptors still owned
  by the Host process. They did not block LISTEN or this short session, but they
  remain a cleanup/resource-retention follow-up and cannot close the host RSS
  no-growth gate.

## Files

- acceptance.json - machine-readable short-smoke result and explicit non-claims.
- ROOT_SUMMARY.md, summary.json, device_identity.json - source summary and
  device identity.
- adb_devices.txt, adb_reverse_before.txt, host_lsof_before.txt - device,
  reverse, and Host listener preconditions.
- established_after_5s.txt through established_after_60s.txt - adb-to-Host
  ESTABLISHED socket samples.
- start_main_activity.txt, pidof_app.txt - Android client launch and PID.
- logcat_filtered.txt, logcat_tail_focused.txt - telemetry, decoder, and
  crash-check excerpts.
- activity_top_after.txt, screen.png - UI/lifecycle artifacts showing the
  launcher foreground caveat.
- host-socket-fd.json - diagnostic for retained CLOSED Host socket file
  descriptors.

## Re-run

Use the same device identity and keep every adb command explicit:

    set -euo pipefail
    export DEVICE_SERIAL=<DEVICE_SERIAL>
    HOST_PID="$(lsof -nP -iTCP@127.0.0.1:54321 -sTCP:LISTEN -t | head -1)"
    test -n "$HOST_PID"
    lsof -nP -a -p "$HOST_PID" -iTCP@127.0.0.1:54321 -sTCP:LISTEN
    adb -s "$DEVICE_SERIAL" reverse tcp:54321 tcp:54321
    adb -s "$DEVICE_SERIAL" logcat -c
    adb -s "$DEVICE_SERIAL" shell am start -n dev.telemachus.display/.MainActivity
    for second in 5 10 15 20 25 30 35 40 45 50 55 60; do
      sleep 5
      lsof -nP -a -p "$HOST_PID" -iTCP@127.0.0.1:54321 -sTCP:ESTABLISHED
    done
    adb -s "$DEVICE_SERIAL" logcat -d | grep -E 'VibeScreenTelemetry|Decode stats|AndroidRuntime|FATAL'

If the Activity falls behind the launcher again, keep the stream connection
claim separate from UI foreground/lifecycle acceptance.
