# Vibe Screen evidence tools

This directory contains dependency-free Python tools for collecting reproducible
device evidence and summarizing externally measured latency samples. Run each
CLI with `--help` for its accepted inputs and output contract.

Evidence is data, not a pass/fail claim. In particular, glass-to-glass and
input latency must come from a single external-camera timeline. Host and device
timestamps are useful for local ordering, but are not interchangeable with an
external measurement unless their clock synchronization and uncertainty are
independently documented.

The JSON schemas in `schemas/` are versioned as `vibescreen.evidence/v1`.
Producers should write a manifest beside raw JSONL/CSV and derived summaries so
the exact command, repository state, host, device, and measurement method remain
auditable.

## iOS current-base readiness

The current-base iOS aggregate owner is PR #182. Use the aggregate gate to keep
that owner connected to the narrower signing, VideoToolbox, advanced-adapter,
AVAudioEngine/PCM, HDR, native-input, reconnect, and trusted-LAN secure-record
tasks without claiming a device pass before real iPhone and iPad evidence
exists:

```sh
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

The target writes `ios-current-base-manifest.json` and
`ios-current-base-gate.json`. The command exits `0` only for a complete formal
aggregate pass. Missing signing identities, missing iPhone/iPad hardware,
Simulator-only evidence, unsigned archives, MacHost loopback, Android evidence,
or plaintext legacy fallback produce `blocked`, `insufficient`, or `fail` with
`can_close_ios_device_acceptance=false`. That nonzero result is the expected
fail-closed readiness evidence when no iOS device run is scheduled.

Codec capability evidence must record the negotiated Protocol v1 codec, the
Host encoder capability and implementation path, the client decoder name, and
the first decoded output frame before it is used to close a codec gate. AV1 is
currently a planned codec only: offline fail-closed/admission tests and blocked
runbooks do not prove an AV1 stream.

Run the tests without installing third-party packages:

```sh
PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v
```

## iOS device acceptance gate

The iOS gate validates a sanitized `acceptance.json` after a separately
scheduled iPhone/iPad run. It is intentionally read-only: it does not invoke
Xcode, start the Host, connect to LAN, use ADB, or operate a device. A `pass`
requires both iPhone and iPad hardware records, complete signing/install,
Protocol v1 session, H.264 and HEVC VideoToolbox, input, reconnect, and audio
playback gates, plus retained local artifacts for every gate. Open or blocked
readiness records return `insufficient`; Android artifacts or identities return
`fail`.

```sh
make ios-device-acceptance-gate \
  IOS_ACCEPTANCE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-device/acceptance.json
```

## Device and soak evidence

The repository-level entry points require an explicit lease-controlled ADB
endpoint. Set it in the shell; the repository intentionally has no device
endpoint default:

```sh
export ADB_ENDPOINT='<lease-controlled-endpoint>'
make evidence-device-info EVIDENCE_SERIAL="$ADB_ENDPOINT"
make soak-30m EVIDENCE_SERIAL="$ADB_ENDPOINT"
make soak-2h EVIDENCE_SERIAL="$ADB_ENDPOINT"
make soak-8h EVIDENCE_SERIAL="$ADB_ENDPOINT"
```

### USB live-stream smoke

The read-only USB live-stream smoke collector inspects an already-running
Android streaming session without installing, launching, stopping, or
reconfiguring anything. It records device identity, the ADB reverse mapping,
the foreground Activity, the application PID, VibeScreenTelemetry events, and
MediaCodec decoder stats, then writes a structured JSON summary.

```sh
make evidence-usb-live-smoke \
  EVIDENCE_SERIAL="$ADB_ENDPOINT" \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_PORT=54321 \
  EVIDENCE_DIR=.build/evidence/usb-live-smoke
```

The tool refuses to run ADB while `/tmp/vibe-screen-device-android.lock` or
`/tmp/vibe-screen-device-soak.lock` exists unless
`--allow-existing-device-lock` is supplied. When `--write-blocked-on-lock` is
set, it writes a `blocked` summary and exits non-zero. A `pass` verdict requires
the device to be ready, the `tcp:54321` reverse mapping to be present, the
Vibe Screen package to be installed and running in the foreground, at least one
current-process `stream_stats` telemetry event with positive FPS, and active
MediaCodec decoder output from current-process `logcat` lines. Fresh sessions
may include decoder setup and first-output lines; long-running sessions may
instead prove decoder activity through continuing frame counters. The app
private diagnostic log is recorded as context only. The summary always carries
`claims.readme_gate_closure=false` and a device-identity label guard so a Nubia
P0110/pacific run can never be relabeled as Xiaomi 13/fuxi evidence. To record
a blocked summary without touching ADB when another run holds the device lock,
invoke the module directly with `--write-blocked-on-lock`.

Outputs go under `.build/evidence/` by default. Each soak writes raw JSONL and
an atomic JSON summary containing connection coverage, process liveness,
reconnects, memory, thermal, battery, power, and optional host RSS series. Use
`EVIDENCE_DIR` and `EVIDENCE_PACKAGE` to select another archive directory or
application package. A non-`complete` summary returns a nonzero exit status.
Power-supply sysfs nodes are optional diagnostics: when an Android device does
not expose them to the ADB shell, their values are recorded as unavailable and
do not make an otherwise valid soak partial. ADB transport failures still do.
Start the host with `VIBE_SCREEN_TELEMETRY_PATH` pointing at the target's
`host-telemetry.jsonl` before the formal Makefile soak. The preset targets
require at least one `stream_stats` event and require the Android process to be
alive in every sample, so an idle collector cannot be reported as a stable
stream.

For custom sampling, run `python3 -m vibescreen_evidence.soak --help` with
`PYTHONPATH=tools`. Disconnect and reconnect hooks receive
`VIBESCREEN_EVENT`, `VIBESCREEN_RUN_ID`, and `VIBESCREEN_ADB_SERIAL`; hook
commands must be supplied explicitly because interrupting ADB or the host is a
destructive test action.

After a run, derive exact-window metrics from its three raw artifacts:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report \
  --summary .build/evidence/soak-2h/summary.json \
  --samples .build/evidence/soak-2h/samples.jsonl \
  --host-telemetry .build/evidence/soak-2h/host-telemetry.jsonl \
  --output .build/evidence/soak-2h/exact-window-report.json
```

The report filters both sample and Host telemetry timestamps to the inclusive
`started_at`/`finished_at` window recorded by the summary. It preserves source
errors, reports malformed or empty inputs, and computes full-window and
second-half RSS regression slopes. Those slopes are descriptive evidence; the
tool deliberately does not turn them into a no-leak verdict.

For the Phase 1 two-hour Host RSS gate, run the separate fail-closed evaluator:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_rss_gate \
  --summary .build/evidence/soak-2h/summary.json \
  --samples .build/evidence/soak-2h/samples.jsonl \
  --output .build/evidence/soak-2h/host-rss-gate.json
```

The evaluator requires an error-free source soak of at least 7,056 seconds,
230 Host RSS samples, 115 second-half samples, samples within 90 seconds of
both window boundaries, and no internal sampling gap above 90 seconds. A pass
requires all of these steady-state limits:

- second-half OLS slope 95% upper bound no greater than 40 KiB/min;
- second-half Theil-Sen slope no greater than 40 KiB/min;
- second-half endpoint-median drift no greater than 4 MiB;
- full-window endpoint-median drift no greater than 8 MiB; and
- second-half final-quarter mean step no greater than 2 MiB.

The command exits zero only for `pass`; invalid, incomplete, or undersampled
evidence is `insufficient` and exits nonzero. A pass means the recorded window
did not show practically significant growth, not that longer or different
workloads cannot leak.

For the Phase 2 tablet productization eight-hour soak, derive the exact-window
report and then evaluate the tablet gate:

Before the timer starts, create a Phase 2 manifest that predeclares the physical
setup, device class, host/APK identity, thresholds, and planned recovery
scenarios:

```sh
make phase2-tablet-manifest EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR=.build/evidence \
  PHASE2_DEVICE_CLASS=physical_8_9_inch_tablet \
  PHASE2_TABLET_SIZE_INCHES="8.8" \
  PHASE2_STAND_SETUP="desktop stand, portrait" \
  PHASE2_CHARGER="vendor USB-C charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="Balanced, 60 FPS, AUTO bitrate" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="host build command, signing identity, and SHA" \
  PHASE2_APK_SHA256="debug or release APK SHA-256" \
  PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS=45 \
  PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT=5 \
  EVIDENCE_HOST_PID="$HOST_PID"
```

Use `PHASE2_DEVICE_CLASS=android_substitute` for Nubia P0110/pacific/Android 16
or another phone substitute. That records useful readiness data, but it cannot
close the 8-9 inch tablet gate and must not be relabeled as Xiaomi/fuxi
evidence.

Run the eight-hour soak with the same Host process ID so each sample carries
both Android app PSS and Host RSS:

```sh
make soak-8h EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR=.build/evidence \
  EVIDENCE_HOST_PID="$HOST_PID"
```

The Phase 2 device-memory gate is intentionally independent from the broader
tablet productization gate. It consumes the pre-run manifest plus the
exact-window report and fails closed when the manifest is not a physical
8-9 inch tablet, the run is shorter than eight hours, Android PSS is missing,
Host RSS is missing, charging/full-state samples are missing or not continuous,
or thermal status samples are missing:

```sh
make phase2-device-memory-gate EVIDENCE_DIR=.build/evidence
```

For an end-to-end readiness check that gathers the same raw inputs and writes an
explicit blocker record, use the wrapper target. It refuses to run ADB when an
existing device lock is present, then writes `phase2-soak-readiness.json`,
`README.md`, static device/Host artifacts, Android log derivatives, and either
`soak-preflight/` or `soak-8h/` depending on mode:

```sh
make phase2-tablet-soak-preflight EVIDENCE_SERIAL=EP0110PZ0B9110300B \
  EVIDENCE_DIR=.build/evidence/phase2-preflight \
  PHASE2_DEVICE_CLASS=android_substitute \
  PHASE2_STAND_SETUP="bench substitute phone, no 8-9 inch tablet stand" \
  PHASE2_CHARGER="recorded charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="preflight only" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="not a formal signed Host run" \
  PHASE2_APK_SHA256="readiness-only-no-apk-hash" \
  PHASE2_SOAK_PREFLIGHT_DURATION=2s \
  PHASE2_SOAK_INTERVAL=1s
```

Use `phase2-tablet-soak-run` only after the physical tablet, stand-mounted
charging setup, signed Host PID, and `VIBE_SCREEN_TELEMETRY_PATH` JSONL are all
ready. The formal target writes blocked evidence instead of starting the timer
when any required precondition is missing.

```sh
make phase2-tablet-gate EVIDENCE_DIR=.build/evidence
make phase2-tablet-preflight EVIDENCE_DIR=.build/evidence
```

The gates consume `.build/evidence/soak-8h/exact-window-report.json`,
`.build/evidence/phase2-tablet-manifest.json`, and the raw evidence files in
`.build/evidence/`, then write
`.build/evidence/soak-8h/phase2-device-memory-gate.json` and
`.build/evidence/soak-8h/phase2-tablet-gate.json`. A `pass` requires an
error-free eight-hour exact window with sufficient samples, continuous stream
stats and heartbeats, no session disconnects, no reported frame drops, bounded
Android PSS and Host RSS growth, battery/thermal readings below the Phase 2
thresholds, net battery drain within the manifest-declared limit, a manifest
declaring `physical_8_9_inch_tablet`, and the required raw
README/device/host/build/APK/battery/power/thermal/log/screenshot artifacts.
`fail` means the evidence is complete but a productization threshold was
violated; `insufficient` means the evidence package cannot close the gate. Phone
substitute manifests such as Nubia P0110/pacific/Android 16 remain useful
readiness records and intentionally evaluate as `insufficient` for the formal
8-9 inch tablet gate. The commands do not replace the raw physical-tablet,
stand-mounted charging, login, headless, and background-recovery artifacts
required by the Phase 2 runbook.

The preflight consumes the whole evidence directory and writes
`.build/evidence/phase2-tablet-preflight.json`. It is fail-closed and exits
nonzero for `blocked`, `fail`, or `insufficient`. A `pass` requires the
schema-backed manifest to identify a physical 8-9 inch tablet, portrait and
landscape tablet screenshots, physical stylus evidence, hardware-keyboard
evidence, foreground/background and transport recovery evidence, the raw
thermal/power/log artifacts, and a passing eight-hour tablet soak gate. Use it
with `PHASE2_DEVICE_CLASS=android_substitute` to create blocked evidence for the
Nubia P0110/pacific or another non-tablet Android device; that result is useful
readiness evidence but cannot close Phase 2 tablet acceptance.

### Short Host memory regression gate

Use the bounded short diagnostic as a 10-17 minute regression gate before
spending another two hours on the formal gate run. It separates live retained
growth from allocator high-water and reports a top-level `verdict` in addition
to the memory `attribution`. Start the Host with `VIBE_SCREEN_TELEMETRY_PATH`
set, establish the normal stream, find that exact Host process ID, then run:

```sh
mkdir -p .build/evidence/memory-short
# Start the Host with:
# VIBE_SCREEN_TELEMETRY_PATH=.build/evidence/memory-short/host-telemetry.jsonl
PYTHONPATH=tools python3 -m vibescreen_evidence.host_memory_diagnostic \
  --host-pid "$HOST_PID" \
  --duration-seconds 900 \
  --interval-seconds 30 \
  --telemetry-jsonl .build/evidence/memory-short/host-telemetry.jsonl \
  --samples .build/evidence/memory-short/samples.jsonl \
  --output .build/evidence/memory-short/diagnostic.json
```

The command samples RSS, `footprint` physical footprint and VM categories, and
`vmmap` malloc-zone dirty/live/fragmentation bytes every interval. It takes
`heap -q -H -s` snapshots only at the start, midpoint, and end to reduce stream
disturbance. Host `stream_stats` must cover the same wall-clock window, remain
on one session epoch, and include continuous bounded network-queue depth even
when no frame is dropped. If VideoToolbox in-flight depth is present, the
diagnostic also validates it against its advertised capacity.

The diagnostic report includes `metrics.heap_watch_summary`, which aggregates
first-to-last count and byte drift for the watched SwiftUI Observation,
autorelease-pool, and video-frame heap classes. This keeps the known Host RSS
suspects visible as structured evidence even when individual heap rows move in
or out of the top-growth list.

The report carries a top-level `verdict` with exactly three values:

- `pass`: the complete 10-17 minute window has sufficient samples, all required
  memory signals stay within the short-window stability thresholds, and stream
  telemetry plus bounded network queues stay healthy. Optional VideoToolbox
  in-flight telemetry, when present, must also stay within capacity. This is a
  short-window regression result only and cannot replace or close the formal
  two-hour `host_rss_gate`.
- `fail`: the window attributes `retained_growth` or `allocator_high_water`, or
  the production stream reports a queue over capacity, an invalid or changing
  queue capacity, optional VideoToolbox in-flight over capacity, or
  non-positive FPS.
- `insufficient`: sampling, tooling, parsing, or stream telemetry coverage is
  incomplete, or the memory signals conflict and do not support a stable or
  growth attribution.

`attribution` still has exactly three values for root-cause orientation:

- `retained_growth`: footprint, live malloc bytes, and heap objects grow together;
- `allocator_high_water`: resident allocator pages and fragmentation grow while
  live malloc bytes and heap objects stay flat;
- `inconclusive`: the short window is stable, incomplete, conflicting, or shows
  a pipeline-capacity anomaly.

Durations are restricted to 10-17 minutes so the final heap snapshot and report
remain within a 20-minute command budget. The diagnostic never invokes
`memory_pressure`, changes TCC, or accesses Keychain. Any tool error, missing
metric, missing stream telemetry coverage, session-epoch change, queue depth
above its advertised capacity, or present encoder in-flight depth above capacity
fails closed: the `verdict` becomes `insufficient` or `fail` and the
`attribution` stays `inconclusive`. The existing deterministic VideoEncoder and
mailbox tests remain the authoritative checks for the two-frame VideoToolbox
admission bound and the single-latest-frame mailbox bound.

Exit status follows the `verdict`: `0` for `pass`, `2` for `fail`, and `1` for
`insufficient`. None of these statuses is a formal two-hour gate result; a
short-window `pass` does not close the release gate. Automation must use
`host_rss_gate` for the formal two-hour no-growth decision.

There is currently no Xiaomi 13 short-window diagnostic evidence built against
this source tree, and this change introduces no new production memory fix. The
formal two-hour Host RSS no-growth gate remains open until a matching
`host_rss_gate` run reports `pass`.

## Latency evidence

Latency evidence is split by what the measurement can prove:

- `glass-to-glass`: end-to-end display latency from Mac-visible stimulus to the
  rendered Android frame. This requires one external high-frame-rate camera or
  equivalent optical timebase. Host, Android, RTT, or decoder timestamps cannot
  close this gate.
- `input`: input-event latency from physical Android input to visible Mac
  result. Prefer the same external-camera method. A synchronized-clock run is
  acceptable only when the evidence records the synchronization method and error
  budget.
- `telemetry-stage`: host or client pipeline-stage timing used to diagnose where
  latency is spent. These summaries are informational and cannot close
  glass-to-glass or input latency gates.

For glass-to-glass, prepare a CSV with either `latency_ms`, or
`start_frame,end_frame,camera_fps` from one external-camera recording, then
summarize it:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency samples.csv \
  --kind glass-to-glass \
  --transport usb \
  --measurement-method external-camera \
  --gate-profile usb-glass-to-glass-sub50 \
  --output summary.json
```

Repeat the run with `--transport lan --gate-profile lan-glass-to-glass-sub80`
for LAN evidence. For input latency use `--kind input --gate-profile
input-p95-sub50`. Gate profiles evaluate P95 with a minimum sample count and
write `verdict=pass|fail|insufficient`; omit `--gate-profile` for a pure
summary. When a gate profile is supplied the exit status follows the verdict:
`0` for `pass`, `1` for `fail` or `insufficient`. Without `--gate-profile` the
command always exits `0`. The tool deliberately rejects a glass-to-glass claim
based on unsynchronized host and Android clocks. Keep the raw camera file,
sample CSV, summary, device info, and a formal latency manifest together;
create the manifest with the dedicated helper:

    PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
      --evidence-dir latency-run \
      --latency-kind glass-to-glass \
      --transport usb \
      --gate-profile usb-glass-to-glass-sub50 \
      --raw-video latency-run/raw-camera.mov \
      --samples latency-run/samples.csv \
      --samples-format csv \
      --annotation-method manual-frame-count \
      --camera-manufacturer "camera vendor" \
      --camera-model "camera model" \
      --camera-mode 1080p240 \
      --camera-frame-rate-fps 240 \
      --camera-shutter-mode fixed \
      --operator "operator name" \
      --annotator "annotator name" \
      --device-info latency-run/device-info.json \
      --host-artifact "host binary identity or hash" \
      --client-artifact "APK identity or hash" \
      --stimulus "visible Mac-side stimulus" \
      --start-event-definition "first camera frame where the stimulus is visible" \
      --end-event-definition "first camera frame where the result is visible" \
      --lighting "lighting conditions" \
      --mounting "camera and device mounting" \
      --max-frame-annotation-uncertainty-ms 4.2 \
      --notes "run-specific notes"

For a formal gate claim, validate the whole evidence directory with the stricter
latency provenance checker:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  latency-run/manifest.json \
  --gate-profile usb-glass-to-glass-sub50 \
  --output latency-run/latency-evidence-report.json
```

The manifest follows `tools/schemas/latency-evidence.schema.json` and must bind
the run ID, transport, profile, sample file, device identity, build identity,
and annotation method. External-camera packages also bind the raw camera
recording and camera mode; synchronized-clock input packages bind the clock
sources, skew, drift, timestamp methods, and sub-5 ms total error budget. The
checker exits `0` only when the profile verdict is `pass` and provenance is
complete; missing raw video, mismatched metadata, or incomplete synchronization
proof stays `insufficient`. The step-by-step method is in
`docs/runbook/latency-measurement.md`.

For telemetry-stage diagnostics, prepare rows with `stage,latency_ms` and mark
the clock domain explicitly:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency host-stages.csv \
  --kind telemetry-stage \
  --transport usb \
  --measurement-method host-telemetry \
  --output host-stage-summary.json
```

Use `--measurement-method client-telemetry` for Android decoder or render-stage
samples. The output has `status=informational` and
`gate.can_close_performance_gate=false`; keep it next to the camera/input
evidence to explain bottlenecks, not as a substitute for external measurement.
Synthetic CLI fixtures live in `tools/fixtures/latency/` and cover pass, fail,
insufficient, input, and telemetry-stage behavior. They are test data only, not
acceptance evidence.

## Troubleshooting

- `device ... not ready`: run `adb connect <serial>` and confirm the exact
  manufacturer/model/fingerprint before testing.
- Missing process metrics: install and start the package passed through
  `EVIDENCE_PACKAGE`; the run remains usable but is marked partial.
- Thermal entries vary by vendor. The collector archives every readable zone
  instead of assuming Xiaomi-specific names.
- A black Android `screencap` does not prove a black stream: hardware-decoded
  secure/overlay surfaces may be absent from screenshots. Use an external
  camera for visual and end-to-end latency evidence.
