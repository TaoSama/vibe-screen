# 2026-08-22 Nubia P0110 USB smoke refresh

This evidence record covers a short, lock-coordinated refresh of the currently
running USB smoke on the connected nubia P0110 / pacific device, running
Android 16 / SDK 36. The exact device serial is retained in raw evidence files.

## Verdict

PASS for the 20-second current-window USB stream refresh only. At
2026-08-22 02:11 Asia/Shanghai, adb reverse was present, the installed macOS
Host was listening on 127.0.0.1:54321, and the host-side loopback check showed
an adb-to-Host ESTABLISHED connection on 127.0.0.1:54321. The Android client
process `dev.telemachus.display` was PID 27526 and the foreground Activity was
`dev.telemachus.display/.MainActivity`.

The app PID-scoped logcat window was cleared before sampling. It contains 20
`VibeScreenTelemetry` `stream_stats` events and 19 `VD` decoder-stat samples
from this window. FPS ranged from 39.14 to 60.70, bitrate ranged from 0.27 to
0.37 Mbps, decoder input advanced from 20100 to 21180, decoder output advanced
from 20099 to 21179, and every decoder-stat sample reported `dropped=0`. The
same cleared window contains no `AndroidRuntime` or `FATAL` crash records.
`/data/tombstones` was empty.

This refresh was collected while the PR worktree HEAD was
`321eb3918026184a1b26ba8509ddee5f2d99878f` on top of main commit
`baaec28a2a47bd9c2ff38a32eaacdbf1880f1e38`. The installed Host/App binary
provenance was not revalidated in this refresh. It supports the already
recorded short USB stream-smoke readiness judgment. It does not close long
soak, host RSS no-growth, external-camera latency, input-latency,
Accessibility/input, native pointer HID, physical stylus, controller runtime,
LAN, Internet, login-startup, or headless Mac gates.

## Recorded Facts

- Device identity: nubia P0110, codename/product pacific, Android 16, SDK 36.
- Device coordination: `/tmp/vibe-screen-device-soak.lock` and
  `/tmp/vibe-screen-device-android.lock` were absent before the first ADB
  command. This run then created `/tmp/vibe-screen-device-android.lock`, used
  only `adb -s <DEVICE_SERIAL> ...`, and released the lock at the end. The
  pre-existing `/tmp/vibe-screen-device-android-test.lock` had no lsof holder
  and is recorded as a non-mandatory stale test lock.
- ADB reverse: `UsbFfs tcp:54321 tcp:54321`.
- Host listener: `/Applications/Vibe Screen.app` PID 92943 listening on
  127.0.0.1:54321.
- Host connection: host-side `lsof` observed adb PID 11477 connected to Host PID
  92943 over 127.0.0.1:54321.
- Android app: `dev.telemachus.display` PID 27526 was running and
  `dev.telemachus.display/.MainActivity` was the focused/resumed Activity.
- Device socket namespace: `/proc/27526/fd` contained socket inode 165563190,
  matching a loopback ESTABLISHED entry in `/proc/27526/net/tcp6`; because
  Android exposes net tables per namespace, this is supporting evidence and is
  not treated as the sole pass condition.
- Stream telemetry: the PID-scoped, post-clear logcat window contains
  `stream_stats` for session_epoch 2 and decoder stats with `dropped=0`.
- Crash check: the PID-scoped window and crash grep contain no `AndroidRuntime`
  or `FATAL` records; `/data/tombstones` was empty.
- Screenshot: `screen.png` captures the device display during the run; it is a
  dark frame while stream telemetry and decoder counters continued.

## Files

- `acceptance.json`, `summary.json` - machine-readable refresh result and
  explicit non-claims.
- `device_identity.txt` - explicit-serial ADB identity commands.
- `adb_reverse.txt` - explicit-serial adb reverse state.
- `foreground.txt`, `pidof_app.txt` - app PID and foreground Activity state.
- `host_lsof_54321.txt` - Host LISTEN and adb-to-Host ESTABLISHED loopback
  socket evidence.
- `device_socket_owner_check.txt`, `device_proc_net_tcp.txt` - device-side
  socket namespace diagnostics.
- `logcat_filtered.txt`, `logcat_crash_window.txt` - current-window telemetry,
  decoder, and crash checks after clearing logcat.
- `tombstones.txt` - tombstone directory listing.
- `screen.png` - device screenshot.
- `lock-status-before.txt`, `lock-status-during.txt`, `lease.txt`,
  `lease-release.txt`, `lock-status-before-fd-check.txt`,
  `lock-status-during-fd-check.txt`, `lease-fd-check.txt`, and
  `lease-release-fd-check.txt` - device-lock coordination records.

## Re-run

Use the same device identity and keep every ADB command explicit. Acquire
`/tmp/vibe-screen-device-android.lock` before the first ADB command and release
it after the short run.

    set -euo pipefail
    export DEVICE_SERIAL=<DEVICE_SERIAL>
    test ! -e /tmp/vibe-screen-device-soak.lock
    test ! -e /tmp/vibe-screen-device-android.lock
    # Atomically create /tmp/vibe-screen-device-android.lock here.
    HOST_PID="$(lsof -nP -iTCP@127.0.0.1:54321 -sTCP:LISTEN -t | head -1)"
    test -n "$HOST_PID"
    lsof -nP -a -p "$HOST_PID" -iTCP@127.0.0.1:54321 -sTCP:LISTEN
    adb -s "$DEVICE_SERIAL" reverse --list | grep 'UsbFfs tcp:54321 tcp:54321'
    APP_PID="$(adb -s "$DEVICE_SERIAL" shell pidof dev.telemachus.display | tr -d '\r' | awk '{print $1}')"
    test -n "$APP_PID"
    adb -s "$DEVICE_SERIAL" logcat -c
    sleep 20
    lsof -nP -a -p "$HOST_PID" -iTCP@127.0.0.1:54321 -sTCP:ESTABLISHED
    adb -s "$DEVICE_SERIAL" logcat -d --pid "$APP_PID" \
      | grep -E 'VibeScreenTelemetry|Decode stats|AndroidRuntime|FATAL'

Keep this evidence scoped to a short stream refresh unless a separate run
collects the required soak, RSS, latency, and input artifacts.
