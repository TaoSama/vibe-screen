# Phase 5: native iOS client and advanced capability boundary

Status: 5A–5D client implementation complete; baseline MacHost loopback and Simulator gates pass, device verification pending
Owner: iOS and advanced capabilities  
Current-base aggregate owner: #290 (`current-base-ios-acceptance`)
Started: 2026-08-04

## Goal

Deliver the smallest native iPhone/iPad client that exercises the final module
boundaries and Protocol v1, while defining advanced capabilities additively so
older Phase 0 clients remain valid.

## Delivered slice (5A)

- one SwiftUI application target for iPhone and iPad, minimum iOS 17;
- generated Protocol v1 SwiftProtobuf bindings from the repository schemas;
- capability/codec Hello, display list/start, H.264/HEVC media, current-epoch
  filtering, and native normalized touch events;
- authenticated trusted-LAN admission and legacy-to-v1 upgrade into the
  baseline MacHost main session through the secure-record loopback harness,
  which asks the Host to bind port `0` and passes the selected localhost port
  to the iOS client,
  loopback path by default, with explicit plaintext legacy fallback
  regression-tested separately;
- replaceable TCP transport framing with independent control, video, audio,
  and bulk logical channels;
- VideoToolbox decode with native CoreVideo output;
- deterministic macOS-buildable tests for protobuf bytes, split/coalesced TCP
  reads, capability intersection, session epochs, backoff, and Annex-B;
- build, install, upgrade, permissions, troubleshooting, provenance, and known
  limitations documentation.

## Phased boundary

| Slice | Scope | Protocol rule | Status |
| --- | --- | --- | --- |
| 5A | single iOS client, existing display, one video stream, touch | existing Protocol v1 only | code complete; baseline MacHost two-process loopback, iPhone Simulator UI smoke, and unsigned archive pass; device run pending |
| 5B | multiple clients, multiple virtual displays/streams | additive resource limits, stream/display targets, explicit negotiated capability result | client routing/limits/UI implemented and CLI tested; host allocation pending |
| 5C | audio, bidirectional clipboard, file transfer | capability-gated messages and separate audio/bulk channels | client core and iOS adapters implemented; Internet product-flow wiring and platform/host E2E pending |
| 5D | HDR/color, custom gestures, wake, managed devices | color-description fields; host actions; local gesture/MDM policy | negotiation/fallback and controls implemented; authenticated WOL sender baseline merged; HDR static metadata, HDR output, and real WakeHost hardware gates pending |

## Acceptance criteria

5A is complete only when all of the following are recorded:

1. `swift build` and the self-test pass from a clean package resolution.
2. Full Xcode builds the universal iPhone/iPad target for an iOS simulator.
3. An iPhone and iPad class device install, negotiate Protocol v1, render H.264
   and HEVC, send touch, reject an old epoch, and recover from a disconnect.
4. The baseline MacHost accepts authenticated trusted-LAN admission, establishes
   secure records for the default loopback path, upgrades from its legacy entry
   boundary inside that record stream, and uses Protocol v1 for the main session,
   display list/start, video configuration/media, heartbeat, targeted touch,
   errors, and disconnect. Explicit plaintext legacy fallback remains a separate
   regression path and is not encrypted evidence.
5. A cross-client fixture proves Swift and Android encode/decode the same
   Protocol v1 Hello and input messages.
6. License acknowledgements are present in any distributed app artifact.

Criteria 1 and 2 are proved. Criterion 4 is proved by the release-build,
two-process loopback for both normal lifecycle and invalid-target error paths;
this is core wire transport/session evidence, not `StreamViewModel`, decoder,
UI, iOS app, or device evidence. The shared Android/iOS model contract in
`contracts/shared-models/v1/manifest.json` now fail-closes field-number,
capability, envelope payload, fixture, generated-binding, and
production-advertisement drift while Android and iOS remain native Kotlin/Swift
implementations. The Swift/HarmonyOS shared ClientHello fixture adds an
independent Protocol v1 compatibility case.
Criterion 5 still requires the Android application golden-byte fixture named by
the acceptance criterion. Android ADB evidence can prove cross-client contract
behavior but cannot satisfy criterion 3.

The current-base aggregate owner is #290. The merged #182 gate remains the
historical sanitized device-acceptance baseline, while #290 owns the
machine-readable aggregate entry point for the current base. This is not a
device-pass claim. The aggregate must continue to include the narrower readiness
owners for signing, VideoToolbox hardware decode, host advanced adapters,
AVAudioEngine/PCM, HDR, native input, reconnect, and trusted-LAN secure records.
Without real signed iPhone and iPad evidence, the aggregate remains fail-closed
readiness only.
After rebasing onto the #225 baseline, #199 is the WakeHost current-base
evidence owner. It tracks the authenticated magic-packet path against current
mainline and keeps the sleeping-Mac/router/NIC WOL gate blocked until retained
hardware evidence satisfies the dedicated gate.
The current-base manifest records the narrower owner per gate so aggregate
tracking cannot hide missing evidence: hardware H.264/HEVC VideoToolbox decode
is owned by #251, and Host advanced adapters are owned by #253 with this gate
ownership layer tracked by #282. Both remain open until their retained evidence
passes through the machine gate; neither #182 nor #290 closes either gate by
aggregation alone.
