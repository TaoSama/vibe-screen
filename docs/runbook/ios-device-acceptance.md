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

The current-base aggregate owner is #290 (`current-base-ios-acceptance`). Merged
PR `#182` is the historical sanitized device-acceptance baseline; do not use it
as the current aggregate owner. Before reporting readiness or a blocked run,
produce the aggregate summary from the current base:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

The expected no-device result is fail-closed `blocked`. A nonzero exit from this
command is correct when signing identities, full Xcode, iPhone/iPad hardware, or
retained gate evidence are missing. Do not convert that readiness output into a
device pass.
The aggregate report also records per-gate owners. PR #290 owns the aggregate
and sanitized iOS device-acceptance validator only; hardware VideoToolbox
readiness remains owned by #251, and Host-side advanced-adapter readiness
remains owned by #253. Do not mark those gates complete from aggregate status,
Simulator output, unsigned archives, MacHost loopback, or Android evidence.

Before starting any install or device session, record and check the local iOS
toolchain prerequisites. If any of these fail, stop at blocked readiness and do
not begin the device run:

```bash
set -euo pipefail
xcodebuild -version
xcodebuild -showsdks | grep -qi 'iphoneos'
identity_output="$(security find-identity -p codesigning -v)"
printf '%s\n' "$identity_output" | grep -Eq '^[[:space:]]*[1-9][0-9]* valid identities found[[:space:]]*$'
```

Then validate the sanitized app-signing readiness summary. This is a dedicated
fail-closed owner for the signing prerequisite only; it does not install the app
or close any iOS device behavior gate:

```bash
make ios-app-signing-readiness-gate \
  IOS_APP_SIGNING_READINESS_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness.json
```

The input must retain or summarize Team ID, provisioning profile UUID, unique
bundle ID, codesign identity, registered physical-device UDID hashes, signed-app
entitlements, signed artifact SHA-256, a clean current-base commit, and local
artifacts for the archive command, codesign entitlements, and provisioning
profile output. Keep the public JSON sanitized: record booleans, hashes, and
explicit redaction flags instead of raw Team IDs, profile UUIDs, certificate
hashes, identity names, device UDIDs, or local filesystem paths. Missing any one
of those values returns `blocked`; Simulator,
unsigned, ad-hoc, or Android-derived material returns `fail`. Pass the produced
`ios-app-signing-readiness-gate.json` into the current-base manifest before
reporting aggregate readiness:

```bash
make ios-current-base-gate \
  EVIDENCE_DIR=.build/evidence/ios-current-base \
  IOS_APP_SIGNING_READINESS_GATE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness-gate.json
```

The current-base aggregate accepts this signing row only when the embedded gate
declares `owner.role=ios_app_signing_readiness_current_base_owner`,
`owner.head_ref=codex/ios-app-signing-readiness-current-base-20260829`, and
`owner.repository=TaoSama/vibe-screen`. Its `signing_summary` is the source for
the aggregate `signing` fields, including UDID-hash and entitlements coverage;
hand-written manifest fields without that dedicated owner stay blocked.
Embed the same passing `ios-app-signing-readiness-gate.json` as
`signing_readiness_gate` in any later `acceptance.json`. The device acceptance
gate binds the simplified signing row back to that owner output, so an ad-hoc
signature, missing physical-device UDID hashes, missing entitlements, or a
mismatched signed artifact digest cannot close the device gate.

## Open gates

These README Phase 5 device-acceptance gates remain open until the evidence
below passes on real iPhone and iPad hardware:

| Gate | Minimum pass evidence | Fail-closed rule |
| --- | --- | --- |
| Signing | E1 | F1 |
| Device install | E2 | F2 |
| Protocol session | E3 | F3 |
| VideoToolbox decode | E4 | F4 |
| Native input | E5 | F5 |
| Reconnect | E6 | F6 |
| Audio | E7 | F7 |

Evidence requirements:

- E1: Xcode version, selected developer directory, development team, unique
  bundle ID, signing certificate identity, provisioning profile UUID, physical
  device UDID coverage in the provisioning profile, signed-app entitlements, and
  signed app or archive SHA-256.
- E2: iPhone and iPad-class hardware model, OS build, app revision, host
  revision, install log, first launch, and Local Network permission result.
- E3: Pairing link source, `SSWA`/`SSWR`, `0D`/`0D01`, Hello, negotiated
  capabilities, display list/start, video config ACK, ping/pong, and disconnect
  notice.
- E4: H.264 and HEVC runs with codec choice, SPS/PPS or VPS/SPS/PPS evidence,
  stream/config epoch telemetry, dropped frames, decoder error logs, thermal
  state, and power state.
- E5: Native-input behavior is owned by
  `phase5-ios-native-input-behavior`. The run must record touch tap, touch
  drag, hardware keyboard press/release, hardware keyboard modifier cleanup,
  hover or pointer accessory movement, Host acknowledgements, and selected
  display/stream IDs from signed iPhone and iPad apps.
- E6: Transient network interruption and heartbeat timeout cases with reconnect
  attempt timestamps, final state, no stale-epoch render, and measured reconnect
  duration.
- E7: PCM S16LE negotiation, `--audio-playback-self-test` PASS on the signed
  app build, AVAudioEngine start, audible playback confirmation, queue depth,
  underrun/overrun/error logs, audio route, and audio policy state.

Fail-closed rules:

- F1: Unsigned archive, Simulator build, missing signing identity, or reused
  bundle ID is not device evidence.
- F2: One device family alone leaves the other open; Simulator does not count.
- F3: The macOS loopback gate cannot satisfy app/device session evidence.
- F4: Android MediaCodec, synthetic media, or a decoded still image is not
  hardware VideoToolbox evidence. Simulator and unsigned archive summaries from
  the readiness helper are also blocked by construction.
- F5: Offline input encoding tests, iPhone Simulator UI tests, Android CGEvent
  evidence, or ADB/HID evidence from another platform do not close iOS native
  input behavior.
- F6: Manual relaunch, auth/protocol validation failure, or missing epoch
  telemetry leaves reconnect open.
- F7: Core PCM parser tests, playback-queue self-tests, Simulator-only
  AVAudioEngine checks, or host-side audio capture plans do not prove audible
  iOS playback.

README Phase 5 also keeps HDR output, iOS advanced adapters, host-side advanced
adapters, audio/bulk product flows over Internet DataChannels, and advanced
real-device behavior open; those broader gates remain tracked in the Phase 5
verification record rather than closed by this device runbook. The host-side
advanced-adapter owner is #253 and requires reviewed MacHost/product evidence
for multi-client/display streams, audio capture, clipboard/file handlers,
HDR/color retry, host actions, wake helper, and managed policy. HDR output
specifically requires the dedicated `ios-hdr-edr-gate` in the
[HDR/color acceptance runbook](hdr-color-acceptance.md): SDR fallback,
Simulator output, unsigned archives, Android evidence, Protocol field presence,
ordinary VideoToolbox decode readiness, and offline self-tests do not close it.

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
9. Exercise PCM S16LE playback. First launch the same signed build with
   `--audio-playback-self-test` and record the PASS/FAIL line plus scheduled,
   played, queued, queue-empty, late-completion, overrun, and stop counters.
   Then connect to an audio-capable host path and record negotiated audio
   config, packet epochs, queue depth, AVAudioEngine state, output route,
   audible output confirmation from a listener or external recorder, and any
   underrun, overrun, or format rejection. If no audio-capable host path or
   audible capture environment is present, mark E7 blocked rather than passed.
10. If the acceptance owner requests a bounded stability sample, record a
    30-minute memory, latency, dropped-frame, thermal, and power series. Do not
    start a longer soak from this runbook without explicit owner approval.

## VideoToolbox readiness owner

Record the Phase 5 hardware VideoToolbox behavior gate separately from the wider
acceptance checklist. The owner is
`tools/vibescreen_evidence/ios_videotoolbox_readiness.py`, with schema
`tools/schemas/ios-videotoolbox-readiness.schema.json` and Makefile wrapper:

```bash
make ios-videotoolbox-readiness EVIDENCE_DIR="$EVIDENCE_DIR"
```

The wrapper expects `$EVIDENCE_DIR/ios-videotoolbox-observations.json`. Set
`runtime_class` to `simulator`, `unsigned_archive`, `physical_iphone`, or
`physical_ipad`. The helper may be run offline or in CI with Simulator/archive
inputs, but those runtime classes must produce `verdict=blocked` and make the
Makefile gate exit nonzero. A physical device family can pass only when the
observation record proves signed installation, real iPhone/iPad identity, H.264
and HEVC parameter sets, VideoToolbox sessions and output frames for both
codecs, hardware-path evidence, stream/config epoch telemetry, thermal/power
state, and existing non-empty retained iOS VideoToolbox artifacts under the
evidence directory. To write a blocked or insufficient summary for triage
without failing the shell command, call the Python helper directly and omit
`--require-pass`.

The summary intentionally keeps `can_close_phase5_hardware_videotoolbox_gate`
false. Close the README Phase 5 gate only after both `physical_iphone` and
`physical_ipad` summaries pass and are reviewed with the signed installation,
protocol session, input, reconnect, and audio evidence from this runbook.

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
    "aggregate_pr": "#290",
    "source_prs_or_tasks": ["#182", "#196", "#207", "#208", "#209", "#238", "#251", "#253", "#257", "#279", "#282"]
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
    "mode": "secure_records",
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
  "signing_readiness_gate": {
    "schema_version": "vibescreen.evidence/v1",
    "kind": "ios_app_signing_readiness_gate",
    "owner": {
      "role": "ios_app_signing_readiness_current_base_owner",
      "head_ref": "codex/ios-app-signing-readiness-current-base-20260829",
      "repository": "TaoSama/vibe-screen",
      "scope": "Phase 5 iOS app-signing readiness prerequisite only"
    },
    "source": {
      "readiness": "ios-app-signing-readiness.json",
      "evidence_root": "."
    },
    "current_base": {
      "commit": null,
      "branch": "codex/ios-app-signing-readiness-current-base-20260829",
      "dirty": false
    },
    "verdict": "blocked",
    "signing_status": "blocked",
    "signing_summary": {
      "status": "blocked",
      "bundle_id": null,
      "unique_bundle_id": false,
      "team_id_recorded": false,
      "codesign_identity_recorded": false,
      "provisioning_profile_recorded": false,
      "device_udid_hashes_recorded": false,
      "entitlements_recorded": false,
      "signed_artifact_sha256": null
    },
    "can_close_ios_app_signing_readiness": false,
    "can_close_ios_device_acceptance": false,
    "recorded_fields": {
      "team_id": false,
      "provisioning_profile": false,
      "bundle_id": false,
      "codesign_identity": false,
      "device_udid": false,
      "entitlements": false,
      "signed_artifact": false,
      "artifacts": false
    },
    "missing": ["replace this object with the passing gate output before device acceptance"],
    "failures": [],
    "evidence": [],
    "interpretation": "Blocked signing readiness cannot close device acceptance."
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
    "audio_playback": {
      "status": "open",
      "playback_self_test": {
        "status": "open",
        "result_line": "",
        "scheduled_buffers": 0,
        "played_buffers": 0,
        "queued_buffers": 0,
        "queue_empty": 0,
        "late_completions": 0,
        "overruns": 0,
        "stops": 0
      },
      "audible_confirmation": {
        "status": "open",
        "method": "",
        "audio_route": "",
        "capture_artifacts": []
      },
      "evidence": []
    }
  },
  "broader_gates": {
    "hdr_output": { "status": "open", "evidence": [], "runbook": "docs/runbook/hdr-color-acceptance.md" },
    "advanced_adapters": { "status": "open", "evidence": [] },
    "host_advanced_adapters": { "status": "open", "evidence": [] },
    "trusted_lan_secure_records": { "status": "open", "evidence": [] }
  },
  "android_evidence_used_for_ios_gates": false,
  "notes": []
}
```

Use `trusted_lan.mode=secure_records` only when retained evidence shows
`SSWA`/`SSWR`, `VSLS`/`VSLR`, AES-256-GCM record traffic, and the `0D`/`0D01`
Protocol v1 upgrade inside that record stream. Use
`explicit_plaintext_legacy_fallback` only for the separate fallback regression
path, and keep `encrypted_lan_claimed=false` unless a signed iPhone/iPad run on a
real network has retained packet/session evidence.

To turn this runbook record into current-base aggregate evidence, copy sanitized
field values into `ios-current-base-manifest.json` or generate a fresh default
manifest with `make ios-current-base-manifest`, then run
`PYTHONPATH=tools python3 -m vibescreen_evidence.ios_current_base_gate`. The aggregate gate is
stricter than this runbook: it keeps the current-base aggregate open until the
E1-E7 device gates and the broader HDR, advanced-adapter, and trusted-LAN
secure-record gates all carry retained evidence.

Store raw logs under the active Phase 5 evidence directory or an external
release bundle, depending on privacy review. Commit only sanitized summaries,
hash manifests, and privacy scans.

## Native input gate

For the E5 native-input slice, write a sanitized
`ios-native-input-observations.json` next to the retained logs, then derive the
fail-closed summary:

```bash
make ios-native-input-gate EVIDENCE_DIR=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>
```

The command writes `ios-native-input-gate.json`. It is a readiness/evidence
owner for the iOS native-input behavior gate, not a collector. A `pass` closes
only the native-input behavior gate when the same bundle contains signed iPhone
and iPad runs, Host build identity, input accessories, and retained logs.
`blocked`, `insufficient`, or `fail` keeps the gate open. The gate fails if the
observations try to use Android evidence, Simulator evidence, or offline tests
as real iOS input behavior.

Minimal observation template:

```json
{
  "run_id": "",
  "ios_device_lock_acquired": false,
  "device_identity_recorded": false,
  "device_is_iphone_or_ipad": false,
  "iphone_native_input_observed": false,
  "ipad_native_input_observed": false,
  "app_revision_recorded": false,
  "signed_app_installed": false,
  "local_network_permission_recorded": false,
  "baseline_machost_listener_observed": false,
  "protocol_session_negotiated": false,
  "input_capabilities_negotiated": false,
  "display_stream_binding_recorded": false,
  "touch_tap_observed": false,
  "touch_drag_observed": false,
  "hardware_keyboard_attached": false,
  "keyboard_press_release_observed": false,
  "keyboard_modifier_observed": false,
  "keyboard_modifier_release_no_leak_observed": false,
  "hover_pointer_accessory_attached": false,
  "hover_pointer_move_observed": false,
  "host_input_acknowledgements_retained": false,
  "ios_logs_retained": false,
  "host_logs_retained": false,
  "android_evidence_used_for_ios_input": false,
  "simulator_evidence_used_for_ios_input": false,
  "offline_tests_used_as_device_evidence": false,
  "artifact_paths": [],
  "blocking_notes": [],
  "notes": ""
}
```
