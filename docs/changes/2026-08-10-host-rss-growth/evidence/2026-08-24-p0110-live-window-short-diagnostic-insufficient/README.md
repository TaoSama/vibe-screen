# 2026-08-24 P0110 live-window Host RSS diagnostic: insufficient

Created: 2026-08-24T11:11:11Z
Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial <device-serial>
Host PID: 22385

## Verdict

INSUFFICIENT for Host RSS gate closure. The live stream window was useful as a
read-only diagnostic sample, but it was not a current-source, stable-signed,
TCC-verified Host launched with `VIBE_SCREEN_TELEMETRY_PATH`, and the retained
telemetry was reconstructed from the installed app log rather than emitted by
the new structured lifecycle telemetry path.

This record does not close the short Host memory diagnostic gate and does not
close the formal two-hour Host RSS no-growth gate. The README Phase 0 gate
remains open until a complete two-hour run from a matching current-source Host
is evaluated by `host_rss_gate` with `verdict=pass`.

## Live window facts

These facts were captured in read-only follow-up checks at
2026-08-24T11:27:51Z, after the diagnostic window completed, and are retained
as artifacts in this directory.

- `/Applications/Vibe Screen.app` was still running as PID 22385.
- `lsof -nP -p 22385 -iTCP:54321 -sTCP:LISTEN` showed the Host listening on
  `127.0.0.1:54321`.
- The Host process environment did not contain `VIBE_SCREEN_TELEMETRY_PATH`; it
  did report `__CFBundleIdentifier=dev.telemachus.display`.
- Installed Host executable SHA-256 was
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`.
- `adb -s <device-serial> reverse --list` reported
  `UsbFfs tcp:54321 tcp:54321`.
- `adb -s <device-serial> shell pidof dev.telemachus.display` reported
  Android process 15457. `window-focus.txt` records
  `dev.telemachus.display/.MainActivity` as the focused app/activity.
- Device identity was recorded as nubia / P0110 / pacific / Android 16 / SDK 36.

## Diagnostic result

`vibescreen_evidence.host_memory_diagnostic` ran from 2026-08-24T11:11:11Z to
2026-08-24T11:21:31Z with 21 memory samples and exited non-zero because the
diagnostic was intentionally fail-closed. The JSON report says:

- `verdict`: `insufficient`
- `attribution`: `inconclusive`
- `reasons`: `required short-run samples or telemetry are incomplete`
- `sufficiency.stream_telemetry`: `false`
- `telemetry.coverage_complete`: `false`
- `telemetry.stream_stats_count`: `0`
- `telemetry.total_stream_stats_count`: `259`
- `telemetry.invalid_record_count`: `259`

The re-encoded log records preserve the observed stream cadence (`fps` near 60,
zero dropped frames in the tail samples), but they do not carry required
diagnostic fields such as queue depth/capacity, session epoch, encoder
in-flight state, frame registry count, latest pixel-buffer retention, fallback
capture state, or encoder presence. The diagnostic therefore correctly refuses
to infer bounded frame lifecycle health from this window.

Memory-side signals in this short window were not independently concerning
(`rss_bytes.endpoint_median_drift` was -9699328 bytes;
`physical_footprint_bytes.endpoint_median_drift` was 65560 bytes), but those
numbers are diagnostic only. They do not prove the two-hour no-growth gate.

## Files

- `commands.txt` - command ledger and exit codes.
- `diagnostic.json` - fail-closed short diagnostic report.
- `samples.jsonl` - 21 Host memory samples.
- `reencoded-host-telemetry.jsonl` - 273 stream-stat-like records reconstructed
  from the installed app log; the diagnostic window counted 259 of them.
- `host-log-telemetry-stderr.txt` - warnings from log tailing; repeated stale-log
  warnings explain why the re-encoded stream telemetry was incomplete for gate
  purposes.
- `host-process.txt`, `host-listener.txt`, `host-env-selected.txt`, and
  `installed-host-sha256.txt` - retained Host process, listener, selected
  environment, and installed binary hash observations.
- `device-info.txt`, `adb-reverse.txt`, `android-pid.txt`, and
  `window-focus.txt` - retained P0110 identity, USB reverse, Android process,
  and focus observations.

## Required rerun

For a useful short diagnostic, launch a stable-signed current-source Host with
Screen Recording and Accessibility grants and set:

    export VIBE_SCREEN_TELEMETRY_PATH="$EVIDENCE_DIR/host-telemetry.jsonl"

Then establish a fresh P0110 USB stream and run the short diagnostic against the
matching Host PID. For formal gate closure, run the full `soak-2h-host-rss-gate`
path and retain the resulting `host-rss-gate.json` with `verdict=pass`.
