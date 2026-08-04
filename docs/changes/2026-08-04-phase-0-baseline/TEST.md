# Phase 0 verification plan

## Reproducible local checks

```bash
make protocol
make baseline-macos-build
make baseline-macos-self-test
make baseline-macos-test
make baseline-macos-app
make baseline-android-test
make baseline-android-check
make baseline-android-apk
make evidence-tools-test
make evidence-device-info
```

Record `sw_vers`, `xcodebuild -version`, `swift --version`, `java -version`,
Android SDK versions, `adb devices -l`, and the repository commit with every
result.

## Test matrix

| Layer | Required evidence |
| --- | --- |
| Static | Buf format/lint/build; breaking check against v1 fixture; license/notice audit |
| Contract | Swift/Kotlin golden bytes; required capability; Buf unknown-field binary acceptance and lossy JSON projection; incompatible version; capability rejection |
| Unit | session state machine; epoch filter; backoff; coordinate mapping; latest-frame queue |
| Transport | split/coalesced reads; disconnect; slow consumer; bounded backlog |
| Host integration | fake capture through encoder and loopback transport |
| Android integration | framing, session, and decoder lifecycle on emulator |
| Device E2E | Xiaomi 12 video, touch, keyboard, reconnect, codec fallback |
| Soak | 1080p30 USB for 30 minutes with queue/RSS/latency series |
| Latency | external-camera raw samples and measurement notes |

## Current evidence (2026-08-04)

- Upstream SideScreen HEAD resolves to
  `a651a81b7d6468c7a564c038551872d3346a2d55`.
- Upstream Telemachus HEAD resolves to
  `a5dd1298870846d749175812f936ceebfd8b6b69`.
- Protocol v1 format, lint, build, and breaking checks pass with Buf v1.72.0.
- The final Android clean gate passes 68 tests with zero
  failures/errors/skips. `clean`, `testDebugUnitTest`, `lintDebug`,
  `assembleDebug`, and `auditReleaseDependencies` pass together
  (`BUILD SUCCESSFUL in 35s`, 60 tasks). The installed debug APK has
  SHA-256
  `573a00cfca1ab5d39e5d2991ab5f6d19aa920271980b75b62ff64a5490922c68`.
- Android reliability tests cover capacity-bounded latest-frame eviction,
  stale session epochs, heartbeat expiry, capped reconnect backoff, explicit
  HEVC-to-H.264 fallback, and single-line JSON telemetry. The JSONL gate was
  also run alone and passed.
- The dependency-free evidence tool suite passes 32 tests. Its versioned
  `vibescreen.evidence/v1` schemas cover device identity, run manifests, raw
  soak samples, and summaries; Makefile targets expose 30-minute, two-hour,
  and eight-hour presets. Formal soak presets require the Android process to
  remain alive and require host `stream_stats` JSONL, so idle collection cannot
  be reported as a stable stream.
- The generated Android notices match the pinned MIT license, notice, and
  Apache 2.0 text byte-for-byte by SHA-256.
- Imported host transport self-test passes configuration, keyframe, pong,
  touch parsing, and port-conflict checks.
- The host reliability core and `StreamingServer` now enforce an effective
  two-frame maximum (one Network.framework send plus one pending frame), reject
  frames from an older session epoch, monitor heartbeats with bounded reconnect
  advice, select codec fallback explicitly, and write versioned JSONL telemetry.
  The reliability/streaming sources pass an isolated Swift typecheck, the full
  release host build passes, and `make baseline-macos-self-test` passes host,
  transport, and reliability self-tests.
- Host self-test passes online-display catalog/fallback, window placement
  bounds, and the bounded unattended recovery schedule. The release host
  rebuilds successfully after the concurrent session/queue/telemetry
  integration.
- `make baseline-macos-app` produces an ad-hoc signed
  `Telemachus-macos-0.12.0-arm64.zip` plus SHA-256 file; `codesign --verify
  --deep --strict` passes. Developer ID signing and notarization are not
  claimed.
- Both upstream macOS executables compile and link under Swift 6.3.1.
- Both macOS test suites fail before test execution with
  `error: no such module 'XCTest'` because full Xcode is not selected.

## Protocol v1 main-session offline verification (2026-08-05)

The macOS host and Android client now share the checked Protocol v1 schemas in
their runnable baseline session. This evidence proves generated-wire
compatibility, session behavior, builds, and the non-listening host integration
self-test. It does not replace device interoperability evidence.

- `make protocol` passes Buf format, lint, build, and breaking checks plus 12
  fixture/security tests. Fixed fixtures cover 13 control envelopes, media
  header plus Annex-B payload, upgrade bytes, required capability field 9,
  split/coalesced logical-channel framing, and Buf decoding of an additive
  unknown binary field. The latter test deliberately projects through JSON,
  confirms that the unknown field is discarded, and does not prove Swift or
  Kotlin unknown-field preservation.
- `./gradlew testDebugUnitTest lintDebug assembleDebug
  auditReleaseDependencies` passes 112 Android unit tests and all 66 Gradle
  tasks. The generated Java-lite bindings contain 168 files. The resulting
  debug APK SHA-256 is
  `c7f3c16339bd1cc589d03268e1d0bbfbf87ad0857af92787061f6247a32d9cb1`.
- `swift build -c release --product Telemachus` passes. The release executable
  SHA-256 is
  `76202bd0deb8d8f9763490f25361dea9a894a5636a84d4e205fcfb2f1449ceb1`.
  `.build/release/Telemachus --protocol-v1-self-test` reports `PASS` for
  framing, all shared cross-platform golden fixtures, version/required
  capability negotiation, display/video acknowledgement gating, stale epochs,
  input including two-pointer aggregation, heartbeat, errors, and media.
- The additive schema was regenerated into both MacHost and iOS Swift bindings.
  `swift build --package-path apps/ios` and the iOS core self-test pass, proving
  the checked binding update did not regress that consumer.
- `swift test --filter ProtocolV1SessionTests` still fails before test execution
  with `no such module 'XCTest'`: this machine selects
  `/Library/Developer/CommandLineTools`, not full Xcode. The equivalent pure
  host self-test is evidence for this change, but it is not recorded as XCTest.

The available device lease was released after a screen-locked macOS host
reported zero ScreenCaptureKit displays; its attempted two-hour pre-warm never
started a valid clock and is not evidence. No Protocol v1 APK install, app
launch, media-port probe, or device stream was performed for this integration
record. A future device run must acquire a fresh exclusive lease and prove the
new wire mode from host/client logs before it can close the interoperability
gate.

## Final coordinated device acceptance (2026-08-04)

The final device run used ADB endpoint `100.72.246.116:5555`. The device
identified itself as Nubia P0110 (`pacific`), hardware serial `[redacted]`,
Android 16 / SDK 36, fingerprint
`nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys`.
It is not a Xiaomi 12, so this run proves interoperability on the recorded
Nubia device but does not close the Xiaomi-specific Phase 0 criterion.

- The final APK was installed exactly once with `adb install -r -t`; install
  returned `Success` and `lastUpdateTime=2026-08-04 22:49:59` local time.
- ADB reverse was rebuilt as `tcp:54321 -> tcp:54321`. The Host listened on
  `127.0.0.1:54321` and negotiated HEVC with the real
  `c2.qti.hevc.decoder` at `1512x982`. First output and continuing 60 FPS
  counters were observed; typical decoder latency was 5--7 ms.
- Android taps at two separated screen positions moved the Mac cursor from
  `(448.7,-557.1)` to `(0.0,271.9)` and then `(1279.1,505.7)`, while the Host
  PID and stream remained alive.
- Force-stopping and cold-starting the client preserved Host PID `70018`.
  Host telemetry recorded disconnect epoch 1, admission epoch 2, HEVC
  selection, a fresh keyframe, and first output. From explicit client start to
  admission was about one second.
- A Debug/JDWP fault injection set the process-local HEVC runtime-failure flag.
  The unchanged APK then sent the normal AVC-only offer; the Host explicitly
  selected H.264 and VideoToolbox reconfigured to H.264. The device used
  `c2.qti.avc.decoder` and produced output. On this device H.264 decoder
  latency was about 86--91 ms with frequent stale-output drops, so it is a
  functional fallback, not the preferred performance path.
- A separate Debug/JDWP fault injection advanced the active epoch gate to 999
  while frames still carried epoch 11. Android emitted machine-readable
  `frame_dropped` records with `reason=stale_session_epoch`,
  `frame_epoch=11`, and `current_epoch=999`. The injected process was then
  discarded before stability testing.

The accepted soak ran from `2026-08-04T15:54:38.394286Z` through
`2026-08-04T16:24:38.347614Z` with Host PID `95367` and Android PID `24997`.
The runner was invoked with `--host-pid`, making Host liveness a sampled gate
in addition to the Makefile target's Android-process and `stream_stats` gates.

- result: `complete`; 60/60 connected samples, 60/60 Android-process samples,
  60/60 Host RSS samples, zero sample errors, zero ADB reconnects;
- exact-window Host telemetry: 1,784 `stream_stats`, 1,797 accepted
  heartbeats, zero admission/disconnect events, zero queue drops, and zero
  reported dropped frames;
- FPS min/mean/max: `59.53 / 60.01 / 61.29`; average frame-age
  min/mean/max: `4.92 / 6.38 / 11.08 ms`; maximum stats gap: 2 seconds;
- Android PSS min/mean/max/final:
  `127805 / 129194 / 130681 / 130565 KiB`;
- Host RSS min/mean/max/final:
  `107568 / 113999 / 118208 / 118048 KiB`;
- battery sensors stayed within 36--38 C, USB-port temperature within
  37.98--38.65 C, CPU peak was 69.9 C and returned to 44.0 C, GPU peak was
  54.0 C and returned to 39.7 C; reported thermal status remained zero.

The Host RSS rose about 9 MiB from the first to last sample and its fitted
second-half slope remained approximately 208 KiB/min. The stream, queue,
latency, and process gates passed, but a 30-minute RSS series cannot rule out a
slow leak. The planned two-hour run remains required before claiming the
Phase 1 no-growth target.

Two earlier windows are explicitly invalid. The first was interrupted by a
concurrent APK install. A later 30-minute attempt was disturbed by a local
HTTP probe that sent `GET / HTTP/1.1` to the media port; the Host treated it as
a client and the Android stream recovered in about two seconds. That attempt
is retained under `.build/evidence/soak-30m-invalid-local-http-probe-*` and is
not used for the accepted result. The final Host was pre-warmed beyond the
one-time probe before starting the accepted clock.

Detailed commands, hashes, and artifact locations are recorded in
[`evidence/device-100.72.246.116-5555/FINAL_ACCEPTANCE.md`](evidence/device-100.72.246.116-5555/FINAL_ACCEPTANCE.md).

## Still unproved

- macOS XCTest results, Developer ID signing, and notarization;
- private virtual-display behavior on macOS 26.4.1;
- selected-display hot-plug behavior, true mirror mode, and real-window restore;
- Xiaomi 12 install, hardware decode, input, disconnect, and soak behavior;
- keyboard forwarding, Protocol v1 real-device application interoperability, a
  two-hour no-growth run, and external glass-to-glass/input latency.

These remain required work. They must not be converted into assumed passes.
