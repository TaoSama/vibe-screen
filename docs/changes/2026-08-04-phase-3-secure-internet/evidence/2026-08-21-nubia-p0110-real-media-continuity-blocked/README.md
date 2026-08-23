# Nubia P0110 Phase 3 real-media continuity preflight - BLOCKED

This record applies the new passive continuity evaluator to the retained
2026-08-18 blocked Host and Android logs for `nubia P0110 / pacific / Android
16 / SDK 36`. It is not a new device run and does not use Xiaomi 13/fuxi
evidence. No ADB command was executed for this derived preflight, so the
original device serial remains redacted in repository artifacts.

## Result

**BLOCKED.** The retained Host window still shows missing macOS Screen Recording
permission, and the retained Android window contains only pre-session
`TRANSPORT_CLOSED` retries. The preflight therefore records no public Internet
route, no ICE/DTLS/DataChannel completion, no Protocol v1 media epoch, no
ScreenCaptureKit or CGDisplayStream first frame, no VideoToolbox output, no
Android decoder configuration, no MediaCodec first input/output frame, and no
continuous decoder output.

The result is intentionally fail-closed and leaves every Phase 3 Internet
release gate open. It only proves that the new evaluator converts incomplete or
blocked runtime artifacts into structured blocked evidence instead of allowing a
synthetic or pre-session record to be interpreted as real media continuity.

## Evidence layout

- `real-media-continuity.json`: evaluator output produced from the retained
  2026-08-18 Host and Android log windows.
- `device-info.json`: privacy-safe device identity projection copied from the
  retained 2026-08-18 evidence.
- `commands.txt`: command ledger for this derived preflight.
- `privacy-scan.json`: deterministic privacy scan for this evidence directory.
- `SHA256SUMS`: integrity binding for every archived file except itself.

## Source artifacts

Inputs were read from:

- `../2026-08-18-nubia-p0110-current-main-real-media-blocked/host-permission-window.log`
- `../2026-08-18-nubia-p0110-current-main-real-media-blocked/android-blocked-window.log`

Those logs are retained in their original evidence directory and are referenced
by SHA-256 in `real-media-continuity.json`.
