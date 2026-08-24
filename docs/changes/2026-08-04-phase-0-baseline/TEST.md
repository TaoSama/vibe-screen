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
| Device E2E | recorded Nubia P0110 evidence plus the Xiaomi 13 (fuxi) video, touch, keyboard, reconnect, and codec fallback gate; Xiaomi 13 streaming/input is now on device, host RSS no-growth soak still open |
| Soak | 1080p60 USB with queue/RSS/latency series; a two-hour Xiaomi 13 run completed with a stable stream but an open host RSS no-growth gate |
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
- In the original local environment, both macOS test suites failed before test
  execution with `error: no such module 'XCTest'` because full Xcode was not
  selected. For main commit `4c2e908fe31af4c187684991301e163371444eab`,
  this historical local limitation was closed by the 2026-08-06 CI result
  recorded below; it is not retroactively attributed to the original device
  artifact.

## Protocol v1 main-session offline verification (2026-08-05)

The macOS host and Android client now share the checked Protocol v1 schemas in
their runnable baseline session. This evidence proves generated-wire
compatibility, session behavior, builds, and the non-listening host integration
self-test. It does not replace device interoperability evidence.

- `make protocol` passes Buf format, lint, build, and breaking checks plus 13
  fixture/security tests. Fixed fixtures cover 14 control envelopes, including
  non-zero initial and runtime rotation, plus media
  header plus Annex-B payload, upgrade bytes, required capability field 9,
  split/coalesced logical-channel framing, and Buf decoding of an additive
  unknown binary field. The latter test deliberately projects through JSON,
  confirms that the unknown field is discarded, and does not prove Swift or
  Kotlin unknown-field preservation.
- `./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug
  auditReleaseDependencies` passes 176 Android unit tests with zero
  failures/errors/skips and all 67 Gradle tasks (`BUILD SUCCESSFUL in 37s`). The
  generated Java-lite bindings contain 168 files. The resulting
  debug APK SHA-256 is
  `1fdd44c2a7da8b5cb9a28dca7e8b883bafa303897aee957617804ec006be3c58`.
  The deterministic malformed-display/RST regression ran three separate
  `--rerun-tasks` invocations, each repeating the live `StreamClient` socket
  integration 25 times. All 75 interleavings preserved the inbound
  non-retryable `INVALID_DISPLAY` result, emitted no reconnect suggestion,
  and did not allow the concurrent startup-capability writer failure to mask
  it. The same three invocations also ran 25 deterministic ready-session EOF
  interleavings each: a startup-capability write failure was observed before
  the server closed, yet all 75 sessions preserved the more specific inbound
  `TRANSPORT_CLOSED` reason. A complementary writer-only case kept the peer's
  inbound direction open beyond the read poll and consistently selected the
  pending `WRITE_FAILED` reason.
- `swift build -c release --product Telemachus` passes. The release executable
  SHA-256 is
  `ce86c9f60418e4b34fd4fa9d6229ba103b32a47922b0abeec6dc14409b87ee76`.
  `.build/release/Telemachus --protocol-v1-self-test` reports `PASS` for
  framing, all shared cross-platform golden fixtures, version/required
  capability negotiation, display/video acknowledgement gating, stale epochs,
  input including two-pointer aggregation, heartbeat, errors, and media.
  The production `StreamingServer` loopback transport test also completes a
  real Protocol v1 upgrade/session, observes initial 90-degree rotation, and
  uses queue barriers to force an inbound Ping ahead of both a runtime rotation
  and a concurrent stop. The wire records preserve one connection/session
  owner and strictly increasing IDs (`Pong` before `DisplayChanged`, and
  `Pong` before the framed intentional `DisconnectNotice`). Separate loopback
  cases stop the server immediately after upgrade, during codec preparation,
  while awaiting the display request, while awaiting `VideoConfigResult`, and
  after streaming begins; every upgraded v1 stage receives a framed intentional
  shutdown. The session self-test also proves that a rotation changed during
  video negotiation is withheld until acceptance and then emitted as the
  latest `DisplayChanged` rather than leaking an early control message.
- The additive schema was regenerated into both MacHost and iOS Swift bindings.
  `swift build --package-path apps/ios` and the iOS core self-test pass, proving
  the checked binding update did not regress that consumer. Both iOS and
  release workflows run the same generated-binding verifier, which rejects
  tracked changes and path-scoped untracked files. A temporary additive proto
  produced an untracked Swift binding and made the verifier fail; removing it
  and regenerating restored a clean pass.
- `swift test --filter ProtocolV1SessionTests` failed in this historical local
  run with `no such module 'XCTest'`: that machine selected
  `/Library/Developer/CommandLineTools`, not full Xcode. The equivalent pure
  host self-test was the evidence available for this change at that time.

## Main Xcode verification snapshot (2026-08-06)

On 2026-08-06, main commit `4c2e908fe31af4c187684991301e163371444eab`
completed GitHub Actions Phase 0
[run 31084214883](https://github.com/TaoSama/vibe-screen/actions/runs/31084214883)
successfully. Its `macos-15` job passed `make baseline-macos-build`,
`make baseline-macos-self-test`, `make baseline-macos-test` (202/202 tests), and
`make baseline-macos-app`; protocol, Android, Phase 3, and evidence-tool jobs
also passed. The same SHA passed iOS engineering
[run 31084214830](https://github.com/TaoSama/vibe-screen/actions/runs/31084214830)
and HarmonyOS portable
[run 31084214856](https://github.com/TaoSama/vibe-screen/actions/runs/31084214856).
For that dated main commit, this closes the macOS XCTest execution gate. It
does not prove Developer ID signing, notarization, private display integration,
any new real-device behavior, iOS/HarmonyOS device behavior, latency, or soak
stability.

The 202/202 figure above is anchored to that dated 2026-08-06 commit. Main has
since advanced to `c639caa`, whose 2026-08-09 Phase 0 CI
[run 31332629511](https://github.com/TaoSama/vibe-screen/actions/runs/31332629511)
ran the MacHost XCTest `macos` job with 312 tests executed, 1 skipped, and 0
failures, alongside green protocol, Android, Phase 3, evidence, iOS, and
HarmonyOS-portable jobs. The count grew as tests were added; it is not
retroactively attributed to the earlier commit.

The available device lease was released after a screen-locked macOS host
reported zero ScreenCaptureKit displays; its attempted two-hour pre-warm never
started a valid clock and is not evidence. No Protocol v1 APK install, app
launch, media-port probe, or device stream was performed for this integration
record. A future device run must acquire a fresh exclusive lease and prove the
new wire mode from host/client logs before it can close the interoperability
gate.

## Final coordinated device acceptance (2026-08-04)

The final device run used a controlled ADB endpoint, redacted here as
`$ADB_ENDPOINT`; it is historical evidence, not a script default. The device
identified itself as Nubia P0110 (`pacific`), hardware serial `[redacted]`,
Android 16 / SDK 36, fingerprint
`nubia/pacific/pacific:16/2.5.2.0/20260804.003241:userdebug/test-keys`.
It is not the Xiaomi 13 (model 2211133C, codename fuxi) primary target, so this
run proves interoperability on the recorded Nubia device but does not close the
Xiaomi-specific Phase 0 criterion; later Xiaomi 13 evidence is recorded under
`evidence/2026-08-08-xiaomi12-fuxi-8a023e3a/` and
`evidence/2026-08-09-xiaomi-fuxi-soak2h-v2/`.

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
slow leak. A valid two-hour run has since been recorded on the Xiaomi 13 on
2026-08-09 (240 samples, mean 59.94 FPS, stable client memory): the stream and
process gates held, but host RSS still grew about 18.3 MB with a +96.5 KiB/min
second-half slope, so the Phase 1 no-growth target is still not met. See
`evidence/2026-08-09-xiaomi-fuxi-soak2h-v2/README.md` and
`../2026-08-10-host-rss-growth/TECH.md`.

Two earlier windows are explicitly invalid. The first was interrupted by a
concurrent APK install. A later 30-minute attempt was disturbed by a local
HTTP probe that sent `GET / HTTP/1.1` to the media port; the Host treated it as
a client and the Android stream recovered in about two seconds. That attempt
is retained under `.build/evidence/soak-30m-invalid-local-http-probe-*` and is
not used for the accepted result. The final Host was pre-warmed beyond the
one-time probe before starting the accepted clock.

Detailed commands, hashes, and artifact locations are recorded in
[`evidence/device-nubia-p0110-android16/FINAL_ACCEPTANCE.md`](evidence/device-nubia-p0110-android16/FINAL_ACCEPTANCE.md).

## Current-tree Nubia P0110 USB smoke (2026-08-20)

Main commit 0844991ea6ca55905349abb5f57291990454f0ad completed a short
current-tree USB smoke on the connected Nubia P0110 (pacific) device,
recorded as a pseudonymous explicit ADB target, Android 16 / SDK 36. The macOS
Host and Android debug APK were rebuilt from that commit, a stale Host from
another worktree was recorded and stopped, adb reverse tcp:54321 tcp:54321 was
established for the P0110 target, and the current-tree Host listened on
127.0.0.1:54321 as PID 97995.

The Android client connected over loopback USB, negotiated Protocol v1,
received a three-display catalog with virtual display 6 selected, configured
c2.qti.hevc.decoder for 2000x1200, produced first output, and recorded
short-window 60 FPS decode counters through output #720 with dropped=0.
A force-stop/cold-start reconnect kept Host PID 97995, established Host
connection epoch 2, and recorded fresh HEVC output counters through #840 with
dropped=0. This record is P0110/pacific evidence only; it is not Xiaomi
13/fuxi evidence and does not close the two-hour soak, host RSS no-growth,
native pointer HID, physical stylus, controller runtime, external-camera
latency, rotated host-display, or Accessibility/input gates.

Evidence is retained under
[evidence/2026-08-20-nubia-p0110-usb-smoke/](evidence/2026-08-20-nubia-p0110-usb-smoke/README.md).

## Current-tree Nubia P0110 USB smoke refresh (2026-08-22)

A 2026-08-22 lock-coordinated refresh was collected while this PR worktree was
rebased to `321eb3918026184a1b26ba8509ddee5f2d99878f` on top of
`origin/main` `baaec28a2a47bd9c2ff38a32eaacdbf1880f1e38`. The installed
Host/App binary provenance was not revalidated in this refresh. The connected
Nubia P0110/pacific Android 16 device produced a 20-second current-window USB
stream sample after clearing logcat. The app PID-scoped logcat window recorded
20 `stream_stats` events, 19 decoder-stat samples, `dropped=0`, no
AndroidRuntime/FATAL crash, and an empty `/data/tombstones` listing. The Host
still listened on 127.0.0.1:54321 and the host-side loopback socket remained
ESTABLISHED. This refresh is only short USB stream evidence and does not close
the soak, host RSS no-growth, input, LAN/Internet, external latency, or
headless Mac gates. Evidence is retained under
[evidence/2026-08-22-nubia-p0110-usb-smoke-refresh/](evidence/2026-08-22-nubia-p0110-usb-smoke-refresh/README.md).

## Current-base Nubia P0110 USB recheck (2026-08-23)

Origin/main commit `50694049096783466481f418c41a5eb50740e871` was rechecked on
the connected Nubia P0110 (pacific), serial `EP0110PZ0B9110300B`, Android 16 /
SDK 36. The current Android debug APK installed successfully and the P0110 ADB
target reported `UsbFfs tcp:54321 tcp:54321`, but this attempt did not establish
a current-base USB stream.

The supported stable Host preflight failed because the local keychain lacked the
documented `Vibe Screen Dev` codesigning identity. An ad-hoc current-source
`.app` could be launched, but no current-base `54321` listener was observed and
the retained artifacts do not isolate Screen Recording/TCC state from local
port/process state. The read-only `usb_live_smoke` collector then returned
`insufficient`: the Android package was not running, was not foregrounded, and
current-process logcat had no `stream_stats`, decoder setup, first output frame,
or decoder counters.

This is fail-closed readiness evidence only. It does not prove current-base USB
streaming, Protocol v1 interoperability, decoder output, reconnect, or
app-lifecycle recovery, and it does not change any two-hour soak, Host RSS,
latency, native-pointer, stylus, controller, rotated-display, login-startup,
headless, LAN, Internet, or AV1 gate. Evidence is retained under
[evidence/2026-08-23-nubia-p0110-usb-current-base/](evidence/2026-08-23-nubia-p0110-usb-current-base/README.md).

## External latency readiness check (2026-08-20)

Main commit `b9d768e55c75f03cd3cb5d20939576bc8d24ff27` completed a latency
toolchain/readiness check for the README external gate profiles
`usb-glass-to-glass-sub50`, `lan-glass-to-glass-sub80`, and
`input-p95-sub50`. The standard-library test path ran 41 latency tests with
zero failures, and CLI fixture reruns confirmed pass, fail, insufficient,
telemetry-stage informational, and formal provenance-checker behavior.

The repository scan found no high-frame-rate external-camera package with a
formal latency manifest, raw camera recording, and sample annotations outside
the synthetic `tools/fixtures/latency/` data. Therefore this record is blocked
readiness evidence only and does not close any external latency gate. Evidence
is retained under
[evidence/2026-08-20-latency-gates-readiness-blocked/](evidence/2026-08-20-latency-gates-readiness-blocked/README.md).

On 2026-08-21, origin/main commit
`cc26a84c829016fa61c721f73a128284fdf64f92` refreshed the same gate boundary
with the connected Nubia P0110/pacific Android 16 substitute recorded under a
pseudonymous device id. The UTC machine timestamps correspond to the local
2026-08-21 evidence date. The device identity preflight passed, but no
high-frame-rate external-camera package or synchronized-clock input package was
available, so `usb-glass-to-glass-sub50`, `lan-glass-to-glass-sub80`, and
`input-p95-sub50` all remain open. Evidence is retained under
[evidence/2026-08-21-nubia-p0110-latency-preflight-blocked/](evidence/2026-08-21-nubia-p0110-latency-preflight-blocked/README.md).

## Still unproved

- Developer ID signing and notarization;
- real-window restore after disconnect on device;
- a host-RSS-stable two-hour no-growth run (the two-hour Xiaomi 13 soak ran but
  host RSS grew about 18.3 MB), native-pointer HID move/click with a physical
  mouse, controller runtime acceptance with a physical Android controller and
  entitled Host, and external USB/LAN glass-to-glass plus input latency.

Private `CGVirtualDisplay` creation/capture and HiDPI, graceful mirror-mode
fallback, keyboard/scroll input, and Protocol v1 real-device interoperability
that were previously listed here are now verified on the Xiaomi 13; see Phase 1
and the Xiaomi 13 evidence directories.

These remain required work. They must not be converted into assumed passes.
