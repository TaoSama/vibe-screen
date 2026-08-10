# Xiaomi 13 video-preferences 30-minute record

## Scope

- Device: Xiaomi 13, model `2211133C`, codename `fuxi`, Android 16
- ADB serial: `bac5b092`
- Transport: USB ADB reverse on TCP `54321`, Protocol v1
- Host PID: `24536`
- Window: `2026-08-10T07:37:47.401664Z` to
  `2026-08-10T08:07:47.456708Z`

The installed macOS bundle and Android launcher both display **Vibe Screen**.
Their package identifiers retain `dev.telemachus.display` for compatibility.

## Functional result

On the final artifacts, the client applied 5 Mbps / 60 FPS at config epoch 2,
then 50 Mbps / 60 FPS at epoch 3. Restarting only Android changed its process
while the Host PID stayed `24536`; the new session's epoch 1 immediately
reported 50 Mbps / 60 FPS. `android-functional-logcat.txt` is the raw client
record, and `host-functional-window.log` contains the corresponding Host
encoder/session record.

The retained Host log also records a 2 Mbps / 60 FPS in-place update. The three
PNG files capture the final-artifact 5/50 Mbps and reconnect UI states. Other
quality/FPS combinations are covered by offline protocol and encoder tests, not
claimed here as retained device evidence.

## Thirty-minute result

- `summary.json`: `complete`, 60/60 connected samples, 60/60 process-running
  samples, zero reconnects, zero sample errors.
- Host RSS: 93,728 KiB first, 64,240 KiB final; second-half slope
  -581.91 KiB/min.
- Android PSS: 78,631 KiB first, 76,682 KiB final; second-half slope
  -19.37 KiB/min.
- Exact window: 1,476 stream-stat records, mean 59.93 FPS, mean frame age
  5.87 ms, 350 Host-reported dropped frames, and zero frame-queue-drop events.

`exact-window-report.json` is intentionally `partial` derivation because this
USB main session emitted no `heartbeat_received` event. The trends remain
descriptive evidence and do not close the formal two-hour Host RSS no-growth
gate.

## Artifacts

- `artifact-sha256.txt`: installed Host executable and APK hashes
- `macos-codesign.txt`: installed Host signing metadata
- `device-model.txt`: device identity and build fingerprint
- `samples.jsonl`, `summary.json`: 30-minute device/process samples
- `host-telemetry.jsonl`, `host-window.log`: exact-window stream telemetry/log
- `exact-window-report.json`: derived trend and stream report
- `android-functional-logcat.txt`, `host-functional-window.log`: bitrate and
  reconnect verification
- `01-live-5mbps.png`, `02-live-50mbps.png`,
  `03-reconnect-epoch1-50mbps.png`: UI evidence

The sibling `-partial-attempt` directory is an intentionally interrupted
pre-fix run and is not part of this result.
