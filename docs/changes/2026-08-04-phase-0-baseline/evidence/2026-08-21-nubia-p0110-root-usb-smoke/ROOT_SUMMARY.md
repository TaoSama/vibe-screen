# Root USB Smoke Summary - 2026-08-21 22:35 Asia/Shanghai

Device: Nubia P0110 / pacific / Android 16 / SDK 36, serial EP0110PZ0B9110300B.

Scope: short USB smoke only. This is not a long soak, latency gate, input gate, UI gate, or Xiaomi/fuxi evidence.

Actions:
- Acquired `/tmp/vibe-screen-device-android.lock` with fcntl exclusive lock.
- Confirmed `adb reverse tcp:54321 tcp:54321`.
- Confirmed `/Applications/Vibe Screen.app` process PID 92943 listening on `127.0.0.1:54321`.
- Force-stopped and started `dev.telemachus.display/.MainActivity`.
- Sampled Host 54321 connections for 60 seconds.
- Captured screenshot, `dumpsys activity top`, and logcat tail.
- Force-stopped the app after sampling and released the lock.

Observed pass evidence:
- `established_after_5s.txt` through `established_after_60s.txt` all contain adb <-> Host ESTABLISHED connection.
- `logcat_filtered.txt` contains 9 `VibeScreenTelemetry` `stream_stats` records.
- FPS values observed: 60.04, 59.92, 60.10, 59.94, 60.22, 59.88, 57.94, 60.16, 56.97.
- Mbps values observed: 0.36-0.37.
- No FATAL/AndroidRuntime crash was observed in the filtered log.

Observed caveats / follow-up:
- `screen.png` and `activity_top_after.txt` show Nubia launcher in the foreground, not Vibe Screen UI, while the app process continued streaming in background. Treat this as a UI/lifecycle follow-up, not a full UX pass.
- Host lsof before the run showed many CLOSED TCP 54321 file descriptors. This did not block LISTEN or the short session, but it should be investigated as potential session cleanup/resource retention.
- After cleanup, `lsof -nP -iTCP:54321 | grep ESTABLISHED` was empty and `pidof dev.telemachus.display` was empty.
