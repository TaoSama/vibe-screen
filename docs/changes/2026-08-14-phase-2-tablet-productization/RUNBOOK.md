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
- Create `phase2-tablet-manifest.json` before starting the timer so the run has
  a run ID plus predeclared identity, setup, scenario, and threshold metadata.
  This manifest is preparation evidence only; it cannot close the gate without
  the raw eight-hour artifacts and final gate report.

## Baseline device checks

Capture these before the eight-hour timer starts:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
adb -s "$ADB_SERIAL" shell getprop > device.txt
adb -s "$ADB_SERIAL" shell wm size > wm-size.txt
adb -s "$ADB_SERIAL" shell wm density > wm-density.txt
adb -s "$ADB_SERIAL" shell dumpsys battery > adb-battery-before.txt
adb -s "$ADB_SERIAL" shell dumpsys power > adb-power-before.txt
adb -s "$ADB_SERIAL" shell dumpsys thermalservice > thermal-before.txt 2> thermal-before.err
adb -s "$ADB_SERIAL" shell dumpsys SurfaceFlinger --latency-clear || true
adb -s "$ADB_SERIAL" shell pidof dev.telemachus.display > android-pid.txt
```

Then write the Phase 2 manifest from the evidence root. Use
`PHASE2_DEVICE_CLASS=android_substitute` for a Nubia P0110/pacific/Android 16
or another phone substitute; do not label a substitute as Xiaomi 13/fuxi or as
8-9 inch tablet evidence.

```bash
make phase2-tablet-manifest \
  EVIDENCE_DIR="$RUN_DIR" \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  PHASE2_DEVICE_CLASS=physical_8_9_inch_tablet \
  PHASE2_TABLET_SIZE_INCHES="8.8" \
  PHASE2_STAND_SETUP="<stand orientation and mounting description>" \
  PHASE2_CHARGER="<charger model and rating>" \
  PHASE2_CABLE_OR_DOCK="<data cable or dock identity>" \
  PHASE2_AMBIENT_TEMPERATURE_CELSIUS="<room temperature>" \
  PHASE2_VIDEO_PREFERENCES="<quality/FPS/bitrate settings>" \
  PHASE2_HOST_IDENTITY="<Mac model and macOS version>" \
  PHASE2_HOST_BUILD="<host build command, signing identity, and SHA>" \
  PHASE2_APK_SHA256="<debug or release APK SHA-256>" \
  PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS="<battery temperature limit>" \
  PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT="<maximum net battery drain>" \
  PHASE2_RECOVERY_SCENARIOS="background_foreground,transport_reconnect"
```

If `dumpsys thermalservice` fails or writes an empty dump, keep
`thermal-before.err`, mark the thermal gate failed, and do not count the run as
Phase 2 thermal evidence. SurfaceFlinger latency-clear failures are diagnostic
only and do not invalidate the run by themselves.
`android-pid.txt` is a diagnostic process-identity snapshot for comparing the
start and end of a run; it is not a required evidence artifact.

Capture the matching end-of-run platform state before stopping the app or host:

```bash
adb -s "$ADB_SERIAL" shell dumpsys battery > adb-battery-after.txt
adb -s "$ADB_SERIAL" shell dumpsys power > adb-power-after.txt
adb -s "$ADB_SERIAL" shell dumpsys thermalservice > thermal-after.txt 2> thermal-after.err
adb -s "$ADB_SERIAL" shell pidof dev.telemachus.display > android-pid-after.txt || true
```

If the final `dumpsys thermalservice` command fails or writes an empty dump,
keep `thermal-after.err`, mark the thermal gate failed, and preserve the failed
evidence directory.

Also capture settings screenshots in portrait and landscape, including any
split-screen or freeform window size that the tablet supports. The screenshots
must show the sustained-use card and the active stream state.

## Eight-hour sampling

Sample at least once per minute, with a 30-second cadence preferred when storage
allows. The canonical sample file is `samples.jsonl`; `samples.csv` may be a
derived conversion for spreadsheets, but it must not replace the raw JSONL.
Keep one row per sample with monotonic timestamp, wall-clock timestamp, Android
PID/RSS, host PID/RSS, FPS, dropped frames, reconnect count, battery level,
charging status, current/voltage when exposed, power-saver state, thermal
status, transport state, and the active video preference/config epoch.
`dumpsys battery` status values are Android's standard enum: `1` unknown, `2`
charging, `3` discharging, `4` not charging, and `5` full. The gate treats only
charging/full samples as compatible with stand-mounted charging, requires the
derived `plugged` value to stay nonzero, and compares net battery drain against
the predeclared manifest threshold.

A directory named `phase2-8h` closes the sustained-use gate only when
`summary.json` records `duration_seconds >= 28800`, `interval_seconds <= 60`,
and zero missing sample gaps over the measured interval. The run README must
include the exact collection commands, links to `samples.jsonl`,
`summary.json`, `phase2-tablet-manifest.json`, and raw logs, plus the measured
duration, cadence, and first-failure fields.
After deriving the exact-window report, run:

```bash
make phase2-tablet-gate EVIDENCE_DIR="$RUN_DIR"
```

The gate reads the manifest and raw evidence root as well as the soak report, so
a short run, phone substitute, missing raw battery / power / thermal files,
missing screenshots, or undeclared threshold remains `insufficient` instead of
closing Phase 2.

The run fails immediately if the app crashes, the host crashes, the stream does
not recover after a required interruption, stale frames or stale input are
accepted after a new session epoch, Android reports severe or critical thermal
state for a sustained interval, charging cannot maintain the session on the
stand-mounted setup, or data/transport instability makes the sample series
untrustworthy. These conditions terminate collection instead of producing a
partial success. Keep the failed evidence directory, preserve logs through the
failure point, and record the earliest failure timestamp as `first_failure_at`
in `summary.json` and the run README.

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

## Hardware-keyboard workflow

Run the hardware-keyboard workflow as a separate focused pass unless the test
owner explicitly includes it in a longer tablet run. ADB `input keyevent` may be
kept as diagnostic dispatch evidence, but it cannot close this gate because it
does not prove a physical Android-attached keyboard source.

Before touching the Android device, acquire the shared device coordination lock:

```bash
lock=/tmp/vibe-screen-device-android.lock
if ! (set -o noclobber; printf 'owner=phase2-hardware-keyboard\npid=%s\nworktree=%s\ncreated_at=%s\n' \
  "$$" "$(pwd)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$lock"); then
  echo "Android device lock is already held: $lock" >&2
  exit 2
fi
trap 'rm -f "$lock"' EXIT HUP INT TERM
```

If the lock already exists, stop and record a blocked evidence directory without
running ADB. A passing run must use the actual target serial and preserve the
observed identity as Nubia P0110 / pacific / Android 16 when using
`EP0110PZ0B9110300B`; do not relabel this device as Xiaomi 13/fuxi or as tablet
hardware.

Collect these artifacts in `evidence/YYYY-MM-DD-<device>-hardware-keyboard/`:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
adb -s "$ADB_SERIAL" shell dumpsys input > "$RUN_DIR/dumpsys-input.txt"
adb -s "$ADB_SERIAL" logcat -c
adb -s "$ADB_SERIAL" reverse tcp:54321 tcp:54321
```

Also retain a Host preflight record with the listener, signing identity, and
permission state before starting the run:

```bash
lsof -nP -iTCP:54321 -sTCP:LISTEN > "$RUN_DIR/host-listener.txt"
security find-identity -v -p codesigning > "$RUN_DIR/codesign-identities.txt"
python3 scripts/macos_dev_host.py preflight --report "$RUN_DIR/host-signing-and-permissions.txt"
```

Do not continue to physical-keyboard input unless the Host listener exists and
the installed Host is stable-signed with Screen Recording and Accessibility
ready. Once the stream is active, press keys on the attached keyboard and retain
Android and Host logs proving:

- the physical keyboard device name and `Sources: ... KEYBOARD` in
  `dumpsys-input.txt`;
- Protocol v1 keyboard and USB HID modifier-byte capabilities were negotiated;
- `MainActivity` or `StreamClient` production forwarding accepted the key
  events;
- Host `Key injected: hid=<usage> pressed=<true|false> modifiers=<mask>` lines
  include paired press/release events;
- at least one shortcut/modifier combination, such as Control+C, Command+C,
  Shift+A, or Alt+Tab, reaches the Host;
- a later plain key has no leaked modifier after the shortcut is released;
- a visible Mac-side text or shortcut result is captured by screenshot, screen
  recording, or a retained app log.

Create `hardware-keyboard-observations.json` with explicit boolean observations
for every required item, then derive the gate summary:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

The resulting `hardware-keyboard-summary.json` can close the
hardware-keyboard workflow gate only when `verdict=pass` and
`can_close_hardware_keyboard_gate=true`. A blocked or insufficient summary keeps
the gate open and must explain the missing physical keyboard, Host listener,
stable signed/TCC Host, logs, or visible Mac result.

## Pass criteria

- The evidence identifies the real device and host, not only a synthetic layout
  or prior phone run.
- The hardware-keyboard workflow gate closes only when a physical keyboard
  attached to the recorded Android device drives the production Protocol v1
  keyboard path into a stable signed/TCC-ready Host, with Host key-injection logs
  and visible Mac-side results retained in the same evidence directory.
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
- `device-info.json` collected by `make evidence-device-info` and valid against
  `tools/schemas/device-info.schema.json`;
- `device.txt`, `host.txt`, `apk-sha256.txt`, `build.txt`, and
  `phase2-tablet-manifest.json` valid against
  `tools/schemas/phase2-tablet-manifest.schema.json`;
- `samples.jsonl` and `summary.json` for the eight-hour series, plus optional
  derived `samples.csv` when spreadsheet inspection is useful;
- `adb-battery-before.txt`, `adb-battery-after.txt`, `adb-power-before.txt`,
  `adb-power-after.txt`, thermal dumps before/after, and the corresponding
  `thermal-*.err` stderr captures;
- `raw-logcat.txt`, `host.log`, `reconnects.log`, `frame-drops.log`, and
  `decoder-telemetry.jsonl`;
- `screenshots/` for portrait, landscape, power-saver, thermal/load, reconnect,
  and end-of-run states.
- for hardware-keyboard passes, `hardware-keyboard-observations.json`,
  `hardware-keyboard-summary.json`, `dumpsys-input.txt`, `android-keyboard.log`,
  `host-keyboard.log`, `host-listener.txt`, `host-signing-and-permissions.txt`,
  `codesign-identities.txt`, and a screenshot or recording of the visible Mac
  result.

Do not mark Phase 2 accepted from this runbook unless the raw evidence exists in
the directory and the summary explains every failed or skipped gate.
