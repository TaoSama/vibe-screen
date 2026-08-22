# iOS device acceptance

No iOS device acceptance run is recorded yet. The current Phase 5 evidence is
limited to macOS-buildable core tests, the baseline MacHost two-process
loopback, the iPhone Simulator smoke gate, and an unsigned iPhoneOS archive. Do
not treat Android, Nubia P0110/pacific, or Xiaomi 13/fuxi records as iOS
signing, install, decode, UI, input, audio, reconnect, or device evidence.

Use this runbook only when an iPhone or iPad acceptance pass is explicitly
scheduled. It is a checklist and evidence schema; it does not ask for a long
soak by default, and it must not reset macOS or Android permissions or clear
Android application data. The machine gate validates retained summaries after a
run; it does not start Xcode, the Host, LAN traffic, ADB, or device automation.

The current-base aggregate owner is #182 (`current-base-ios-acceptance`). Before
reporting readiness or a blocked run, produce the aggregate summary from the
current base:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

The expected no-device result is fail-closed `blocked`. A nonzero exit from this
command is correct when signing identities, full Xcode, iPhone/iPad hardware, or
retained gate evidence are missing. Do not convert that readiness output into a
device pass.

## Open gates

These README Phase 5 device-acceptance gates remain open until the evidence
below passes on real iPhone and iPad hardware:

| Gate | Minimum pass evidence | Fail-closed rule |
| --- | --- | --- |
| Signing | E1 | F1 |
| Device install | E2 | F2 |
| Protocol session | E3 | F3 |
| VideoToolbox decode | E4 | F4 |
| Input | E5 | F5 |
| Reconnect | E6 | F6 |
| Audio | E7 | F7 |

Evidence requirements:

- E1: Xcode version, selected developer directory, development team, unique
  bundle ID, signing certificate identity, provisioning profile UUID, signed app
  or archive SHA-256.
- E2: iPhone and iPad-class hardware model, OS build, app revision, host
  revision, install log, first launch, and Local Network permission result.
- E3: Pairing link source, `SSWA`/`SSWR`, `0D`/`0D01`, Hello, negotiated
  capabilities, display list/start, video config ACK, ping/pong, and disconnect
  notice.
- E4: H.264 and HEVC runs with codec choice, SPS/PPS or VPS/SPS/PPS evidence,
  stream/config epoch telemetry, dropped frames, decoder error logs, thermal
  state, and power state.
- E5: Touch, drag, hardware keyboard modifiers, and hover or pointer accessory
  behavior with host acknowledgements and selected display/stream IDs.
- E6: Transient network interruption and heartbeat timeout cases with reconnect
  attempt timestamps, final state, no stale-epoch render, and measured reconnect
  duration.
- E7: PCM S16LE negotiation, AVAudioEngine start, audible playback
  confirmation, queue depth, underrun/error logs, and audio policy state.

Fail-closed rules:

- F1: Unsigned archive, Simulator build, missing signing identity, or reused
  bundle ID is not device evidence.
- F2: One device family alone leaves the other open; Simulator does not count.
- F3: The macOS loopback gate cannot satisfy app/device session evidence.
- F4: Android MediaCodec, synthetic media, or a decoded still image is not
  hardware VideoToolbox evidence.
- F5: Offline input encoding tests or Android CGEvent evidence do not close iOS
  input behavior.
- F6: Manual relaunch, auth/protocol validation failure, or missing epoch
  telemetry leaves reconnect open.
- F7: Core PCM parser tests or host-side audio capture plans do not prove iOS
  playback.

README Phase 5 also keeps HDR output, host-side advanced adapters, audio/bulk
product flows over Internet DataChannels, and advanced real-device behavior
open; those broader gates remain tracked in the Phase 5 verification record
rather than closed by this device runbook.

## Checklist

1. Record the repository commit, branch, dirty-tree status, Xcode version,
   selected developer directory, iOS SDK version, Swift version, host revision,
   and app archive SHA-256.
2. Record the signing setup: Apple development team, bundle identifier, signing
   certificate common name, provisioning profile UUID, and whether the archive
   is Development, Ad Hoc, or TestFlight. Do not commit private keys, profile
   contents, pairing tokens, or Apple account identifiers.
3. Record both target devices before install: product name, hardware model,
   OS/iPadOS version, build number, battery state, low-power mode, thermal
   state, network SSID class, and available storage. Redact serial numbers and
   private network identifiers.
4. Install and launch the signed app on one iPhone and one iPad-class device.
   Capture install logs, launch logs, Local Network permission behavior, and
   foreground/background lifecycle transitions.
5. Connect to the baseline MacHost over trusted LAN using a fresh pairing link.
   Capture the admission, upgrade, Hello, capability, display, video-config,
   heartbeat, input, and disconnect envelopes.
6. Stream H.264 and HEVC separately. Record negotiated resolution/FPS/bitrate,
   codec parameter sets, config epochs, frame IDs, dropped frames, decoder
   errors, device thermal/power state, and whether playback stayed live after a
   keyframe.
7. Exercise touch, drag, hardware keyboard modifiers, and hover or pointer
   accessory input against the selected stream. Record host-side acknowledgements
   or logs that include display and stream targets.
8. Exercise reconnect by toggling the trusted LAN path and by allowing the
   heartbeat miss budget to expire. Record attempt count, backoff timestamps,
   final state, reconnect duration, and proof that stale epochs were rejected.
9. Exercise PCM S16LE playback. Record negotiated audio config, packet epochs,
   queue depth, AVAudioEngine state, audible output confirmation, and any
   underrun or format rejection.
10. If the acceptance owner requests a bounded stability sample, record a
    30-minute memory, latency, dropped-frame, thermal, and power series. Do not
    start a longer soak from this runbook without explicit owner approval.

## Evidence schema

Each run should include a sanitized `acceptance.json` next to the retained logs.
Missing required fields, any Android device substituted for an iPhone/iPad gate,
or any gate without evidence keeps the run open, failed, or blocked; it must not
be reported as passed. Validate the sanitized file before using it to close a
README gate:

```sh
make ios-device-acceptance-gate \
  IOS_ACCEPTANCE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-device/acceptance.json \
  IOS_ACCEPTANCE_GATE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-device/ios-device-acceptance-gate.json
```

The underlying Python gate exits `0` only for `pass`, `1` for incomplete
evidence (`insufficient`), and `2` for failed or invalid evidence; the Makefile
target reports any non-pass as a failed target. `open` or `blocked` readiness
summaries are useful for tracking prerequisites, but they are expected to return
`insufficient` and cannot close the iOS trusted-LAN or real-device acceptance
gate.

```json
{
  "schema_version": "vibescreen.evidence/v1",
  "kind": "ios_device_acceptance",
  "platform": "ios",
  "status": "open",
  "aggregate_owner": {
    "aggregate": "current-base-ios-acceptance",
    "aggregate_pr": "#182",
    "source_prs_or_tasks": ["#182", "#196", "#207", "#208", "#209", "#238", "#251", "#253", "#257"]
  },
  "readiness_status": "blocked",
  "blocked_reasons": [],
  "repository": {
    "commit": "",
    "branch": "",
    "dirty": false
  },
  "host": {
    "commit": "",
    "macos_version": "",
    "permissions_changed_by_run": false
  },
  "xcode": {
    "version": "",
    "selected_developer_dir": "",
    "ios_sdk": ""
  },
  "trusted_lan": {
    "mode": "explicit_plaintext_legacy_fallback",
    "encrypted_lan_claimed": false
  },
  "signing": {
    "status": "open",
    "bundle_id": "",
    "team_id_redacted": true,
    "certificate_common_name_redacted": true,
    "provisioning_profile_uuid_redacted": true,
    "archive_sha256": ""
  },
  "devices": [
    {
      "role": "iphone",
      "product_name": "",
      "hardware_model": "",
      "os_version": "",
      "build_number": "",
      "install_status": "open"
    },
    {
      "role": "ipad",
      "product_name": "",
      "hardware_model": "",
      "os_version": "",
      "build_number": "",
      "install_status": "open"
    }
  ],
  "gates": {
    "signing": { "status": "open", "evidence": [] },
    "device_install": { "status": "open", "evidence": [] },
    "protocol_session": { "status": "open", "evidence": [] },
    "videotoolbox_h264": { "status": "open", "evidence": [] },
    "videotoolbox_hevc": { "status": "open", "evidence": [] },
    "input": { "status": "open", "evidence": [] },
    "reconnect": { "status": "open", "evidence": [] },
    "audio_playback": { "status": "open", "evidence": [] }
  },
  "broader_gates": {
    "hdr_output": { "status": "open", "evidence": [] },
    "advanced_adapters": { "status": "open", "evidence": [] },
    "trusted_lan_secure_records": { "status": "open", "evidence": [] }
  },
  "android_evidence_used_for_ios_gates": false,
  "notes": []
}
```

To turn this runbook record into current-base aggregate evidence, copy sanitized
field values into `ios-current-base-manifest.json` or generate a fresh default
manifest with `make ios-current-base-manifest`, then run
`python3 -m vibescreen_evidence.ios_current_base_gate`. The aggregate gate is
stricter than this runbook: it keeps the current-base aggregate open until the
E1-E7 device gates and the broader HDR, advanced-adapter, and trusted-LAN
secure-record gates all carry retained evidence.

Store raw logs under the active Phase 5 evidence directory or an external
release bundle, depending on privacy review. Commit only sanitized summaries,
hash manifests, and privacy scans.
