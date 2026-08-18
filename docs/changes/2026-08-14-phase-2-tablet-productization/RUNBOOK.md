# Phase 2 tablet acceptance runbook

This runbook is for the physical 8-9 inch tablet and sustained-use gates that
cannot be closed by unit tests, synthetic dp layouts, phones, emulators, or
short soaks. Record every run under `evidence/YYYY-MM-DD-<device>-phase2-8h/`
and keep raw logs even when the run fails.

## Preconditions

- Use a named 8-9 inch tablet with developer options enabled and a reliable USB
  data path or the target LAN path under test. Record manufacturer, model,
  codename, OS build, panel refresh rate, density, battery capacity if exposed,
  charger model, cable/dock, stand orientation, and ambient room temperature.
- Use the exact Mac, host build, Android APK, transport, and video preferences
  intended for the run. Record commit SHA, build command, APK SHA-256, host
  signing identity, macOS version, display mode, and Screen Recording /
  Accessibility permission state.
- Start from a clean baseline: no old Vibe Screen process, no stale ADB reverse
  unless the run deliberately exercises reconnect, and no forced battery or
  thermal overrides left from earlier checks.
- Verify the Android settings sustained-use card against platform state before
  the soak: `dumpsys battery`, `dumpsys power`, and thermal status must match
  the visible battery, charging, power-saver, and thermal labels.

## Baseline device checks

Capture these before the eight-hour timer starts:

```bash
adb shell getprop > device.txt
adb shell wm size > wm-size.txt
adb shell wm density > wm-density.txt
adb shell dumpsys battery > adb-battery-before.txt
adb shell dumpsys power > adb-power-before.txt
adb shell dumpsys thermalservice > thermal-before.txt || true
adb shell dumpsys SurfaceFlinger --latency-clear || true
adb shell pidof dev.telemachus.display > android-pid.txt
```

Also capture settings screenshots in portrait and landscape, including any
split-screen or freeform window size that the tablet supports. The screenshots
must show the sustained-use card and the active stream state.

## Eight-hour sampling

Sample at least once per minute, with a 30-second cadence preferred when storage
allows. Keep one row per sample with monotonic timestamp, wall-clock timestamp,
Android PID/RSS, host PID/RSS, FPS, dropped frames, reconnect count, battery
level, charging status, current/voltage when exposed, power-saver state, thermal
status, transport state, and the active video preference/config epoch.

The run fails immediately if the app crashes, the host crashes, the stream does
not recover after a required interruption, stale frames or stale input are
accepted after a new session epoch, Android reports severe or critical thermal
state for a sustained interval, charging cannot maintain the session on the
stand-mounted setup, or data/transport instability makes the sample series
untrustworthy. Keep the failed evidence directory and summarize the first failure
time.

## Required interruption scenarios

Run these during a separate acceptance pass, or during the eight-hour run only if
the goal is to prove recovery under disturbance:

- rotate between portrait and landscape and reopen settings after each rotation;
- background and foreground the Android app, confirming a fresh keyframe and no
  stale input delivery;
- disconnect and restore the selected transport, confirming a new session epoch
  and bounded reconnect time;
- toggle Android power saver and confirm the sustained-use card changes without
  silently changing the user's video preferences;
- apply a controlled thermal load only if it is safe for the device and charger,
  then confirm the UI, `dumpsys power`, and thermal service agree;
- reboot the Mac and verify login startup or headless Mac mini recovery when that
  gate is in scope.

## Pass criteria

- The evidence identifies the real device and host, not only a synthetic layout
  or prior phone run.
- The stream remains usable for eight hours with no unrecovered crash, no
  unbounded reconnect loop, and no stale frame/input acceptance across session
  epochs.
- Android and host memory trends are bounded by the Phase 2 test owner's stated
  threshold for that run. If no threshold was declared before the run, the result
  is evidence only and does not close the gate.
- Thermal state remains within the declared limit for the whole run; any severe
  or critical interval is called out with duration and user-visible behavior.
- The stand-mounted power setup is stable: charging state, current/voltage where
  available, and battery percentage do not show unsafe heat or net drain outside
  the declared threshold.
- Every manual recovery action records before/after logs and confirms whether the
  user-visible state matched platform state.

## Evidence package

Each run directory should include at minimum:

- `README.md` with the result, device identity, host identity, exact commands,
  pass/fail thresholds declared before the run, first failure if any, and links
  to raw logs;
- `device.txt`, `host.txt`, `apk-sha256.txt`, and `build.txt`;
- `samples.csv` for the eight-hour series;
- `adb-battery-before.txt`, `adb-battery-after.txt`, `adb-power-before.txt`,
  `adb-power-after.txt`, and thermal dumps before/after;
- `raw-logcat.txt`, host logs, reconnect logs, frame/drop logs, and any decoder
  telemetry;
- `screenshots/` for portrait, landscape, power-saver, thermal/load, reconnect,
  and end-of-run states.

Do not mark Phase 2 accepted from this runbook unless the raw evidence exists in
the directory and the summary explains every failed or skipped gate.
