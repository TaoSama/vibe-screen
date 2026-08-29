# P0110 Android audio current-base blocked evidence - 2026-08-28

Status: blocked before real USB/LAN audio playback acceptance
Device: `nubia P0110 / pacific / Android 16 / SDK 36`
ADB serial: `<ANDROID_SERIAL>`
Source commit: `20cd27b1d59dfcc66e28df41aba421e14b6171f4` (`origin/main` at branch creation)

## Goal

Re-check the current `origin/main` baseline for the Protocol v1 Android audio
playback gate using the connected P0110 as a general Android substitute. A
passing record still requires a real USB or trusted-LAN production session with
a stable signed Microphone/TCC-ready macOS Host, negotiated
`CAPABILITY_AUDIO`, accepted PCM S16LE `AudioConfig`, Host channel `3` audio
packet flow, Android production `AudioTrack` start/write evidence, audible or
instrumentation-backed playback confirmation, and cleanup on disconnect or
reconfiguration.

## Observed state

- `device-info.json` records `nubia P0110 / pacific / Android 16 / SDK 36`;
  this evidence must not be relabeled as Xiaomi 13/fuxi.
- `device-lock-acquired.txt` records ownership of
  `/tmp/vibe-screen-device-android.lock` for read-only collection.
- `adb-reverse-list.txt` records `UsbFfs tcp:54321 tcp:54321`.
- `usb-live-smoke.json` records the Android app installed, foreground, and
  receiving a USB video stream. This is USB/video evidence only.
- `host-54321-listener.txt` records a Host listener on TCP `54321`.
- `macos-dev-host-preflight-current-base.txt` and
  `macos-dev-host-readiness-current-base.txt` fail closed: the configured
  stable local signing identity is unavailable, the installed Host lacks source
  commit/tree provenance, and read-only TCC inspection cannot prove
  Microphone readiness.
- `host-info-plist.txt` shows the installed Host bundle does not contain
  `NSMicrophoneUsageDescription`, while current source does; this indicates the
  installed Host bundle predates the current audio-capable packaging path.
- `android-audio-diag.txt`, `android-audio-logcat.txt`, and
  `audio-log-search.txt` contain video/session context but no retained
  `CAPABILITY_AUDIO`, `AudioConfig`, `AudioTrack` start/write,
  `audio_capture_started`, microphone capture, or channel `3` packet evidence.
- `android-network.txt` records `wlan0` with no carrier, so trusted-LAN audio
  was not runnable in this environment.
- `sfltool-start.txt` and `sfltool-end.txt` were captured with
  `pgrep -x sfltool || true`; no `/usr/bin/sfltool dumpbtm` or login-item
  diagnostic opt-in was run.

## Gate result

`android-audio-playback-summary.json` reports:

- `verdict=blocked`
- `can_close_android_audio_playback_gate=false`
- blocking field: `host_stable_signed_tcc_ready`

Additional missing pass requirements include current-source Host build
identity, `CAPABILITY_AUDIO` negotiation, accepted PCM S16LE `AudioConfig`,
Host microphone capture, Host channel `3` packet flow, Android `AudioTrack`
start/write evidence, playback output confirmation, disconnect cleanup, and
retained Host packet-flow logs.

This is a fail-closed current-base readiness record only. It does not close the
real USB or trusted-LAN audio playback gate.
