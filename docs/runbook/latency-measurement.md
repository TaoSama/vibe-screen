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

## Evidence directory

Store each run in an immutable directory with these files:

    latency-run/
      manifest.json
      raw-camera.mov
      samples.csv
      summary.json
      latency-evidence-report.json
      device-info.json
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

For LAN glass-to-glass, use `--transport lan` with `lan-glass-to-glass-sub80`.
For input latency, use `--kind input` with `input-p95-sub50`. The checker exits 0 only
when the profile verdict is pass and required external-camera provenance is
complete. Missing raw video, mismatched manifest fields, changed sample
annotations, frame-rate mismatches, annotation uncertainty that crosses the
threshold, too few samples, wrong transport, or a threshold miss all return
nonzero with a JSON report whose verdict is insufficient or fail. Referenced
files must use package-relative paths and stay inside the evidence directory.

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

The current formal provenance checker validates external-camera packages only.
Until a synchronized-clock manifest schema and checker path exist, a
synchronized-clock input run must keep its `vibescreen_evidence.latency` summary
with the synchronization proof and must be reviewed manually before it can be
used as acceptance evidence.

## Claim boundary

A pass applies only to the recorded device, transport, build, camera setup, and
sample window. Telemetry-stage summaries, decoder timings, RTT, screen
recordings, screenshots, and unsynchronized host/device timestamps can explain
latency sources, but they do not close USB/LAN glass-to-glass or input-latency
gates.
