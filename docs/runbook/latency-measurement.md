# External-camera latency measurement

This runbook defines the minimum evidence package for USB/LAN
glass-to-glass and input-latency claims. It does not record a pass by itself;
it makes real high-frame-rate samples auditable and fail-closed.

## Capture setup

Use one external camera or optical measurement device as the only timebase.
Record the Mac display and Android device in the same frame so the start and
end events are visible without relying on host or device clocks. Use at least
120 FPS; 240 FPS or higher is preferred because a single-frame annotation error
is already about 4.2 ms at 240 FPS.

For glass-to-glass, make the start event a visible Mac-side stimulus such as a
full-screen black/white transition, frame counter change, or cursor movement.
Make the end event the first camera frame where the Android render shows the
same visual change. For input latency, make the start event the physical input
contact or HID actuation visible to the camera, and the end event the first
visible Mac-side result. Keep input claims scoped to real physical input; ADB
or synthetic events are mapper diagnostics, not input-latency evidence.

## Capture procedure

Before the run, lock the camera exposure, focus, shutter mode, frame rate, and
white balance so frame boundaries stay readable across the full sample window.
Mount the camera, Mac display, and Android device so both endpoint events are in
one stable frame; do not hand-hold the camera or move either display after the
first calibration clip. Record `adb -s EP0110PZ0B9110300B shell getprop` or the
equivalent device-info helper output next to the run, and keep the device label
as Nubia P0110/pacific/Android 16 when that serial is used.

For USB glass-to-glass, start the macOS host and Android client over ADB reverse,
then record at least five visible Mac stimulus transitions and their matching
Android render results in one raw camera file. For LAN glass-to-glass, remove
the ADB reverse dependency, confirm the LAN session is active, and repeat the
same visible transition sampling with the LAN gate profile. For input latency,
record real physical touch, stylus, keyboard, or mouse actuation and the first
visible Mac-side result; do not use ADB-generated input as the start event.

Annotate `samples.csv` from the raw recording only after capture. Use the first
frame where the start event is visible and the first frame where the result is
visible; if either boundary is ambiguous, record the worst-case endpoint
uncertainty in the manifest. Keep failed, insufficient, and interrupted runs in
their own evidence directories so the blocked reason is auditable rather than
silently replaced by a later attempt.

## Evidence directory

Store each run in an immutable directory with these files:

    latency-run/
      manifest.json
      raw-camera.mov
      samples.csv
      summary.json
      latency-evidence-report.json
      device-info.json
      usb-connection.txt
      commands.txt

The sample file contains either direct latency_ms rows or frame deltas from
the one camera timeline:

    start_frame,end_frame,camera_fps
    100,111,240
    240,251,240

The formal manifest uses tools/schemas/latency-evidence.schema.json and binds
the raw recording, sample file, transport, gate profile, build, host, device,
and annotation method. A minimal shape is:

    {
      "schema_version": "vibescreen.evidence/v1",
      "run_id": "2026-08-19-usb-latency-example",
      "latency_kind": "glass-to-glass",
      "transport": "usb",
      "measurement_method": "external-camera",
      "gate_profile": "usb-glass-to-glass-sub50",
      "camera": {
        "manufacturer": "camera vendor",
        "model": "camera model",
        "mode": "1080p240",
        "frame_rate_fps": 240,
        "shutter_mode": "fixed"
      },
      "recording": {
        "raw_video": "raw-camera.mov",
        "recorded_at": "2026-08-19T00:00:00Z",
        "operator": "operator name",
        "sha256": "raw video sha256"
      },
      "samples": {
        "file": "samples.csv",
        "format": "csv",
        "sha256": "sample annotations sha256",
        "annotation_method": "manual-frame-count",
        "annotator": "annotator name"
      },
      "gate_artifacts": {
        "usb_connection": {
          "file": "usb-connection.txt",
          "sha256": "USB connection artifact sha256",
          "description": "ADB reverse/USB setup and active USB stream proof"
        }
      },
      "device": {
        "manufacturer": "device manufacturer",
        "model": "device model",
        "codename": "device codename",
        "os_version": "Android version"
      },
      "host": {
        "model": "Mac model",
        "macos_version": "macOS version"
      },
      "build": {
        "repository_revision": "git revision",
        "host_artifact": "host binary identity or hash",
        "client_artifact": "APK identity or hash"
      },
      "measurement_setup": {
        "stimulus": "visible stimulus used for this run",
        "start_event_definition": "first camera frame where the start event is visible",
        "end_event_definition": "first camera frame where the result is visible",
        "lighting": "lighting conditions",
        "mounting": "camera and device mounting",
        "clock_domain": "single-external-camera-timebase",
        "max_frame_annotation_uncertainty_ms": 4.2,
        "notes": "run-specific notes"
      }
    }

The field `max_frame_annotation_uncertainty_ms` is the maximum uncertainty for
one annotated endpoint frame. The checker applies it to both the start and end
frames before comparing P95 against the gate threshold.

The `gate_artifacts` object is profile-specific. Use `usb_connection` for
`usb-glass-to-glass-sub50`, `lan_network_preflight` for
`lan-glass-to-glass-sub80`, and `input_actuation_record` for
`input-p95-sub50`. Synchronized-clock input packages must also include a
`synchronization_record` artifact containing the clock-alignment transcript,
skew checks, drift check, and error-budget derivation. Each entry must point to
a retained package-relative file with a matching SHA-256 digest.

After collecting raw-camera.mov, samples.csv, and device-info.json, create the
manifest with the dedicated helper instead of adapting the generic evidence
manifest tool:

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
      --gate-artifact latency-run/usb-connection.txt \
      --gate-artifact-description "ADB reverse/USB setup and active USB stream proof" \
      --notes "run-specific notes"

## Commands

First summarize the samples with the matching profile:

    PYTHONPATH=tools python3 -m vibescreen_evidence.latency latency-run/samples.csv \
      --kind glass-to-glass \
      --transport usb \
      --measurement-method external-camera \
      --gate-profile usb-glass-to-glass-sub50 \
      --run-id 2026-08-19-usb-latency-example \
      --output latency-run/summary.json

Then validate the formal evidence package:

    PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
      latency-run/manifest.json \
      --gate-profile usb-glass-to-glass-sub50 \
      --output latency-run/latency-evidence-report.json

For LAN glass-to-glass, use the same package shape with the LAN transport proof:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
  --evidence-dir "$EVIDENCE_DIR" \
  --latency-kind glass-to-glass \
  --transport lan \
  --gate-profile lan-glass-to-glass-sub80 \
  --raw-video "$EVIDENCE_DIR/raw-camera.mov" \
  --samples "$EVIDENCE_DIR/samples.csv" \
  --samples-format csv \
  --annotation-method manual-frame-count \
  --camera-manufacturer "camera vendor" \
  --camera-model "camera model" \
  --camera-mode 1080p240 \
  --camera-frame-rate-fps 240 \
  --camera-shutter-mode fixed \
  --operator "operator name" \
  --annotator "annotator name" \
  --device-info "$EVIDENCE_DIR/device-info.json" \
  --host-artifact "host binary identity or hash" \
  --client-artifact "APK identity or hash" \
  --stimulus "visible Mac-side stimulus" \
  --start-event-definition "first camera frame where the stimulus is visible" \
  --end-event-definition "first camera frame where the Android result is visible" \
  --lighting "lighting conditions" \
  --mounting "camera and device mounting" \
  --max-frame-annotation-uncertainty-ms 4.2 \
  --gate-artifact "$EVIDENCE_DIR/lan-network-preflight.txt" \
  --gate-artifact-description "LAN network preflight and active trusted-LAN stream proof" \
  --notes "run-specific notes"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency "$EVIDENCE_DIR/samples.csv" \
  --kind glass-to-glass \
  --transport lan \
  --measurement-method external-camera \
  --gate-profile lan-glass-to-glass-sub80 \
  --run-id "$RUN_ID" \
  --output "$EVIDENCE_DIR/summary.json"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile lan-glass-to-glass-sub80 \
  --output "$EVIDENCE_DIR/latency-evidence-report.json"
```

For Internet glass-to-glass, use `--transport internet` with
`internet-glass-to-glass-sub150` and add the public-route manifest fields.
`--turn-resolved-ip` must be the retained global IP from resolving the selected
TURN hostname during the run. The Internet manifest must also retain a
profile-specific `internet_public_route_record` artifact through
`--gate-artifact`:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
  --evidence-dir "$EVIDENCE_DIR" \
  --latency-kind glass-to-glass \
  --transport internet \
  --gate-profile internet-glass-to-glass-sub150 \
  --raw-video "$EVIDENCE_DIR/raw-camera.mov" \
  --samples "$EVIDENCE_DIR/samples.csv" \
  --samples-format csv \
  --annotation-method manual-frame-count \
  --camera-manufacturer "camera vendor" \
  --camera-model "camera model" \
  --camera-mode 1080p240 \
  --camera-frame-rate-fps 240 \
  --camera-shutter-mode fixed \
  --operator "operator name" \
  --annotator "annotator name" \
  --device-info "$EVIDENCE_DIR/device-info.json" \
  --host-artifact "host binary identity or hash" \
  --client-artifact "APK identity or hash" \
  --stimulus "visible Mac-side stimulus" \
  --start-event-definition "first camera frame where the stimulus is visible" \
  --end-event-definition "first camera frame where the Android result is visible" \
  --lighting "lighting conditions" \
  --mounting "camera and device mounting" \
  --max-frame-annotation-uncertainty-ms 4.2 \
  --gate-artifact "$EVIDENCE_DIR/internet-public-route-record.txt" \
  --gate-artifact-description "public TURN route, remote peer, ICE pair, and non-LAN topology proof" \
  --notes "run-specific notes" \
  --internet-route forced-public-turn \
  --turn-provider "provider" \
  --turn-region "region" \
  --turn-public-hostname "turn.example.net" \
  --turn-resolved-ip "$TURN_RESOLVED_IP" \
  --turn-tls turns \
  --turn-credential-source "authority-issued short-lived credential" \
  --remote-peer-operator "remote tester" \
  --remote-peer-network "remote carrier or ISP" \
  --remote-peer-public-ip-asn "AS number" \
  --remote-peer-location "city, country" \
  --local-candidate-type relay \
  --remote-candidate-type relay \
  --relay-protocol turn-tls \
  --host-network "host ISP" \
  --device-network "remote carrier or ISP" \
  --different-private-network

PYTHONPATH=tools python3 -m vibescreen_evidence.latency "$EVIDENCE_DIR/samples.csv" \
  --kind glass-to-glass \
  --transport internet \
  --measurement-method external-camera \
  --gate-profile internet-glass-to-glass-sub150 \
  --run-id "$RUN_ID" \
  --output "$EVIDENCE_DIR/summary.json"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile internet-glass-to-glass-sub150 \
  --output "$EVIDENCE_DIR/latency-evidence.json"
```

For external-camera input latency, use `--kind input` with
`input-p95-sub50` and make `--gate-artifact` point at the physical input
actuation proof:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency "$EVIDENCE_DIR/samples.csv" \
  --kind input \
  --transport usb \
  --measurement-method external-camera \
  --gate-profile input-p95-sub50 \
  --run-id "$RUN_ID" \
  --output "$EVIDENCE_DIR/summary.json"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile input-p95-sub50 \
  --output "$EVIDENCE_DIR/latency-evidence-report.json"
```

The checker exits 0 only when the profile verdict is pass and the required
external-camera or synchronized-clock provenance is complete. Missing raw
video, mismatched manifest fields, changed sample annotations, frame-rate
mismatches, annotation uncertainty or clock error budget that crosses the
threshold, too few samples, wrong transport, missing profile artifact, or a
threshold miss all return nonzero with a JSON report whose verdict is
insufficient or fail. Referenced files must use package-relative paths and stay
inside the evidence directory.

For committed evidence directories, the Make wrapper runs the same formal
checker and writes the canonical report name in place:

```bash
make evidence-latency-gate \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  LATENCY_GATE_PROFILE=usb-glass-to-glass-sub50
```

Set `LATENCY_MANIFEST` only when the manifest is not
`$EVIDENCE_DIR/manifest.json`; otherwise leave it at the default. The target
returns `0` only when `latency-evidence-report.json` records `verdict=pass`.

## Fail-closed readiness preflight

When external-camera hardware, synchronized-clock proof, physical input
actuation, or transport proof is not ready, record that blocked state before
leaving the gate. Create `preflight-input.json` with the checks that are known
true and leave missing checks false, then run:

```bash
make evidence-latency-preflight \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  LATENCY_DEVICE_INFO="$EVIDENCE_DIR/device-info.json" \
  LATENCY_PREFLIGHT_INPUT="$EVIDENCE_DIR/preflight-input.json" \
  LATENCY_REPOSITORY_REVISION="$(git rev-parse origin/main)"
```

A reusable input template is available at
`tools/fixtures/latency/preflight-input.template.json`. The target writes `latency-preflight.json` and
`latency-preflight-exit.txt`. Exit `0` means the declared artifacts are ready
for a formal checker attempt, exit `2` means the run is blocked before formal
gate closure, and exit `1` means malformed input or evaluation failures.
When `formal_manifest_retained` is true for a profile, the matching formal
latency `gate_profiles[].manifest` path must also be present in `preflight-input.json`;
otherwise the preflight stays blocked because there is no formal package for
the checker to validate.
This readiness record cannot close `usb-glass-to-glass-sub50`,
`lan-glass-to-glass-sub80`, or `input-p95-sub50`; it only preserves why the
gate is still open.

## Synchronized-clock input latency

The synchronized-clock path is only for the `input-p95-sub50` profile. It is
not accepted for USB or LAN glass-to-glass gates, because those require one
external camera or optical timebase that sees both the Mac stimulus and the
Android render result.

Use `--measurement-method synchronized-clock` only when the evidence package
also contains a reviewable synchronization record: the host and Android clock
sources, the synchronization procedure, before/after skew checks, drift over
the measurement window, and a worst-case error budget. The total timing error
budget must be less than 5 ms, which is 10% of the sub-50 ms P95 input gate, or
the claim remains `insufficient` even if the raw P95 is below 50 ms.

A synchronized-clock input run still needs a real physical input event and a
visible Mac-side result. Before sampling, record a before-skew measurement,
perform the synchronization procedure, record an after-skew measurement, and
repeat a drift check after the sample window. The manifest's total error budget
must conservatively cover the remaining skew, drift, timestamp capture
resolution, and trigger-detection uncertainty; if any component is guessed or
omitted, the run remains blocked.

The formal provenance checker now validates synchronized-clock input packages.
The manifest generator can build this path with `--measurement-method
synchronized-clock`; it sets `measurement_setup.clock_domain` to
`synchronized-host-device-clocks`, omits the external-camera-only `camera` and
`recording` sections, and writes the required `synchronization` section. That
section must provide:

- `host_clock_source` and `device_clock_source`: the clock domains used on each
  side.
- `sync_procedure`: how the two clocks were aligned before the run.
- `before_skew_ms`, `after_skew_ms`, and `max_drift_ms`: measured skew and
  drift over the measurement window.
- `total_error_budget_ms`: the worst-case timing error, which must be less
  than 5 ms.
- `input_timestamp_method` and `result_timestamp_method`: how the physical
  input actuation and the visible Mac result were timestamped.

The checker applies `total_error_budget_ms` directly to the observed P95
(rather than doubling it, as it does for per-frame camera annotation
uncertainty). A pass requires `p95 + total_error_budget_ms <= 50 ms`.

After collecting direct-latency samples and synchronization evidence, generate
the manifest, then run the summarizer and checker:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
  --evidence-dir "$EVIDENCE_DIR" \
  --measurement-method synchronized-clock \
  --latency-kind input \
  --transport usb \
  --gate-profile input-p95-sub50 \
  --samples "$EVIDENCE_DIR/samples.csv" \
  --samples-format csv \
  --annotation-method direct-latency-ms \
  --annotator "annotator name" \
  --device-info "$EVIDENCE_DIR/device-info.json" \
  --host-artifact "host binary identity or hash" \
  --client-artifact "APK identity or hash" \
  --stimulus "physical input actuation" \
  --start-event-definition "physical input timestamp source" \
  --end-event-definition "visible Mac result timestamp source" \
  --lighting "n/a for synchronized-clock" \
  --mounting "n/a for synchronized-clock" \
  --host-clock-source "host clock source" \
  --device-clock-source "device clock source" \
  --sync-procedure "clock synchronization procedure" \
  --before-skew-ms 1.2 \
  --after-skew-ms 1.5 \
  --max-drift-ms 0.8 \
  --total-error-budget-ms 3.5 \
  --input-timestamp-method "physical input timestamp method" \
  --result-timestamp-method "visible result timestamp method" \
  --gate-artifact "$EVIDENCE_DIR/input-actuation.txt" \
  --gate-artifact-description "physical input actuation and visible Mac result proof" \
  --synchronization-artifact "$EVIDENCE_DIR/synchronization-record.txt" \
  --synchronization-artifact-description "clock sync transcript, skew checks, drift check, and error-budget derivation" \
  --notes "run-specific notes"
```

Then run the summary and checker commands:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency "$EVIDENCE_DIR/samples.csv" \
  --kind input \
  --transport usb \
  --measurement-method synchronized-clock \
  --gate-profile input-p95-sub50 \
  --run-id "$RUN_ID" \
  --output "$EVIDENCE_DIR/summary.json"

PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  "$EVIDENCE_DIR/manifest.json" \
  --gate-profile input-p95-sub50 \
  --output "$EVIDENCE_DIR/latency-evidence-report.json"
```

A valid synchronized-clock fixture lives at
`tools/fixtures/latency/synchronized-clock-input-valid/`. It exercises the
checker path and is not real-device evidence.

## Claim boundary

A pass applies only to the recorded device, transport, build, camera setup, and
sample window. Telemetry-stage summaries, decoder timings, RTT, screen
recordings, screenshots, and unsynchronized host/device timestamps can explain
latency sources, but they do not close USB/LAN glass-to-glass or input-latency
gates.
