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
- final-quarter mean step no greater than 2 MiB.

The command exits zero only for `pass`; invalid, incomplete, or undersampled
evidence is `insufficient` and exits nonzero. A pass means the recorded window
did not show practically significant growth, not that longer or different
workloads cannot leak.

## Latency evidence

Prepare a CSV with either `latency_ms`, or `start_frame,end_frame,camera_fps`
from one external-camera recording, then summarize it:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency samples.csv \
  --kind glass-to-glass \
  --transport usb \
  --measurement-method external-camera \
  --output summary.json
```

Repeat the run with `--transport lan` for LAN evidence. For input latency use
`--kind input`. The tool deliberately rejects a
glass-to-glass claim based on unsynchronized host and Android clocks. Keep the
raw camera file, sample CSV, summary, device info, and a manifest together;
create the latter with `python3 -m vibescreen_evidence.manifest --help`.

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
