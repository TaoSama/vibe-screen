# Audio USB/LAN real-device evidence blocked - 2026-08-23

Status: blocked before real-device audio acceptance
Source branch: `codex/audio-usb-lan-e2e-gate`
Base commit: `781992d7dc6e99d62ddd5326853f689c30c53d67` (`origin/main` at
rebase)

## Goal

Run a current-source Protocol v1 USB and trusted-LAN audio smoke using the
macOS Host microphone PCM source and Android `AudioTrack` playback path. A valid
pass would need the real device identity, negotiated `CAPABILITY_AUDIO`,
`AudioConfigResult.accepted=true`, channel `3` audio packets, Android write
evidence, Host cleanup on disconnect, and audible or instrumentation-backed
playback confirmation.

## Blocker

This environment cannot complete evidence-grade device acceptance for the audio
path. The macOS Host audio source requires Microphone permission through TCC,
and current-source device evidence also requires the stable signed Host bundle
used by the project runbooks. Those signing/TCC prerequisites were not available
in this worktree session. Trusted-LAN audio additionally requires a reachable
Android Wi-Fi route and secure-record admission evidence; the most recent LAN
records for the Nubia P0110 remained blocked before LAN stream setup.

The target Android device for the next run must be recorded as `nubia P0110 /
pacific / Android 16 / SDK 36` with serial `EP0110PZ0B9110300B`; Android
commands must use `adb -s EP0110PZ0B9110300B ...`. This record does not relabel
that device as Xiaomi 13/fuxi evidence.

No real USB audio playback, trusted-LAN audio playback, audible output, or
Android device `AudioTrack` runtime write evidence was collected. This blocked
record does not close any real-device USB/LAN audio gate.

## Offline evidence collected instead

- Protocol contract gate: `make protocol` passed.
- Mac source and self-test gates passed: `cd baseline/MacHost && swift build`
  plus `.build/debug/"Vibe Screen" --transport-self-test` and
  `.build/debug/"Vibe Screen" --audio-capture-self-test`. Swift XCTest
  execution is blocked locally by missing `XCTest` in the selected Command Line
  Tools environment.
- Android focused gate passed for Protocol v1 session/framing, PCM playback unit
  behavior, StreamClient loopback audio, and secure-record channel declaration.

The command-level automated verification summary is recorded in
[`../../TEST.md`](../../TEST.md). None of those offline checks is treated as
real-device USB or trusted-LAN audio playback evidence.

## Required next run

1. Install a current-source stable-signed Host bundle and grant Screen
   Recording, Accessibility, and Microphone permissions as required.
2. Record exact Android device identity and APK/Host build identity.
3. For USB, start Host, configure `adb reverse tcp:54321 tcp:54321`, connect
   Android Protocol v1, and retain logs proving audio negotiation, config
   acceptance, packet flow, Android playback writes, and disconnect cleanup.
4. For LAN, first prove Wi-Fi route and encrypted secure-record negotiation;
   then repeat the audio checks with no plaintext fallback.
5. Keep this evidence labeled by the actual device, transport, source commit,
   and permission/signing setup.
