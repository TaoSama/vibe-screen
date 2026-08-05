# Phase 5: native iOS client and advanced capability boundary

Status: 5A–5D client implementation complete; baseline MacHost loopback and Simulator gates pass, device verification pending
Owner: iOS and advanced capabilities  
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
  baseline MacHost main session on TCP `54321`;
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
| 5C | audio, bidirectional clipboard, file transfer | capability-gated messages and separate audio/bulk channels | client core and iOS adapters implemented; platform/host E2E pending |
| 5D | HDR/color, custom gestures, wake, managed devices | structured color metadata; host actions; local gesture/MDM policy | negotiation/fallback and controls implemented; HDR output/host helper pending |

## Acceptance criteria

5A is complete only when all of the following are recorded:

1. `swift build` and the self-test pass from a clean package resolution.
2. Full Xcode builds the universal iPhone/iPad target for an iOS simulator.
3. An iPhone and iPad class device install, negotiate Protocol v1, render H.264
   and HEVC, send touch, reject an old epoch, and recover from a disconnect.
4. The baseline MacHost accepts authenticated trusted-LAN admission, upgrades
   from its legacy entry boundary, and uses Protocol v1 for the main session,
   display list/start, video configuration/media, heartbeat, targeted touch,
   errors, and disconnect.
5. A cross-client fixture proves Swift and Android encode/decode the same
   Protocol v1 Hello and input messages.
6. License acknowledgements are present in any distributed app artifact.

Criteria 1 and 2 are proved. Criterion 4 is proved by the release-build,
two-process loopback for both normal lifecycle and invalid-target error paths;
this is core wire transport/session evidence, not `StreamViewModel`, decoder,
UI, iOS app, or device evidence. The Swift/HarmonyOS shared ClientHello fixture
adds an independent Protocol v1 compatibility case. Criterion 5 still requires
the Android application fixture named by the acceptance criterion. Android ADB
evidence can prove cross-client contract behavior but cannot satisfy criterion
3.
