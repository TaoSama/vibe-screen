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

Run the tests without installing third-party packages:

```sh
PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v
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
  PHASE2_STAND_SETUP="desktop stand, portrait" \
  PHASE2_CHARGER="vendor USB-C charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="Balanced, 60 FPS, AUTO bitrate" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="host build command, signing identity, and SHA" \
  PHASE2_APK_SHA256="debug or release APK SHA-256"
```

Use `PHASE2_DEVICE_CLASS=android_substitute` for Nubia P0110/pacific/Android 16
or another phone substitute. That records useful readiness data, but it cannot
close the 8-9 inch tablet gate and must not be relabeled as Xiaomi/fuxi
evidence.

```sh
make phase2-tablet-gate EVIDENCE_DIR=.build/evidence
```

The gate consumes `.build/evidence/soak-8h/exact-window-report.json` and writes
`.build/evidence/soak-8h/phase2-tablet-gate.json`. A `pass` requires an
error-free eight-hour exact window with sufficient samples, continuous stream
stats and heartbeats, no session disconnects, no reported frame drops, bounded
client and host memory growth, and battery/thermal readings below the Phase 2
thresholds. `fail` means the evidence is complete but a productization threshold
was violated; `insufficient` means the evidence cannot close the gate. The
command does not replace the raw physical-tablet, stand-mounted charging, login,
headless, and background-recovery artifacts required by the Phase 2 runbook.

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
sample CSV, summary, device info, and a manifest together; create the latter
with `python3 -m vibescreen_evidence.manifest --help`.

For a formal gate claim, validate the whole evidence directory with the stricter
external-camera provenance checker:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  latency-run/manifest.json \
  --gate-profile usb-glass-to-glass-sub50 \
  --output latency-run/latency-evidence-report.json
```

The manifest follows `tools/schemas/latency-evidence.schema.json` and must bind
the run ID, transport, profile, raw camera recording, sample file, camera mode,
device identity, build identity, and annotation method. The checker exits `0`
only when the profile verdict is `pass` and provenance is complete; missing raw
video or mismatched metadata stays `insufficient`. The step-by-step method is in
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
