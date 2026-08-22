# 2026-08-21 Nubia P0110 latency preflight: blocked

This record refreshes the README external latency gates on origin/main commit
`cc26a84c829016fa61c721f73a128284fdf64f92` with the connected Android
acceptance substitute recorded as `nubia-p0110-pacific-device-1`. The preflight
was collected on 2026-08-20 UTC and published under the 2026-08-21 evidence
directory.

## Verdict

BLOCKED for formal performance-gate closure. The attached Nubia P0110/pacific
device is reachable over ADB and its identity is recorded in `device-info.json`,
but this evidence directory intentionally contains no external-camera recording,
no annotated camera-frame samples, and no formal latency manifest. Therefore it
does not close any of these profiles:

- `usb-glass-to-glass-sub50`
- `lan-glass-to-glass-sub80`
- `input-p95-sub50`

No host/client telemetry, decoder timing, RTT, screen recording, or ADB-driven
synthetic input was used as a substitute for external latency evidence.

## Device preflight

The connected Android device reported:

- Manufacturer: `nubia`
- Model: `P0110`
- Codename/product: `pacific`
- OS: Android `16`, SDK `36`
- Evidence device id: `nubia-p0110-pacific-device-1`

The device check used the required explicit serial form; committed records redact
the raw ADB serial and use the pseudonymous device id through `$ADB_SERIAL`:

```bash
ADB_SERIAL=nubia-p0110-pacific-device-1
adb -s "$ADB_SERIAL" get-state
PYTHONPATH=tools python3 -m vibescreen_evidence.device_info \
  --serial "$ADB_SERIAL" \
  --no-connect \
  --output docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-21-nubia-p0110-latency-preflight-blocked/device-info.json
```

## Blocker

The required measurement hardware and artifacts were not available in this
worktree session:

- a high-frame-rate external camera or optical measurement device framing both
  the Mac stimulus and Android result on one timebase;
- at least five annotated USB glass-to-glass samples from that recording;
- at least five annotated LAN glass-to-glass samples from that recording;
- for input latency, either physical input actuation and visible Mac result in
  that same camera timebase, or a documented synchronized-clock setup with a
  sub-5 ms total error budget.

## Reproducible next step

After recording `raw-camera.mov` and annotating `samples.csv`, generate a
schema-compatible external-camera manifest with:

```bash
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
  --evidence-dir "$EVIDENCE_DIR" \
  --latency-kind glass-to-glass \
  --transport usb \
  --gate-profile usb-glass-to-glass-sub50 \
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
  --notes "run-specific notes"
```

Then run the summary and formal checker commands from
`docs/runbook/latency-measurement.md`. For LAN, switch the transport/profile to
`lan` and `lan-glass-to-glass-sub80`. For synchronized-clock input latency, use
that runbook path with `--measurement-method synchronized-clock`, real physical
input timing evidence, and a reviewable sub-5 ms synchronization error budget.

## Artifacts

- `device-info.json`: ADB identity for Nubia P0110/pacific.
- `readiness-report.json`: machine-readable blocked status for all three
  latency profiles.
- `commands.txt`: commands run during this preflight and their outcomes.

## Boundary

This record is a preflight/blocker record only. It proves the Android target was
reachable and records exactly why the latency gates remain open; it does not
measure USB glass-to-glass, LAN glass-to-glass, or input latency.
