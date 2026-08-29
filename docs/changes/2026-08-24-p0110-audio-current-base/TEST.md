# P0110 Android audio current-base owner

Status: current-base Android owner recorded; real USB/LAN audio playback blocked
Date: 2026-08-28
Source branch: `codex/audio-playback-current-base`
Base commit: `20cd27b1d59dfcc66e28df41aba421e14b6171f4` (`origin/main` at branch creation)

## Scope

This record establishes the current-base Android/P0110 owner for the README
Protocol v1 USB/LAN audio playback gate. It does not change the product audio
path from the merged Host-to-Android PCM S16LE microphone-capture wiring. The
gate still requires real-device playback evidence from the production session:
`CAPABILITY_AUDIO`, accepted PCM S16LE `AudioConfig`, Host channel `3` packet
flow, Android `AudioTrack` start/write evidence, audible or
instrumentation-backed playback confirmation, and disconnect cleanup.

## PR audit

| PR | Status | Audio-gate effect |
| --- | --- | --- |
| [#305](https://github.com/TaoSama/vibe-screen/pull/305) | Merged | Implements Protocol v1 USB/LAN Host-to-Android microphone PCM wiring and offline Host/Android/LAN secure-record tests. It explicitly leaves real USB and trusted-LAN audio playback evidence open. |
| [#197](https://github.com/TaoSama/vibe-screen/pull/197) | Closed | Earlier audio wiring attempt with the same real-device blockers; not a merged current-base pass. |
| [#209](https://github.com/TaoSama/vibe-screen/pull/209) | Open | iOS AVAudioEngine/PCM verifier work. It is adjacent only and cannot support Android P0110 USB/LAN playback. |

## Current-base P0110 readiness

Latest evidence directory:
[`evidence/2026-08-28-p0110-audio-current-base-blocked`](evidence/2026-08-28-p0110-audio-current-base-blocked/README.md).

The retained device identity is `nubia P0110 / pacific / Android 16 / SDK 36`;
public artifacts use `<ANDROID_SERIAL>` instead of the real device serial. The
local Android app was installed and foreground, `adb reverse tcp:54321
tcp:54321` was present, a Host listener was observed on loopback TCP `54321`,
and the read-only USB live smoke observed an active video stream. That is still
not an audio pass: the retained production session did not negotiate
`CAPABILITY_AUDIO`, the installed Host bundle lacks current-source provenance,
the installed Host `Info.plist` lacks `NSMicrophoneUsageDescription`, read-only
Host preflight/readiness could not prove stable signing or Microphone/TCC
readiness, and no Host microphone capture, channel `3` packet flow, Android
`AudioTrack` writes, audible output, or cleanup evidence was collected.
Trusted-LAN audio remains blocked separately because the device Wi-Fi path had
no usable association, `wlan0` IPv4 address, or route.

The machine-checkable summary is
[`android-audio-playback-summary.json`](evidence/2026-08-28-p0110-audio-current-base-blocked/android-audio-playback-summary.json):
`verdict=blocked` and `can_close_android_audio_playback_gate=false`.

## Automated checks

| Check | Result | Evidence |
| --- | --- | --- |
| `PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial <ANDROID_SERIAL> --package dev.telemachus.display --output evidence/2026-08-28-p0110-audio-current-base-blocked/device-info.json` | PASS | Wrote sanitized `device-info.json` with nubia/P0110/pacific/Android 16/SDK 36 identity and installed APK metadata. |
| `PYTHONPATH=tools python3 -m vibescreen_evidence.usb_live_smoke --allow-existing-device-lock --serial <ANDROID_SERIAL> --package dev.telemachus.display --port 54321 --output evidence/2026-08-28-p0110-audio-current-base-blocked/usb-live-smoke.json` | PASS | Observed current USB video stream, foreground app, ADB reverse, and decoder counters; this does not prove audio playback. |
| `python3 scripts/macos_dev_host.py preflight --source-root . --report evidence/2026-08-28-p0110-audio-current-base-blocked/macos-dev-host-preflight-current-base.txt` | BLOCKED | Failed closed before Host/device audio acceptance because the configured stable local signing identity is unavailable. |
| `python3 scripts/macos_dev_host.py readiness --source-root . --report evidence/2026-08-28-p0110-audio-current-base-blocked/macos-dev-host-readiness-current-base.txt --json-output evidence/2026-08-28-p0110-audio-current-base-blocked/host-readiness.json --port 54321` | BLOCKED | Read-only readiness recorded Host listener presence but could not prove stable signing, current-source Host provenance, or Microphone/TCC readiness. No login-item diagnostic opt-in was used. |
| `make android-audio-playback-owner-record EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-28-p0110-audio-current-base-blocked` | PASS | Wrote `android-audio-playback-summary.json` while preserving the expected fail-closed `blocked` result for a current-base owner record. |
| `make android-audio-playback-gate EVIDENCE_DIR=docs/changes/2026-08-24-p0110-audio-current-base/evidence/2026-08-28-p0110-audio-current-base-blocked` | NON-PASS | Re-ran the formal closing gate; expected fail-closed `blocked` result because Host stable signing/TCC readiness and Protocol v1 audio playback evidence are missing. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools/tests/test_android_audio_playback.py -v` | PASS | Evidence gate unit tests passed, including fail-closed blocked/insufficient behavior. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests "*ProtocolPcmAudioPlaybackTest" --tests "*StreamClientProtocolV1IntegrationTest"` | PASS | Focused Android JVM tests for PCM playback and Protocol v1 audio integration passed. |

## Open gates

- Real USB Protocol v1 audio playback on the named P0110 device.
- Real trusted-LAN Protocol v1 audio playback with AES-256-GCM secure records and no plaintext fallback.
- Mac system-output capture, if required as a product behavior beyond the current microphone PCM source.
