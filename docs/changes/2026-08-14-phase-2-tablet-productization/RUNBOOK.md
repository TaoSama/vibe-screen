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
pgrep -f 'Vibe Screen' > host-pid.txt
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
  EVIDENCE_HOST_PID="$(cat host-pid.txt)" \
  PHASE2_RECOVERY_SCENARIOS="background_foreground,transport_reconnect"
```

If `dumpsys thermalservice` fails or writes an empty dump, keep
`thermal-before.err`, mark the thermal gate failed, and do not count the run as
Phase 2 thermal evidence. SurfaceFlinger latency-clear failures are diagnostic
only and do not invalidate the run by themselves.
`android-pid.txt` is a diagnostic process-identity snapshot for comparing the
start and end of a run; it is not a required evidence artifact.

When the physical 8-9 inch tablet is not available, still write a blocked
preflight record instead of leaving an ambiguous partial directory. Use
`PHASE2_DEVICE_CLASS=android_substitute` for the attached Nubia P0110/pacific or
another non-tablet Android device, generate the manifest, then run:

```bash
make phase2-tablet-preflight EVIDENCE_DIR="$RUN_DIR"
```

The command writes `phase2-tablet-preflight.json` and exits nonzero for
`blocked`, `insufficient`, or `fail`. That nonzero status is expected for a
phone substitute and is the evidence that the 8-9 inch tablet gate remains open.

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

## Portrait and landscape streaming UI

Record real tablet screenshots, not only synthetic 600dp instrumentation, for
both orientations:

- `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png` must show the active stream and the
  sustained-use status card.
- Open the control capsule, display picker, settings dialog, and disconnect
  affordance in each orientation. Keep screenshots or screen recordings that
  show no clipped text, overlapped controls, or unreachable buttons.
- Rotate portrait -> landscape -> portrait without recreating the Host session
  unless the scenario is explicitly testing reconnect. Record the session epoch,
  display mode, and whether touch mapping still lands on the intended Mac
  points after rotation.
- For split-screen or freeform modes available on the tablet, capture the
  smallest supported window that still claims Phase 2 readiness.

If the optional `orientation-evidence.json` is present, its top-level `status`
or `verdict` must be `pass` for the preflight checker to accept the orientation
gate.

## Physical stylus workflow

Physical stylus acceptance requires both Android capability evidence and a
human-observed drawing-app pass through the production Host path:

```bash
python3 scripts/android_stylus_acceptance.py \
  --serial "$ADB_SERIAL" \
  --output-dir "$RUN_DIR/stylus" \
  --observed-physical-drawing \
  --drawing-observation "physical stylus produced visible pressure-aware ink" \
  --host-stable-signed-tcc-ready \
  --host-log "$RUN_DIR/host-stylus.log"
cp "$RUN_DIR/stylus/stylus-evidence.json" "$RUN_DIR/stylus-evidence.json"
cp "$RUN_DIR/stylus/stylus-summary.json" "$RUN_DIR/stylus-summary.json"
```

The host log excerpt must include the stylus contact/tool/buttons/pressure/tilt
fields required by the script, and `--host-stable-signed-tcc-ready` may only be
set after `scripts/macos_dev_host.py preflight` passes for the same Host build.
Capability-only or lock-blocked stylus records are useful blocked evidence but
do not close the Phase 2 stylus gate. The
machine-readable owner is `stylus-summary.json`; only `verdict=pass` with
`can_close_physical_stylus_gate=true` may close the drawing-app gate.

## Hardware keyboard workflow

Attach the keyboard that will be used with the tablet stand setup and follow the
dedicated [hardware keyboard workflow acceptance runbook](../../runbook/hardware-keyboard-workflow.md).
The run root must include `hardware-keyboard-observations.json` and
`hardware-keyboard-summary.json`; the summary is generated with:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

The observation contract is the schema-backed boolean field set in
`tools/schemas/hardware-keyboard.schema.json`. A pass requires the physical
Android keyboard source, active selected-display stream, Protocol v1 keyboard
and USB HID modifier capability negotiation, Android production forwarding with
focus/IME boundary evidence, Host listener and stable signed/TCC readiness,
Host `Key injected:` or acknowledgement/CGEvent logs, key and modifier
press/release, shortcut behavior, modifier cleanup, retained Host/Android logs,
and a visible Mac result.
Synthetic ADB key events are not physical-keyboard evidence.

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
Use the same Host PID that was written into `phase2-tablet-manifest.json`; if
the PID changes outside an intentional restart/recovery scenario, mark the run
failed and keep the partial evidence.

```bash
make soak-8h \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  EVIDENCE_DIR="$RUN_DIR" \
  EVIDENCE_HOST_PID="$(cat host-pid.txt)"
```

A directory named `phase2-8h` closes the sustained-use gate only when
`summary.json` records `duration_seconds >= 28800`, `interval_seconds <= 60`,
and zero missing sample gaps over the measured interval. The run README must
include the exact collection commands, links to `samples.jsonl`,
`summary.json`, `phase2-tablet-manifest.json`, and raw logs, plus the measured
duration, cadence, and first-failure fields.
After the timer completes, run `make phase2-device-memory-gate` and
`make phase2-device-environment-gate` before the broader
`make phase2-tablet-gate`. The device-memory gate writes
`soak-8h/phase2-device-memory-gate.json` and must report `pass` before the
Phase 2 device-memory item can be marked covered. The device-environment gate
reads `phase2-device-environment-observations.json`, writes
`soak-8h/phase2-device-environment-summary.json`, and must report `pass` before
stand-mounted charging, controlled thermal-load recovery, or power-source
stability can close. Missing Android PSS, missing Host RSS, missing
charging/full-state samples, missing thermal status, missing power-source
measurements, missing controlled thermal-load recovery, a phone substitute such
as Nubia P0110/pacific, or a sub-eight-hour window is not a pass. The broader
tablet gate also reads the manifest and raw evidence root, so missing raw
battery, power, thermal, log, screenshot, device-environment summary, or
undeclared threshold artifacts also remain `insufficient` instead of closing
Phase 2.

The run fails immediately if the app crashes, the host crashes, the stream does
not recover after a required interruption, stale frames or stale input are
accepted after a new session epoch, Android reports severe or critical thermal
state for a sustained interval, charging cannot maintain the session on the
stand-mounted setup, or data/transport instability makes the sample series
untrustworthy. These conditions terminate collection instead of producing a
partial success. Keep the failed evidence directory, preserve logs through the
failure point, and record the earliest failure timestamp as `first_failure_at`
in `summary.json` and the run README.

The reproducible collection wrapper is `phase2-tablet-soak-preflight` for short
readiness checks and `phase2-tablet-soak-run` for the formal eight-hour
collection. Both targets require an explicit ADB serial and the declared
physical setup. The preflight target is allowed to write blocked evidence when
the current setup is not a physical tablet, lacks a Host PID, lacks Host JSONL
telemetry, or is blocked by a device lock. The formal run target fails closed:
if any precondition blocker is present, it writes `phase2-soak-readiness.json`
and does not start the eight-hour sample loop.
When either `/tmp/vibe-screen-device-android.lock` or
`/tmp/vibe-screen-device-soak.lock` already exists, the wrapper writes only the
blocked readiness record and `README.md`; it does not collect static ADB,
logcat, or soak artifacts.

For the attached Nubia P0110/pacific Android substitute, use an explicit serial
and keep the result scoped to readiness only:

```bash
make phase2-tablet-soak-preflight \
  EVIDENCE_SERIAL="<device-serial>" \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/YYYY-MM-DD-nubia-p0110-phase2-soak-preflight \
  PHASE2_DEVICE_CLASS=android_substitute \
  PHASE2_STAND_SETUP="bench substitute phone, no 8-9 inch tablet stand" \
  PHASE2_CHARGER="recorded charger for this preflight" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="preflight only" \
  PHASE2_HOST_IDENTITY="$(uname -a)" \
  PHASE2_HOST_BUILD="not stable-signed formal Host for 8h gate" \
  PHASE2_SOAK_PREFLIGHT_DURATION=2s \
  PHASE2_SOAK_INTERVAL=1s
```

Preflight may omit APK identity; the wrapper records that as a readiness-only
blocker instead of writing fake SHA-256 evidence. A formal eight-hour run must
provide `PHASE2_APK_PATH` or a real 64-character hexadecimal
`PHASE2_APK_SHA256`; otherwise the wrapper rejects the run before it can close
the Phase 2 gate.

A formal run needs a physical 8-9 inch tablet, a stand-mounted charging setup,
the signed Host process PID, and a Host started with `VIBE_SCREEN_TELEMETRY_PATH`
pointing at the run Host JSONL file:

```bash
PHASE2_HOST_TELEMETRY_JSONL="$RUN_DIR/soak-8h/host-telemetry.jsonl"
mkdir -p "$(dirname "$PHASE2_HOST_TELEMETRY_JSONL")"
osascript -e 'quit app "Vibe Screen"' || true
launchctl setenv VIBE_SCREEN_TELEMETRY_PATH "$PHASE2_HOST_TELEMETRY_JSONL"
open -n -a "Vibe Screen"

make phase2-tablet-soak-run \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  EVIDENCE_DIR="$RUN_DIR" \
  PHASE2_DEVICE_CLASS=physical_8_9_inch_tablet \
  PHASE2_TABLET_SIZE_INCHES="8.8" \
  PHASE2_STAND_SETUP="desktop stand, portrait" \
  PHASE2_CHARGER="vendor USB-C charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="Balanced, 60 FPS, AUTO bitrate" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="signed Host build, signing identity, and SHA" \
  PHASE2_HOST_PID="$HOST_PID" \
  PHASE2_HOST_TELEMETRY_JSONL="$PHASE2_HOST_TELEMETRY_JSONL" \
  PHASE2_APK_PATH=baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
```

The wrapper creates `/tmp/vibe-screen-device-soak.lock` while it owns the
device and refuses to run ADB when either that lock or
`/tmp/vibe-screen-device-android.lock` already exists. After the formal wrapper
passes the precondition checks needed to start collection, it writes
`raw-logcat.txt`, Android telemetry derivatives, before/after battery, power,
thermal dumps, Host identity, APK hash, and the manifest. A readiness result of
`blocked` is useful evidence of why the gate could not start, not a pass; a
blocked run writes `phase2-soak-readiness.json` and only the artifacts collected
before the blocker. The wrapper close contract is `phase2-soak-readiness.json` with
`can_close_phase2_gate=true` plus `soak-8h/phase2-tablet-gate.json` reporting
`verdict=pass`; README prose or placeholder hashes do not satisfy the formal
gate.

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
observed identity as Nubia P0110 / pacific / Android 16 when using the explicit
ADB serial; do not relabel this device as Xiaomi 13/fuxi or as tablet hardware.

Collect a fail-closed readiness bundle in
`evidence/YYYY-MM-DD-<device>-hardware-keyboard/` before starting the interactive
keyboard run:

```bash
make hardware-keyboard-readiness \
  EVIDENCE_SERIAL="$ADB_SERIAL" \
  EVIDENCE_DIR="$RUN_DIR"
```

The collector acquires the Android device lock, records `device-info.json`,
`dumpsys-input.txt`, `dumpsys-package.txt`, Host listener/signing/TCC preflight
artifacts, `hardware-keyboard-observations.json`, and
`hardware-keyboard-summary.json`. It exits nonzero for blocked or insufficient
readiness. That nonzero result is expected when a physical keyboard, Host
listener, or stable signed/TCC-ready Host is missing, and it must not be
converted into a pass.

Before either the wrapper or manual collection can proceed to interactive input,
retain the shared Host readiness snapshot in the same run directory and require
`host-readiness.json` to report `can_start_hardware_keyboard_gate=true`. This is
only a prerequisite to begin the hardware-keyboard run; it does not replace the
keyboard summary gate and cannot close the workflow by itself.

If collecting the artifacts manually, the equivalent commands are:

```bash
make evidence-device-info EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR="$RUN_DIR"
adb -s "$ADB_SERIAL" shell dumpsys input > "$RUN_DIR/dumpsys-input.txt"
adb -s "$ADB_SERIAL" logcat -c
adb -s "$ADB_SERIAL" reverse tcp:54321 tcp:54321
lsof -nP -iTCP:54321 -sTCP:LISTEN > "$RUN_DIR/host-listener.txt"
security find-identity -v -p codesigning > "$RUN_DIR/codesign-identities.txt"
make baseline-macos-host-readiness EVIDENCE_DIR="$RUN_DIR"
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

The default eight-hour stability gate expects zero unplanned
`session_disconnected` events. If a deliberate transport interruption is folded
into the same eight-hour run, the run README and `recovery-evidence.json` must
identify the exact planned interruption window; otherwise `phase2-tablet-gate`
will treat the disconnect as a productization failure. A cleaner evidence
package keeps the uninterrupted eight-hour soak and the destructive recovery
pass as separate directories.

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
- `soak-8h/samples.jsonl`, `soak-8h/summary.json`, and
  `soak-8h/host-telemetry.jsonl` for the eight-hour series, plus optional
  derived `samples.csv` when spreadsheet inspection is useful;
- `host-telemetry.jsonl`, `soak-8h/exact-window-report.json`,
  `soak-8h/phase2-device-memory-gate.json`,
  `soak-8h/phase2-device-environment-summary.json`, and
  `soak-8h/phase2-tablet-gate.json`;
- `phase2-device-environment-observations.json` with explicit boolean
  observations for the stand setup, eight-hour environment window, retained
  battery/power/thermal samples, controlled thermal load, thermal recovery, and
  sustained-use UI/platform agreement;
- `adb-battery-before.txt`, `adb-battery-after.txt`, `adb-power-before.txt`,
  `adb-power-after.txt`, thermal dumps before/after, and the corresponding
  `thermal-*.err` stderr captures;
- `raw-logcat.txt`, `reconnects.log`, `frame-drops.log`, and
  `decoder-telemetry.jsonl`;
- `screenshots/` for portrait, landscape, power-saver, thermal/load, reconnect,
  and end-of-run states;
- for hardware-keyboard passes or blocked readiness, `hardware-keyboard-readiness.json`,
  `hardware-keyboard-observations.json`, `hardware-keyboard-summary.json`,
  `dumpsys-input.txt`, `dumpsys-package.txt`, `android-keyboard.log` when an
  interactive run starts, `host-keyboard.log`, `host-listener.txt`,
  `host-readiness.json`, `host-signing-and-permissions.txt`,
  `codesign-identities.txt`, and a screenshot or recording of the visible Mac
  result for passing runs;
- `stylus-evidence.json`, `stylus-summary.json`, `hardware-keyboard-evidence.json`,
  `recovery-evidence.json`, `soak-8h/phase2-tablet-gate.json`, and
  `phase2-tablet-preflight.json`.

After deriving the eight-hour gate, run:

```bash
make phase2-device-environment-gate EVIDENCE_DIR="$RUN_DIR"
make phase2-tablet-gate EVIDENCE_DIR="$RUN_DIR"
make phase2-tablet-preflight EVIDENCE_DIR="$RUN_DIR"
```

Only a `phase2-tablet-preflight.json` verdict of `pass` can close the README
Phase 2 8-9 inch tablet acceptance gap. A `blocked` verdict is the expected
result when the available device is the Nubia P0110/pacific phone substitute.

After child evidence owners produce their summaries, create a current-base
aggregate owner report so the open Phase 2 workstreams have one merge owner and
README gate closure remains fail-closed:

```bash
make phase2-aggregate-owner EVIDENCE_DIR="$RUN_DIR" \
  PHASE2_TABLET_GATE="$RUN_DIR/soak-8h/phase2-tablet-gate.json" \
  PHASE2_TABLET_MANIFEST="$RUN_DIR/phase2-tablet-manifest.json" \
  PHASE2_HARDWARE_KEYBOARD="$RUN_DIR/hardware-keyboard-summary.json" \
  PHASE2_DEVICE_MEMORY="$RUN_DIR/soak-8h/phase2-device-memory-gate.json" \
  PHASE2_DEVICE_ENVIRONMENT="$RUN_DIR/soak-8h/phase2-device-environment-summary.json"
```

Add `PHASE2_DEVICE_ENVIRONMENT`, `PHASE2_SOAK_READINESS`,
`PHASE2_TABLET_UI`, `PHASE2_RECOVERY`, and `PHASE2_LOGIN_HEADLESS` when those
owner outputs exist. Missing inputs are recorded as blocked rows in
`phase2-aggregate-owner.json`. The aggregate can close README Phase 2 gates only
when every child gate reports an explicit pass or close boolean and the
package-aware tablet gate passes with `physical_8_9_inch_tablet`. A Nubia
P0110/pacific phone record must stay `android_substitute`; the aggregate layer
must not upgrade it to 8-9 inch tablet evidence.

Do not mark Phase 2 accepted from this runbook unless the raw evidence exists in
the directory and the summary explains every failed or skipped gate.
