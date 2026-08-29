# Vibe Screen evidence tools

This directory contains dependency-free Python tools for collecting reproducible
device evidence and summarizing externally measured latency samples. Run each
CLI with `--help` for its accepted inputs and output contract.

Evidence is data, not a pass/fail claim. In particular, USB and LAN
glass-to-glass latency must come from a single external-camera timeline. Input
latency may use the same external-camera method or a synchronized-clock package
whose clock synchronization and uncertainty are independently documented. Host
and device timestamps without that proof are diagnostics only.

The JSON schemas in `schemas/` are versioned as `vibescreen.evidence/v1`.
Producers should write a manifest beside raw JSONL/CSV and derived summaries so
the exact command, repository state, host, device, and measurement method remain
auditable.

## Phase 1 actionable-error state matrix

The Phase 1 actionable-error owner matrix is an offline contract for the
Android and macOS Host states that should give the user a concrete recovery
action. It validates coverage only; it does not launch the Host, run ADB,
exercise Android UI rendering, or close the README Phase 1 gate.

```sh
make actionable-error-states-gate
```

The gate consumes
`docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json`,
checks that open PRs #242, #243, and #272 were reviewed as adjacent work, and
parses Android `SessionFailureKind` from source so new terminal failure kinds
cannot be added without a documented recovery owner. The generated report is
`.build/evidence/actionable-error-states-gate.json`, and it always records
`can_close_readme_phase1_actionable_errors_gate=false` until retained device
evidence covers every supported state.

## iOS current-base readiness

The current-base iOS aggregate owner is PR #290. Merged PR #182 remains the
historical sanitized device-acceptance baseline. Use the aggregate gate to keep
the current owner connected to the narrower signing, VideoToolbox, iOS advanced
adapter, Host advanced-adapter, AVAudioEngine/PCM, HDR, native-input,
reconnect, and trusted-LAN secure-record tasks without claiming a device pass
before real iPhone and iPad evidence exists:

```sh
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

The target writes `ios-current-base-manifest.json` and
`ios-current-base-gate.json`. The command exits `0` only for a complete formal
aggregate pass. Missing signing identities, missing iPhone/iPad hardware,
Simulator-only evidence, unsigned archives, MacHost loopback, Android evidence,
or plaintext legacy fallback produce `blocked`, `insufficient`, or `fail` with
`can_close_ios_device_acceptance=false`. That nonzero result is the expected
fail-closed readiness evidence when no iOS device run is scheduled.
The manifest and gate report retain per-gate `owner_pr` values. Hardware
VideoToolbox H.264/HEVC is owned by #251, and Host advanced adapters are owned
by #253. Passing status plus evidence under the wrong owner still fails closed,
so the #290 aggregate cannot accidentally close those open readiness gates.

## Phase 0 stable-release aggregate gate

The Phase 0 stable-release aggregate gate is intentionally separate from the
individual evidence tools. Run `make phase0-stable-release-gate` to verify that
README still carries the in-progress guard while any required sub-gate is open.
Before changing README to complete/stable Phase 0 wording, run `make
phase0-stable-release-gate PHASE0_STABLE_RELEASE_REQUIRE_PASS=1`; that command
fails closed until every required entry in
`docs/changes/2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json`
has verdict `pass` with closing-strength evidence. Historical real-device
evidence is accepted only for the Android USB baseline gate; current-source
runtime, latency, Host RSS, hardware compatibility, HID, controller, and module
ownership gates require their gate-specific closing evidence.
Pass `PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT=$(git rev-parse HEAD)` when
refreshing or auditing the aggregate owner so the summary records whether the
manifest is bound to the evaluated source commit; a mismatch is reported as
`source_guard.verdict=insufficient` and cannot pass the release-claim gate.

The iOS HDR output / EDR rendering row has a narrower dedicated owner. It
validates retained physical-device HDR observations and returns nonzero for the
expected no-device or SDR-only current state:

```sh
make ios-hdr-edr-gate EVIDENCE_DIR=.build/evidence/ios-hdr-edr
```

`ios-hdr-edr-gate` reads `ios-hdr-edr-observations.json` and writes
`ios-hdr-edr-gate.json`. It passes only with a physical iPhone/iPad HDR-capable
display, EDR headroom, `CAPABILITY_HDR_VIDEO`, accepted HDR config, 10-bit
PQ/HLG VideoToolbox output metadata, EDR renderer enablement, visible output
diagnostics, same-revision SDR fallback, and retained artifacts. Simulator,
unsigned archive, Android, protocol-only, macOS fallback, or SDR fallback
substitution returns `fail` and keeps `can_close_ios_hdr_output_gate=false`.

## iOS app-signing readiness

The app-signing readiness gate is the dedicated current-base owner for the
Phase 5 signing prerequisite. It validates a sanitized JSON summary from an
operator-controlled Xcode archive/signing check. It is read-only and does not
run Xcode, install an app, use Simulator output, or operate any device. It exits
`0` only when the summary records all signing prerequisites from a clean
current-base commit: sanitized Team ID and provisioning profile UUID digests,
unique bundle ID, sanitized non-ad-hoc codesign identity digest, registered
physical-device UDID hashes, signed-app entitlement relationship checks, signed
artifact SHA-256, and retained local artifacts for the
archive command, codesign entitlements, and provisioning profile output.

```sh
make ios-app-signing-readiness-gate \
  IOS_APP_SIGNING_READINESS_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-signing/ios-app-signing-readiness.json
```

The target writes `ios-app-signing-readiness-gate.json` next to the input. The
gate output declares `owner.role=ios_app_signing_readiness_current_base_owner`
and records `current_base.commit`, `current_base.branch`, and
`current_base.dirty`. `blocked` means required signing material, clean commit
state, or required artifact categories are missing; `fail` means the evidence
tries to use Simulator, unsigned, ad-hoc, or Android-derived material. A signing
readiness pass can unblock the current-base signing prerequisite only after the
same gate JSON is bound into `ios-current-base-manifest`;
`ios-current-base-gate` validates both the gate result and owner identity before
accepting the gate's sanitized `signing_summary` as the aggregate `signing` row,
including UDID-hash and entitlements coverage. It still reports
`can_close_ios_device_acceptance=false` because install, launch, decode, input,
reconnect, and audio behavior require real iPhone and iPad runs. The
current-base manifest's local codesigning probe records only status and the
number of valid identities; raw certificate hashes, identity names, Team IDs,
profile UUIDs, device UDIDs, and local paths must stay out of committed
evidence and PR text.

## Phase 5 multi-client/display current-base gate

The Phase 5 multi-client/display gate is a read-only current-base owner for the
planned simultaneous multi-client display capability. It separates one client
switching between multiple displays from two or more clients streaming at the
same time. Single-client display-selection, display-switch, or iOS-only registry
evidence cannot close this gate.

```sh
make phase5-multi-client-current-base-gate \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>
```

The target reads `multi-client-concurrency.json` from `EVIDENCE_DIR` and writes
`phase5-multi-client-current-base-gate.json`. Missing evidence returns
`blocked`; single-client multi-display evidence returns `insufficient`; device
identity relabeling, such as recording a Nubia P0110/pacific run as Xiaomi/fuxi,
returns `fail`. A pass requires retained JSON artifact files with the expected
Phase 5 `kind`, matching `source_revision`, and true observations for the
artifact-specific routing, transport, display, Host, or Android-client claim.
Those artifacts cover Host routing, transport ownership, display identity,
macOS Host, and two Android client records, plus explicit truth fields for
simultaneous clients, distinct session IDs/epochs, independent transport
connections, per-client route binding, frame queue or broadcast ownership, input
target isolation, a defined capture ownership model, Host multi-client
advertisement, and visible distinct streams on Android clients.

Codec capability evidence must record the negotiated Protocol v1 codec, the
Host encoder capability and implementation path, the client decoder name, and
the first decoded output frame before it is used to close a codec gate. AV1 is
currently a planned codec only: offline fail-closed/admission tests and blocked
runbooks do not prove an AV1 stream.

Trusted-LAN smoke evidence must be checked before changing README or release
notes based on a LAN run. A passing real-device record must include non-legacy
encrypted LAN markers from both peers, Protocol v1 over TRANSPORT_KIND_LAN,
HEVC decode with real output frames, and reconnect with the Host PID preserved.
A blocked record is valid only when it names the Nubia P0110 / pacific /
Android 16 / SDK 36 device, records concrete Wi-Fi/route and Host signing/preflight
blockers, and explicitly states that no real trusted-LAN stream was observed.

Run the checker with:

    make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/<run-dir>

Native pointer HID mouse evidence is hardware-gated in the same way. The Android
device must expose a real external mouse-like source (`MOUSE`,
`MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL`), and the same observation
window must retain Android forwarding logs, Host `Pointer injected` logs, and a
visible Mac pointer/click result note. Synthetic `adb shell input mouse` or
direct Protocol v1 calls are diagnostics only; they cannot close the native
pointer move/click gate. Use `make native-pointer-hid-acceptance` to collect a
bundle and `make native-pointer-hid-gate` to re-check an existing bundle. The
gate is closed only when `native-pointer-hid-summary.json` reports
`verdict=pass` and `can_close_native_pointer_hid_gate=true`.

Android Protocol v1 audio playback evidence is also fail-closed. The summary
tool reads a retained `android-audio-playback-observations.json` and writes
`android-audio-playback-summary.json`:

```sh
make android-audio-playback-gate EVIDENCE_DIR=docs/changes/<change>/evidence/<run>
```

The target exits `0` only when the summary can close the gate. A pass requires
the named Android device, structured device identity, USB or trusted-LAN
transport, stable signed Host plus Microphone permission, production Protocol v1
`CAPABILITY_AUDIO` negotiation, accepted PCM S16LE config, Host channel `3`
packet flow, Android `AudioTrack` start/write evidence, audible or
instrumentation-backed playback confirmation, disconnect cleanup, and non-empty
retained artifacts under the evidence directory. Loopback, synthetic,
Android-only, or plaintext legacy records return `blocked` or `insufficient` and keep
`can_close_android_audio_playback_gate=false`.
For current-base owner records that intentionally preserve a blocked or
insufficient result, use `make android-audio-playback-owner-record` with the
same `EVIDENCE_DIR`; it writes the same summary without requiring a passing
gate.

iOS native-input behavior is owned by the
`phase5-ios-native-input-behavior` gate. Summarize a sanitized device-run
observation file with:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.ios_native_input \
  docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>/ios-native-input-observations.json \
  --repo . \
  --output docs/changes/2026-08-04-phase-5-ios-advanced/evidence/<run>/ios-native-input-gate.json \
  --require-pass
```

The CLI is deliberately fail-closed. It requires real iPhone and iPad signed app
runs, physical keyboard, hover or pointer accessory, Protocol v1 session
and capability evidence, selected display/stream routing, Host
acknowledgements, and retained iOS/Host logs. Android evidence, Simulator
evidence, and offline input tests are readiness signals only and cannot close
the iOS native-input behavior gate.

Run the tests without installing third-party packages:

```sh
PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v
```

## Touch rerun evidence

The fixed-binary touch-gesture rerun uses two fail-closed helpers. First collect a
read-only preflight with the expected Host SHA-256 and, when the target device is
known, expected Android identity fields. The preflight records `blocked` if the
installed Host binary, TCC grants, or device identity are not ready. It does not
start the Host, run instrumentation, change ADB reverse mappings, modify privacy
databases or Keychain state, or clear Android app data.

After the opt-in gesture driver, run `make evidence-touch-rerun-summary` against
the retained preflight, instrumentation output, Host log, and listen-only event
tap log. It exits zero only when all artifacts support the pass claim; otherwise
it writes a blocked `result-summary.json`. A Nubia P0110/pacific pass is scoped to
general Android substitute evidence and must not be relabeled as Xiaomi 13/fuxi.

## HarmonyOS current-base owner gate

The HarmonyOS Phase 4 owner gate is a read-only aggregate for the README
DevEco build, signed-HAP install, hardware decode, HUKS secure-pairing,
authenticated transport, resume-capable Host interoperability, and MatePad
Mini acceptance claims. It consumes a readiness preflight and a final device
manifest; it does not run DevEco, install a HAP, start the Host, pair with a
device, decode frames, or produce MatePad Mini evidence:

```sh
make harmony-current-base-gate EVIDENCE_DIR=.build/evidence/harmony-current-base
```

The target reads `harmony-readiness.json` and `harmony-device-gates.json`, then
writes `harmony-current-base-gate.json`. It exits `0` only when every owner
gate is backed by a passing readiness preflight and a passing MatePad Mini
device-gate manifest with local relative evidence artifacts under the evidence
package. Missing DevEco/OHPM/Hvigor/HDC, signed-HAP, MatePad Mini HDC target,
Protocol v1 Host build, H.264/HEVC hardware-decode evidence, HAP install
evidence, HUKS secure-pairing evidence, authenticated transport evidence,
Host resume evidence, eight-hour soak, or external-camera latency returns
`blocked`; Android substitution returns `fail`.

## WakeHost current-base gate

After rebasing onto the merged PR #225 authenticated magic-packet baseline, PR
#199 owns the WakeHost current-base evidence boundary. Use the gate to summarize
retained sleeping-Mac Wake-on-LAN evidence without treating offline HMAC/protocol
tests as a hardware pass:

```sh
make wake-host-current-base-gate EVIDENCE_DIR=.build/evidence/wake-host-current-base
```

With no explicit `WAKE_HOST_CURRENT_BASE_JSON`, the target writes a default
blocked observation file plus `wake-host-current-base-gate.json`. A pass requires
real Mac sleep/wake evidence, identity-signed Host/TCC readiness, Wake for
network access or NIC WOL settings, verified router broadcast or directed WOL
delivery, packet capture or router logs, post-wake Host availability, and
negative rejected attempts for unpaired, expired, replayed, and wrong-signature
requests.

## iOS device acceptance gate

The iOS gate validates a sanitized `acceptance.json` after a separately
scheduled iPhone/iPad run. It is intentionally read-only: it does not invoke
Xcode, start the Host, connect to LAN, use ADB, or operate a device. A `pass`
requires both iPhone and iPad hardware records, complete signing/install,
Protocol v1 session, H.264 and HEVC VideoToolbox, input, reconnect, and audio
playback gates, plus retained local artifacts for every gate. The sanitized
`acceptance.json` must also embed the passing
`ios-app-signing-readiness-gate.json` from the dedicated signing owner; the
device gate checks that owner, current-base commit, bundle ID, signed artifact
digest, codesign identity, device UDID hashes, and entitlements match before it
accepts the legacy signing row. Open or blocked readiness records return
`insufficient`; Android artifacts or identities return `fail`.

```sh
make ios-device-acceptance-gate \
  IOS_ACCEPTANCE_JSON=docs/changes/2026-08-04-phase-5-ios-advanced/evidence/YYYY-MM-DD-ios-device/acceptance.json
```

## Phase 3 real-media continuity preflight

Use the Phase 3 continuity evaluator after collecting retained Host and Android
logs from a real Internet product-session attempt. It checks for the narrow
ScreenCaptureKit/CGDisplayStream -> VideoToolbox -> WebRTC -> Android
MediaCodec continuity slice: route/ICE evidence, Protocol v1 media epoch, real
capture-source metadata, capture first frame, VideoToolbox output epoch,
decoder configuration, first decoder input epoch, first decoder output epoch,
continuous output count, drops, and decoder errors.

The evaluator is passive and fail-closed. It does not start the Host, change TCC,
touch ADB, or close the Phase 3 release gate. A `pass` only means the supplied
logs satisfy this continuity slice; the generated JSON always keeps
`gate_can_close_phase3_release` false. Missing public-Internet route evidence,
identity-signed Host evidence, Screen Recording permission, real capture-source
metadata, real capture, VideoToolbox output, VideoToolbox output epoch,
MediaCodec output, a shared VideoToolbox-to-MediaCodec epoch, or synthetic-media
contamination returns `blocked`. Runtime decoder errors or excess dropped frames
return `fail` only after the required runtime stages are otherwise present.

Exit codes are `0` for `pass`, `1` for `blocked`, `2` for runtime `fail`, and
`3` for input or invocation errors.

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_real_media_continuity \
  --host-log path/to/host-log-redacted.txt \
  --android-log path/to/logcat-redacted.txt \
  --device-info path/to/device-info.json \
  --network-path public_internet \
  --host-signing identity_signed \
  --screen-recording granted \
  --minimum-output-frames 120 \
  --maximum-dropped-frames 0 \
  --output path/to/real-media-continuity.json
```

The Makefile wrapper writes `$(EVIDENCE_DIR)/real-media-continuity.json` and
returns nonzero for `blocked` or `fail` results while preserving the output for
audit:

```sh
make phase3-real-media-continuity \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run> \
  PHASE3_HOST_LOG=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/host-log-redacted.txt \
  PHASE3_ANDROID_LOG=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/logcat-redacted.txt \
  PHASE3_NETWORK_PATH=public_internet \
  PHASE3_HOST_SIGNING=identity_signed \
  PHASE3_SCREEN_RECORDING=granted
```

To bind that narrow continuity result to the current repository HEAD and to a
retained Android visible-UI artifact, run the current-base child gate:

```sh
make phase3-real-media-current-base \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run> \
  PHASE3_REAL_MEDIA_CONTINUITY_JSON=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/real-media-continuity.json \
  PHASE3_ANDROID_UI_EVIDENCE=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/android-visible-ui.png \
  PHASE3_ANDROID_UI_NOTE='operator confirmed decoded Mac desktop content visible in the Android UI'
```

The current-base gate writes `$(EVIDENCE_DIR)/current-base-real-media.json`.
It requires the continuity result to be a clean current-HEAD run, plus a real
Android device identity and a screenshot, screen recording, or external-camera
recording of the decoded UI. Missing UI evidence, old commits, dirty source,
local-only routes, synthetic media, missing identity signing, missing Screen
Recording permission, missing real capture-source metadata, missing
capture/encoder/decoder stages, no shared VideoToolbox-to-MediaCodec epoch,
decoder errors, or excess drops produce `blocked` or `fail`. A pass closes only
this child gate; remote TURN, handoff, revocation, latency, soak, and the
broader Phase 3 release gate remain separate.

## Phase 3 adaptive-media current-base gate

Use the adaptive-media current-base gate after a separately scheduled real
WebRTC Internet fluctuation run has produced a retained
`adaptive-media-fluctuation.json` report. The gate is passive and fail-closed:
it does not start the Host, touch ADB, change network settings, or close the
Phase 3 release gate. A `pass` is only a child-gate claim for the current clean
source revision.

```sh
make phase3-adaptive-media-current-base \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run> \
  PHASE3_ADAPTIVE_MEDIA_REPORT=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/adaptive-media-fluctuation.json
```

The input report must prove public-Internet WebRTC scope, controlled real
network impairment, real WebRTC statistics, raw Host/Android/WebRTC stats
sources, fast-drop/slow-rise adaptation, bitrate/FPS changes, increasing
`config_epoch` values, `VideoConfig` ACK before keyframe/resume, stale
generation rejection, rollback fail-closed behavior, and transport continuity.
Static latency fixtures, local loopback, deterministic network-profile output,
synthetic media, missing raw sources, or Nubia P0110 evidence relabeled away
from `pacific` return `blocked`; transport restarts or unsafe oscillation return
`fail`.

## Phase 3 advanced DataChannel current-base gate

Use this gate for the dedicated current-base owner of Internet DataChannel
audio, clipboard, and bulk file-transfer product flows:

```sh
make phase3-advanced-datachannel-current-base \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run> \
  PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON=docs/changes/2026-08-04-phase-3-secure-internet/evidence/<run>/advanced-datachannel-manifest.json
```

The target evaluates `advanced-datachannel-manifest.json` and writes
`advanced-datachannel-current-base.json`. To create the default blocked baseline
manifest first, run `make phase3-advanced-datachannel-blocked-baseline`. To
pass, retained evidence must prove all of these on the clean current base: real
macOS Host, real Android device, public Internet WebRTC route, identity-signed
Host, no plaintext fallback, no synthetic peer, PCM audio playback over
`vibescreen.audio.v1`, explicit clipboard transfer over the protected control
DataChannel, verified file transfer over `vibescreen.bulk.v1`, bounded
audio/bulk backpressure, and separate AES record domains for control, media,
audio, and bulk. Each gate evidence entry must be a retained relative file with
a matching SHA-256 hash and public-Internet product WebRTC metadata. USB/LAN TCP
records, iOS trusted-LAN records, local loopback or forced local coturn, and raw
channel hook unit tests fail closed if promoted as product-flow evidence. A pass
is only this child gate; the public Internet release gate remains separate.

## Device and soak evidence

The repository-level entry points require an explicit lease-controlled ADB
endpoint. Set it in the shell; the repository intentionally has no device
endpoint default:

```sh
export ADB_ENDPOINT='<lease-controlled-endpoint>'
make evidence-real-device-gate-preflight EVIDENCE_SERIAL="$ADB_ENDPOINT"
make evidence-device-info EVIDENCE_SERIAL="$ADB_ENDPOINT"
make soak-30m EVIDENCE_SERIAL="$ADB_ENDPOINT"
make soak-2h EVIDENCE_SERIAL="$ADB_ENDPOINT" HOST_PID="$HOST_PID"
make host-rss-gate EVIDENCE_DIR=.build/evidence
make soak-8h EVIDENCE_SERIAL="$ADB_ENDPOINT"
```

### Real-device readiness gate

`evidence-real-device-gate-preflight` writes
`.build/evidence/real-device-gate/real-device-gate.json`. It is the unified
readiness record for Android real-device work: device locks, exact ADB identity,
ADB reverse, Android foreground state, macOS Host listener, Host signing/TCC
preflight, and stream telemetry. By default, stream readiness requires fresh
structured `stream_stats` in `--host-telemetry-jsonl`; a timestamp-less Host log
`Pipeline:` line is only a legacy diagnostic when
`--allow-host-log-without-freshness` is passed. The default target is read-only
and exits `2` with `result=blocked` when any prerequisite is missing. Pass
explicit extra arguments only when the device owner wants the runner to prepare
Android-side state, for example:

```sh
make evidence-real-device-gate-preflight EVIDENCE_SERIAL="$ADB_ENDPOINT" \
  REAL_DEVICE_GATE_EXTRA_ARGS="--host-telemetry-jsonl <evidence-dir>/host-telemetry.jsonl --configure-adb-reverse --launch-android-app"
```

The runner still never starts the macOS Host, changes TCC, changes Keychain
state, or clears Android app data. A `ready` result means the session is ready
for a formal run; it does not close USB/LAN stream, latency, soak, Host RSS, or
physical-input gates by itself. Use `--require-soak-summary` to require a
complete soak summary. Use `--require-host-rss-gate` only with
`--soak-summary`, `--soak-samples`, and `--host-rss-exact-window-report`; the
Host RSS gate must consume the same exact-window telemetry report used by the
formal `host-rss-gate` target. Pass
`--require-latency-report <count>` or `--require-input-summary <count>` to make
missing retained latency/input evidence explicit in the same JSON report.
Additional `--lock-glob` values are checked in addition to the default
`/tmp/vibe-screen-device-*.lock` ownership guards. When a hardware-owner script
already holds a specific lease file, pass that exact path with `--held-lock` so
the preflight ignores the caller-owned lock while still blocking on every other
matching lock. For single-device owner runs that already hold their coordination
lock through the Make target, pass `EVIDENCE_ALLOW_EXISTING_LOCKS=1` so the
preflight records the lock and continues read-only probing instead of treating
that owned lock as an external blocker.

### File-transfer Android smoke gate

Use this gate for the dedicated Android/macOS Protocol v1 single-file transfer
smoke owner:

```sh
make file-transfer-android-smoke EVIDENCE_DIR=.build/evidence/file-transfer-android-smoke
```

The gate evaluates Host readiness, USB or trusted-LAN preflight, optional
Android file-transfer instrumentation output, and retained product E2E evidence
from both Android -> macOS and macOS -> Android directions. A pass requires a
real Nubia P0110/pacific Android 16 run with a ready transport, observed
file-offer/request/content packets, explicit sender action and receiver
approval, remote file write, positive session epoch, final SHA-256 equality,
and cancel/cleanup evidence. Missing product evidence,
synthetic/offline-only evidence, or a P0110 run relabeled as Xiaomi/fuxi remains
blocked or failed.

### USB live-stream smoke

The read-only USB live-stream smoke collector inspects an already-running
Android streaming session without installing, launching, stopping, or
reconfiguring anything. It records device identity, the ADB reverse mapping,
the foreground Activity, the application PID, VibeScreenTelemetry events, and
MediaCodec decoder stats, then writes a structured JSON summary.

```sh
make evidence-usb-live-smoke \
  EVIDENCE_SERIAL="$ADB_ENDPOINT" \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_PORT=54321 \
  EVIDENCE_DIR=.build/evidence/usb-live-smoke
```

The tool refuses to run ADB while `/tmp/vibe-screen-device-android.lock` or
`/tmp/vibe-screen-device-soak.lock` exists unless
`--allow-existing-device-lock` is supplied. When `--write-blocked-on-lock` is
set, it writes a `blocked` summary and exits non-zero. A `pass` verdict requires
the device to be ready, the `tcp:54321` reverse mapping to be present, the
Vibe Screen package to be installed and running in the foreground, at least one
current-process `stream_stats` telemetry event with positive FPS, and active
MediaCodec decoder output from current-process `logcat` lines. Fresh sessions
may include decoder setup and first-output lines; long-running sessions may
instead prove decoder activity through continuing frame counters. The app
private diagnostic log is recorded as context only. The summary always carries
`claims.readme_gate_closure=false` and a device-identity label guard so a Nubia
P0110/pacific run can never be relabeled as Xiaomi 13/fuxi evidence. To record
a blocked summary without touching ADB when another run holds the device lock,
invoke the module directly with `--write-blocked-on-lock`.

Outputs go under `.build/evidence/` by default. Each soak writes raw JSONL and
an atomic JSON summary containing connection coverage, process liveness,
reconnects, memory, thermal, battery, power, and optional host RSS series. Use
`EVIDENCE_DIR` and `EVIDENCE_PACKAGE` to select another archive directory or
application package. A non-`complete` summary returns a nonzero exit status.
Power-supply sysfs nodes are optional diagnostics: when an Android device does
not expose them to the ADB shell, their values are recorded as unavailable and
do not make an otherwise valid soak partial. ADB transport failures still do.
Start the host with `VIBE_SCREEN_TELEMETRY_PATH` pointing at the target's
`host-telemetry.jsonl` before the formal Makefile soak. The preset targets
require at least one `stream_stats` event and require the Android process to be
alive in every sample, so an idle collector cannot be reported as a stable
stream. Pass `HOST_PID` when the run needs Host RSS samples; the Phase 1
two-hour no-growth gate depends on `host.rss_kb` in `samples.jsonl`. Use
`make soak-2h-host-rss-gate EVIDENCE_SERIAL="$ADB_ENDPOINT"
HOST_PID="$HOST_PID"` for the formal Host RSS run and gate evaluation. That
target fails before the two-hour run when `HOST_PID` is unset, so missing Host
RSS samples cannot be mistaken for evaluable evidence.

For custom sampling, run `python3 -m vibescreen_evidence.soak --help` with
`PYTHONPATH=tools`. Disconnect and reconnect hooks receive
`VIBESCREEN_EVENT`, `VIBESCREEN_RUN_ID`, and `VIBESCREEN_ADB_SERIAL`; hook
commands must be supplied explicitly because interrupting ADB or the host is a
destructive test action.

After a run, derive exact-window metrics from its three raw artifacts:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report \
  --summary .build/evidence/soak-2h/summary.json \
  --samples .build/evidence/soak-2h/samples.jsonl \
  --host-telemetry .build/evidence/soak-2h/host-telemetry.jsonl \
  --output .build/evidence/soak-2h/exact-window-report.json
```

The report filters both sample and Host telemetry timestamps to the inclusive
`started_at`/`finished_at` window recorded by the summary. It preserves source
errors, reports malformed or empty inputs, and computes full-window and
second-half RSS regression slopes. Those slopes are descriptive evidence; the
tool deliberately does not turn them into a no-leak verdict.

For the Phase 1 two-hour Host RSS gate, run the separate fail-closed evaluator:

```sh
make host-rss-gate EVIDENCE_DIR=.build/evidence
```

This derives `.build/evidence/soak-2h/exact-window-report.json` first, then
writes `.build/evidence/soak-2h/host-rss-gate.json`. It exits zero only when
`host_rss_gate` reports `pass`.

The evaluator requires an error-free source soak of at least 7,056 seconds,
230 Host RSS samples, 115 second-half samples, samples within 90 seconds of
both window boundaries, and no internal sampling gap above 90 seconds. It also
requires a matching exact-window report derived from native
`VIBE_SCREEN_TELEMETRY_PATH` JSONL for the same summary window. Legacy
log-reencoded telemetry or a missing exact-window report is descriptive only and
cannot pass the formal Host RSS gate. A pass requires all of these steady-state
RSS limits:

- second-half OLS slope 95% upper bound no greater than 40 KiB/min;
- second-half Theil-Sen slope no greater than 40 KiB/min;
- second-half endpoint-median drift no greater than 4 MiB;
- full-window endpoint-median drift no greater than 8 MiB; and
- second-half final-quarter mean step no greater than 2 MiB.

The same pass also requires continuous Host stream telemetry in the exact
window: `stream_stats` and accepted `heartbeat_received` coverage without a
window gap above 90 seconds, positive FPS, zero `frame_queue_drop` total, stable
queue capacity with queue depth within that capacity, stable encoder in-flight
capacity with in-flight count and callback registry count within capacity,
latest pixel-buffer retention within its fixed capacity, and an encoder present
throughout the window. Missing lifecycle telemetry makes the gate
`insufficient`; bounded-queue or frame-retention overages make it `fail`.

The command exits zero only for `pass`; invalid, incomplete, or undersampled
evidence is `insufficient` and exits nonzero. A pass means the recorded window
did not show practically significant growth, not that longer or different
workloads cannot leak.

### Trusted LAN preflight

Before a real-device trusted-LAN smoke or reconnect run, collect the read-only
preflight result:

```sh
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the local device serial}"
make evidence-trusted-lan-preflight EVIDENCE_SERIAL="$ANDROID_SERIAL" EVIDENCE_DIR=.build/evidence/trusted-lan-preflight
```

The tool first records `pgrep -x sfltool` and acquires the serial-specific
Android coordination lock in a per-user mode-0700 runtime directory, with a
filename derived from a hash of the serial, before any ADB/device command. It
then checks the explicit Nubia P0110/pacific/Android 16 identity, Android Wi-Fi
association, wlan0 IPv4, route to a Mac LAN IPv4 candidate, and the stable Host
signing/TCC preflight. It exits 0 only when the environment is ready to start
the real LAN smoke. It exits 2 for a blocked
preflight and still writes trusted-lan-preflight.json; keep that JSON as blocked
evidence and stop before Host launch, QR/token exchange, stream, reconnect, or
latency capture. The preflight intentionally does not start the Host, run
instrumentation, modify TCC, alter Keychain, change saved Wi-Fi credentials, or
write pairing secrets.

For the Phase 2 tablet productization eight-hour soak, derive the exact-window
report and then evaluate the tablet gate:

Before the timer starts, create a Phase 2 manifest that predeclares the physical
setup, device class, host/APK identity, thresholds, and planned recovery
scenarios:

```sh
make phase2-tablet-manifest EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR=.build/evidence \
  PHASE2_DEVICE_CLASS=physical_8_9_inch_tablet \
  PHASE2_TABLET_SIZE_INCHES="8.8" \
  PHASE2_STAND_SETUP="desktop stand, portrait" \
  PHASE2_CHARGER="vendor USB-C charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="Balanced, 60 FPS, AUTO bitrate" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="host build command, signing identity, and SHA" \
  PHASE2_APK_SHA256="debug or release APK SHA-256" \
  PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS=45 \
  PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT=5 \
  EVIDENCE_HOST_PID="$HOST_PID" \
  PHASE2_GATE_OWNERS="stand_mounted_charging=phase2-device-environment,thermal_power_sampling=phase2-device-environment,posture_and_mount=phase2-device-environment,eight_hour_sustained_stream=phase2-tablet-gate"
```

Use `PHASE2_DEVICE_CLASS=android_substitute` for Nubia P0110/pacific/Android 16
or another phone substitute. That records useful readiness data, but it cannot
close the 8-9 inch tablet gate and must not be relabeled as Xiaomi/fuxi or
physical-tablet evidence. Physical-tablet manifests must declare
`PHASE2_TABLET_SIZE_INCHES` in the 8.0..9.0 range.

Run the eight-hour soak with the same Host process ID so each sample carries
both Android app PSS and Host RSS:

```sh
make soak-8h EVIDENCE_SERIAL="$ADB_SERIAL" EVIDENCE_DIR=.build/evidence \
  EVIDENCE_HOST_PID="$HOST_PID"
```

The Phase 2 device-memory gate is intentionally independent from the broader
tablet productization gate. It consumes the pre-run manifest plus the
exact-window report and fails closed when the manifest is not a physical
8-9 inch tablet, the run is shorter than eight hours, Android PSS is missing,
Host RSS is missing, charging/full-state samples are missing or not continuous,
or thermal status samples are missing:

```sh
make phase2-device-memory-gate EVIDENCE_DIR=.build/evidence
```

For an end-to-end readiness check that gathers the same raw inputs and writes an
explicit blocker record, use the wrapper target. After the wrapper passes the
precondition checks needed to start collection, it writes
`phase2-soak-readiness.json`, `README.md`, static device/Host artifacts, Android
log derivatives, and either `soak-preflight/` or `soak-8h/` depending on mode.
Blocked runs write readiness evidence and only the artifacts collected before
the blocker:

```sh
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the local device serial}"
make phase2-tablet-soak-preflight EVIDENCE_SERIAL="$ANDROID_SERIAL" \
  EVIDENCE_DIR=.build/evidence/phase2-preflight \
  PHASE2_DEVICE_CLASS=android_substitute \
  PHASE2_STAND_SETUP="bench substitute phone, no 8-9 inch tablet stand" \
  PHASE2_CHARGER="recorded charger" \
  PHASE2_CABLE_OR_DOCK="USB-C data cable" \
  PHASE2_VIDEO_PREFERENCES="preflight only" \
  PHASE2_HOST_IDENTITY="Mac model and macOS version" \
  PHASE2_HOST_BUILD="not a formal signed Host run" \
  PHASE2_SOAK_PREFLIGHT_DURATION=2s \
  PHASE2_SOAK_INTERVAL=1s
```

If the wrapper finds `/tmp/vibe-screen-device-android.lock` or
`/tmp/vibe-screen-device-soak.lock`, it writes only
`phase2-soak-readiness.json` and `README.md` with `result=blocked`; it does not
run ADB or create static, logcat, or soak artifacts. Preflight may omit APK
identity; the wrapper records that as a readiness-only blocker instead of
writing fake SHA-256 evidence. Formal `run` mode must use `PHASE2_APK_PATH` or a
real 64-character hexadecimal `PHASE2_APK_SHA256`; placeholder values are
rejected before the gate can close.

Use `phase2-tablet-soak-run` only after the physical tablet, stand-mounted
charging setup, signed Host PID, and `VIBE_SCREEN_TELEMETRY_PATH` JSONL are all
ready. The formal target writes blocked evidence instead of starting the timer
when any required precondition is missing.

```sh
make phase2-tablet-gate EVIDENCE_DIR=.build/evidence
make phase2-tablet-preflight EVIDENCE_DIR=.build/evidence
```

The gates consume `.build/evidence/soak-8h/exact-window-report.json`,
`.build/evidence/phase2-tablet-manifest.json`, and the raw evidence files in
`.build/evidence/`, then write
`.build/evidence/soak-8h/phase2-device-memory-gate.json` and
`.build/evidence/soak-8h/phase2-tablet-gate.json`. The wrapper closes only
when `phase2-soak-readiness.json` reports `can_close_phase2_gate=true`. A
`pass` requires an
error-free eight-hour exact window with sufficient samples, continuous stream
stats and heartbeats, no session disconnects, no reported frame drops, bounded
Android PSS and Host RSS growth, battery/thermal readings below the Phase 2
thresholds, net battery drain within the manifest-declared limit, a manifest
declaring `physical_8_9_inch_tablet`, and the required raw
README/device/host/build/APK/battery/power/thermal/log/screenshot artifacts.
The gate also rejects known phone substitute identities such as Nubia
P0110/pacific if they are manually mislabeled as physical-tablet evidence.
The manifest must also predeclare owner entries for stand-mounted charging,
thermal/power sampling, posture/mount review, and the eight-hour stream verdict;
missing owner entries keep the gate `insufficient`.
`fail` means the evidence is complete but a productization threshold was
violated; `insufficient` means the evidence package cannot close the gate. Phone
substitute manifests such as Nubia P0110/pacific/Android 16 remain useful
readiness records and intentionally evaluate as `insufficient` for the formal
8-9 inch tablet gate. The commands do not replace the raw physical-tablet,
stand-mounted charging, login, headless, and background-recovery artifacts
required by the Phase 2 runbook.

The preflight consumes the whole evidence directory and writes
`.build/evidence/phase2-tablet-preflight.json`. It is fail-closed and exits
nonzero for `blocked`, `fail`, or `insufficient`. A `pass` requires the
schema-backed manifest to identify a physical 8-9 inch tablet, portrait and
landscape tablet screenshots, physical stylus evidence, hardware-keyboard
evidence, foreground/background and transport recovery evidence, the raw
thermal/power/log artifacts, and a passing eight-hour tablet soak gate. Use it
with `PHASE2_DEVICE_CLASS=android_substitute` to create blocked evidence for the
Nubia P0110/pacific or another non-tablet Android device; that result is useful
readiness evidence but cannot close Phase 2 tablet acceptance. The preflight
also rejects known phone substitutes such as Nubia P0110/pacific when a
hand-written manifest incorrectly labels them as `physical_8_9_inch_tablet`.

Use the aggregate owner report after child owners produce summaries, or when a
current-base audit needs to prove that the README Phase 2 gates remain open:

```sh
make phase2-aggregate-owner EVIDENCE_DIR=.build/evidence \
  PHASE2_TABLET_GATE=.build/evidence/soak-8h/phase2-tablet-gate.json \
  PHASE2_TABLET_MANIFEST=.build/evidence/phase2-tablet-manifest.json \
  PHASE2_HARDWARE_KEYBOARD=.build/evidence/hardware-keyboard-summary.json \
  PHASE2_DEVICE_MEMORY=.build/evidence/soak-8h/phase2-device-memory-gate.json
```

Optional inputs include `PHASE2_DEVICE_ENVIRONMENT`, `PHASE2_SOAK_READINESS`,
`PHASE2_TABLET_UI`, `PHASE2_RECOVERY`, and `PHASE2_LOGIN_HEADLESS`. Missing
inputs become blocked owner rows. The report can close README Phase 2 gates only
when every child gate provides an explicit pass or close signal and the
package-aware tablet gate passes with a physical 8-9 inch tablet manifest.

The login-startup/headless Mac mini owner input is produced from retained real
macOS integration evidence. It is a passive gate: it never changes Login Items,
grants TCC, reboots the Mac, starts the Host, or touches ADB.

```sh
make phase2-macos-startup-recovery-gate EVIDENCE_DIR=.build/evidence
make phase2-aggregate-owner EVIDENCE_DIR=.build/evidence \
  PHASE2_LOGIN_HEADLESS=.build/evidence/macos-startup-recovery-gate.json
```

The input file is `.build/evidence/macos-startup-recovery-evidence.json`. A pass
requires an identity-signed Host with current Screen Recording and Accessibility
grants, login item enabled and not awaiting approval, reboot or logout/login
launch evidence, automatic startup to a rendered client stream, capturable
physical/dummy/headless or Screen Sharing display evidence, bounded unattended
recovery logs, real window restore evidence, Android disconnect/reconnect with
post-reconnect render evidence, and a local or remote administrator path for
FileVault, first-login, TCC, and display intervention. Missing hardware
or permission prerequisites return `blocked` with
`can_close_login_headless_gate=false`; manual launches or relabeled display or
device identities return `fail`.

For the focused hardware-keyboard workflow, collect current-base readiness with
the exact Android serial before attempting physical input:

```sh
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the local device serial}"
make hardware-keyboard-readiness \
  EVIDENCE_SERIAL="$ANDROID_SERIAL" \
  EVIDENCE_DIR=.build/evidence/hardware-keyboard-readiness
```

The collector acquires the shared Android lock, records device/package/input
snapshots and Host listener/signing/TCC preflight artifacts, then writes
`hardware-keyboard-readiness.json`, `hardware-keyboard-observations.json`, and
`hardware-keyboard-summary.json`. It exits nonzero for blocked or insufficient
readiness; that is expected when the physical Android-attached keyboard, stable
signed/TCC-ready Host, active selected-display stream, production Protocol v1
forwarding plus focus/IME boundary logs, Host `Key injected:` or
acknowledgement/CGEvent logs, modifier press/release and cleanup proof, or
visible Mac-side result are missing.

## Phase 3 Internet Soak Gate

The Phase 3 Internet soak gate composes separately collected production evidence
instead of running the public service by itself. First write a manifest from the
reviewed production inputs:

```sh
make phase3-internet-soak-manifest PHASE3_INTERNET_SOAK_DIR=.build/phase3-internet-soak \
  PHASE3_INTERNET_TURN_URIS="turns:relay.prod.your-domain.com:5349?transport=tcp" \
  PHASE3_INTERNET_SIGNALING_ORIGIN=https://signaling.prod.your-domain.com \
  PHASE3_INTERNET_RELAY_ORIGIN=https://relay.prod.your-domain.com \
  PHASE3_INTERNET_AUTHORITY_SOURCE_ID=turn-prod-1 \
  PHASE3_INTERNET_REMOTE_PEER=peer.prod.your-domain.com \
  PHASE3_INTERNET_TLS_CERTIFICATE_SHA256=... \
  PHASE3_INTERNET_DEPLOYMENT_READINESS=authority-readyz,relay-readyz,coturn-tls \
  PHASE3_INTERNET_PLANNED_HANDOFFS=wifi-to-cellular \
  PHASE3_INTERNET_HOST_BUILD="Vibe Screen release build and SHA" \
  PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256=...
```

Then evaluate the gate after placing privacy-reviewed summaries in that same
directory:

```sh
make phase3-internet-soak-gate PHASE3_INTERNET_SOAK_DIR=.build/phase3-internet-soak
```

The default filenames are `remote-turn-verifier.json`, `media-continuity.json`,
`network-handoff.json`, `revocation-propagation.json`, and
`soak-exact-window-report.json`. The gate passes only with public remote TURN
packet exchange, real ScreenCaptureKit-to-Android decode continuity, fresh-session
handoff recovery, revocation propagation through active coturn allocation
disconnect and post-revocation packet denial, and a clean two-hour mixed
direct/relay soak. Missing reports are `blocked`; observed plaintext fallback or
secret-like fields in report inputs are `fail`. Set
`PHASE3_INTERNET_ALLOW_BLOCKED=1` only to archive a blocked record.

### Short Host memory regression gate

Use the bounded short diagnostic as a 10-17 minute regression gate before
spending another two hours on the formal gate run. It separates live retained
growth from allocator high-water and reports a top-level `verdict` in addition
to the memory `attribution`. Start the Host with `VIBE_SCREEN_TELEMETRY_PATH`
set, establish the normal stream, find that exact Host process ID, then run:

```sh
mkdir -p .build/evidence/memory-short
# Start the Host with:
# VIBE_SCREEN_TELEMETRY_PATH=.build/evidence/memory-short/host-telemetry.jsonl
PYTHONPATH=tools python3 -m vibescreen_evidence.host_memory_diagnostic \
  --host-pid "$HOST_PID" \
  --duration-seconds 900 \
  --interval-seconds 30 \
  --telemetry-jsonl .build/evidence/memory-short/host-telemetry.jsonl \
  --samples .build/evidence/memory-short/samples.jsonl \
  --output .build/evidence/memory-short/diagnostic.json
```

The command samples RSS, `footprint` physical footprint and VM categories, and
`vmmap` malloc-zone dirty/live/fragmentation bytes every interval. It takes
`heap -q -H -s` snapshots only at the start, midpoint, and end to reduce stream
disturbance. Host `stream_stats` must cover the same wall-clock window, remain
on one session epoch, and include continuous bounded network-queue depth even
when no frame is dropped. If VideoToolbox in-flight depth is present, the
diagnostic also validates it against its advertised capacity. Current Host
builds additionally include `frame_registry_count` plus the capture-side
`latest_pixel_buffer_retained`/`latest_pixel_buffer_capacity` pair and the
diagnostic `fallback_capture_active`/`encoder_present` booleans, letting the
same short-window report fail closed if retained VideoToolbox callback contexts
or the latest pixel-buffer cache exceed their fixed bounds. Older telemetry
without these optional fields remains readable, but a partially present pair or
non-boolean diagnostic state is treated as insufficient input.

The diagnostic report includes `metrics.heap_watch_summary`, which aggregates
first-to-last count and byte drift for the watched SwiftUI Observation,
autorelease-pool, and video-frame heap classes. This keeps the known Host RSS
suspects visible as structured evidence even when individual heap rows move in
or out of the top-growth list.

The report carries a top-level `verdict` with exactly three values:

- `pass`: the complete 10-17 minute window has sufficient samples, all required
  memory signals stay within the short-window stability thresholds, and stream
  telemetry plus bounded network queues stay healthy. Optional VideoToolbox
  in-flight, frame-registry, and latest pixel-buffer telemetry, when present,
  must also stay within capacity. This is a short-window regression result only
  and cannot replace or close the formal two-hour `host_rss_gate`.
- `fail`: the window attributes `retained_growth` or `allocator_high_water`, or
  the production stream reports a queue over capacity, an invalid or changing
  queue capacity, optional VideoToolbox in-flight/frame-registry over capacity,
  invalid or changing encoder capacity, latest pixel-buffer retention over
  capacity, or non-positive FPS.
- `insufficient`: sampling, tooling, parsing, or stream telemetry coverage is
  incomplete, or the memory signals conflict and do not support a stable or
  growth attribution.

`attribution` still has exactly three values for root-cause orientation:

- `retained_growth`: footprint, live malloc bytes, and heap objects grow together;
- `allocator_high_water`: resident allocator pages and fragmentation grow while
  live malloc bytes and heap objects stay flat;
- `inconclusive`: the short window is stable, incomplete, conflicting, or shows
  a pipeline-capacity anomaly.

Durations are restricted to 10-17 minutes so the final heap snapshot and report
remain within a 20-minute command budget. The diagnostic never invokes
`memory_pressure`, changes TCC, or accesses Keychain. Any tool error, missing
metric, missing stream telemetry coverage, session-epoch change, queue depth
above its advertised capacity, present encoder in-flight or frame-registry
depth above capacity, invalid or changing encoder capacity, present latest
pixel-buffer retention above capacity, or non-boolean diagnostic state
fails closed: the `verdict` becomes `insufficient` or `fail` and the
`attribution` stays `inconclusive`. The existing deterministic VideoEncoder and
mailbox tests remain the authoritative checks for the two-frame VideoToolbox
admission bound and the single-latest-frame mailbox bound.

Exit status follows the `verdict`: `0` for `pass`, `2` for `fail`, and `1` for
`insufficient`. None of these statuses is a formal two-hour gate result; every
short diagnostic report also carries
`gate.can_close_host_rss_no_growth_gate=false`. Automation must use
`host_rss_gate` for the formal two-hour no-growth decision.

There is currently no Xiaomi 13 short-window diagnostic evidence built against
this source tree, and this change introduces no new production memory fix. The
formal two-hour Host RSS no-growth gate remains open until a matching
`host_rss_gate` run reports `pass`.

### Host TCP socket FD diagnostic

When USB or LAN smoke evidence shows stale Host TCP entries on port `54321`,
sample the Host process with `lsof` and preserve the full output, including
`CLOSED`, `ESTABLISHED`, and `LISTEN` rows. The PID and TCP filters must be
combined with `-a`; otherwise `lsof` treats them as a broad OR query.

To summarize saved snapshots:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_socket_fd \
  --input /tmp/vibe-screen-p0110-e2e/root-usb-smoke-20260821-223447/host_lsof_before.txt \
  --output /tmp/vibe-screen-p0110-e2e/root-usb-smoke-20260821-223447/host-socket-fd.json
```

To collect a short read-only series from a running Host:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.host_socket_fd \
  --pid "$HOST_PID" \
  --port 54321 \
  --samples 13 \
  --interval-seconds 5 \
  --output .build/evidence/host-socket-fd.json
```

The report fails when the Host process still owns any TCP socket FD whose TCP
state is `CLOSED`, and it records whether the CLOSED count increased across
the sample window. This is a socket-lifecycle diagnostic only: its gate field
always keeps `can_close_host_rss_no_growth_gate=false`, and it cannot replace
the formal two-hour `host_rss_gate`.

## Reconnect timing evidence

The Phase 1 reconnect-within-three-seconds gate is separate from
glass-to-glass latency. It measures one recovery window from a declared
disruption start to the Android decoder's first output frame after a fresh
Protocol v1 recovery. A retry loop, Activity lifecycle callback, Host accept
line, or first received encoded frame alone is not sufficient.

For a complete gate record, collect one attempt for each required disruption:

- `client-kill`: force-stop or kill the Android client, cold-start it, and
  record the disruption timestamp before the kill.
- `adb-reverse-disconnect`: remove `tcp:54321`, restore it, and record the
  disruption timestamp before the removal plus `adb_reverse_restored=true`.
- `lan-network-interrupt`: interrupt the trusted-LAN route, restore it, and
  record secure-record markers proving encrypted LAN rather than plaintext
  fallback.

Each attempt must include the same Host PID before and after recovery, the Host
Protocol v1 connection epoch, and the disruption start in the same Android
millisecond timebase as the recovery markers. Those markers can come from the
private diag log (`Protocol v1 upgrade accepted`, `First frame:`, and `First
output frame!`) or from `VibeScreenTelemetry` logcat events. For logcat-only
attempts, `protocol_v1_accepted` with `session_epoch` is the Protocol v1
acceptance marker; existing `connection_opened`, `first_frame_received`, and
`first_output_frame` logcat events only supply connection/session and decoder
timing evidence and cannot independently prove Protocol v1. Until the
`protocol_v1_accepted` event is present in the captured logcat, the attempt must
remain `insufficient` or use the private diag log instead. Run the evaluator on
the observation JSON:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing observations.json \
  --output reconnect-timing-summary.json
```

The summary exits `0` only for `pass`, `1` for insufficient evidence, `2` for a
measured failure, and `3` for blocked prerequisites. During incremental real
device work, use `--require-disruption client-kill` or another single scenario
to validate a partial run without claiming the full three-scenario gate.
Consumers that decide README gate status must require `can_close_timing_gate=true`.
`verdict=pass` by itself may describe only the requested scoped scenario; those
partial passes are reported with `can_close_requested_scope=true` and still keep
`can_close_timing_gate=false`.

When prerequisites block the run, write a blocked record instead of promoting
older reconnect logs:

```sh
make evidence-reconnect-timing-blocked \
  EVIDENCE_DIR=docs/changes/<change>/evidence/<run> \
  RECONNECT_TIMING_BLOCKER_ARGS='--blocker "Vibe Screen Dev signing identity is unavailable" --blocker "Host is not listening on 127.0.0.1:54321"' \
  RECONNECT_TIMING_ARTIFACT_ARGS='--artifact "docs/changes/<change>/evidence/<run>/host-54321-listener.txt" --artifact "docs/changes/<change>/evidence/<run>/macos-dev-host-preflight.txt"' \
  RECONNECT_TIMING_NOTES_ARG='--notes "Blocked readiness record only; no real Protocol v1 reconnect timing attempt was run."'
```

or pass exact blockers directly:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.reconnect_timing \
  --blocked \
  --target-device "Nubia P0110 / pacific / Android 16 / ${ANDROID_SERIAL}" \
  --blocker "Vibe Screen Dev signing identity is unavailable" \
  --blocker "Host is not listening on 127.0.0.1:54321" \
  --output reconnect-timing-summary.json
```

Blocked or insufficient summaries cannot close the README reconnect timing
gate. Evidence from the Nubia P0110 must remain labeled P0110/pacific and must
not be relabeled as Xiaomi 13/fuxi.

## macOS Host compatibility evidence

Use `macos-hardware-compatibility-gate` to summarize one macOS Host hardware
compatibility matrix row after the row artifacts have already been collected:

```sh
make macos-hardware-compatibility-gate EVIDENCE_DIR=.build/evidence/macos-host-compatibility
```

The target consumes `macos-hardware-compatibility.json` and writes
`macos-hardware-compatibility-gate.json`. A `pass` closes only the exact row
recorded in the input: CPU architecture, Mac model, macOS build, display
topology, transport, Android counterpart, source-bound Host build/signing/TCC
state, capture backend, and retained artifacts. Missing row identity, clean
40-character repository commit, stable bundle id, non-ad-hoc signing identity,
authorized Screen Recording or Accessibility TCC state, installed Host source
commit/tree provenance, Host self-test/current-base provenance, packaged Host
launch, Protocol v1 stream, artifact retention, or exact-row scoping is
`blocked`; missing runtime probes are `insufficient`.
Marking CI-only evidence, extrapolating Apple silicon, OS-version,
display-topology, capture-backend, or virtual-display claims across rows, or
recording contradictory capture backend results is `failed`. The Python CLI exits
`0` only for `pass`, `1` for `blocked` or `insufficient`, and `2` for `failed`;
Make reports any non-pass verdict as target failure after writing the summary.
The collection checklist is in `docs/runbook/macos-host-compatibility.md`.

## Latency evidence

Latency evidence is split by what the measurement can prove:

- `glass-to-glass`: end-to-end display latency from Mac-visible stimulus to the
  rendered Android frame. This requires one external high-frame-rate camera or
  equivalent optical timebase. Host, Android, RTT, or decoder timestamps cannot
  close this gate.
- `input`: input-event latency from physical Android input to visible Mac
  result. Prefer the same external-camera method. A synchronized-clock run is
  acceptable only when the evidence records the synchronization method and error
  budget.
- `telemetry-stage`: host or client pipeline-stage timing used to diagnose where
  latency is spent. These summaries are informational and cannot close
  glass-to-glass or input latency gates.

For glass-to-glass, prepare a CSV with either `latency_ms`, or
`start_frame,end_frame,camera_fps` from one external-camera recording, then
summarize it:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency samples.csv \
  --kind glass-to-glass \
  --transport usb \
  --measurement-method external-camera \
  --gate-profile usb-glass-to-glass-sub50 \
  --output summary.json
```

Repeat the run with `--transport lan --gate-profile lan-glass-to-glass-sub80`
for LAN evidence. For input latency use `--kind input --gate-profile
input-p95-sub50`. Gate profiles evaluate P95 with a minimum sample count and
write `verdict=pass|fail|insufficient`; omit `--gate-profile` for a pure
summary. When a gate profile is supplied the exit status follows the verdict:
`0` for `pass`, `1` for `fail` or `insufficient`. Without `--gate-profile` the
command always exits `0`. The tool deliberately rejects a glass-to-glass claim
based on unsynchronized host and Android clocks. Keep the raw camera file,
sample CSV, summary, device info, and a formal latency manifest together;
create the manifest with the dedicated helper:

    PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
      --evidence-dir latency-run \
      --latency-kind glass-to-glass \
      --transport usb \
      --gate-profile usb-glass-to-glass-sub50 \
      --raw-video latency-run/raw-camera.mov \
      --samples latency-run/samples.csv \
      --samples-format csv \
      --annotation-method manual-frame-count \
      --camera-manufacturer "camera vendor" \
      --camera-model "camera model" \
      --camera-mode 1080p240 \
      --camera-frame-rate-fps 240 \
      --camera-shutter-mode fixed \
      --operator "operator name" \
      --annotator "annotator name" \
      --device-info latency-run/device-info.json \
      --host-artifact "host binary identity or hash" \
      --client-artifact "APK identity or hash" \
      --stimulus "visible Mac-side stimulus" \
      --start-event-definition "first camera frame where the stimulus is visible" \
      --end-event-definition "first camera frame where the result is visible" \
      --lighting "lighting conditions" \
      --mounting "camera and device mounting" \
      --max-frame-annotation-uncertainty-ms 4.2 \
      --gate-artifact latency-run/usb-connection.txt \
      --gate-artifact-description "ADB reverse/USB setup and active USB stream proof" \
      --notes "run-specific notes"

For an Internet manifest, use the same camera and build fields, switch to
`--transport internet --gate-profile internet-glass-to-glass-sub150`, and add
the public-route fields. Use `--different-private-network` only after recording
that the macOS Host and Android peer were not on the same private network.
`--turn-resolved-ip` must be the retained global IP from resolving the selected
TURN hostname during the run. Use `--same-private-network` for LAN/loopback
diagnostics, which will remain insufficient for the Internet gate:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_manifest \
  --evidence-dir latency-run \
  --latency-kind glass-to-glass \
  --transport internet \
  --gate-profile internet-glass-to-glass-sub150 \
  --raw-video latency-run/raw-camera.mov \
  --samples latency-run/samples.csv \
  --samples-format csv \
  --annotation-method manual-frame-count \
  --camera-manufacturer "camera vendor" \
  --camera-model "camera model" \
  --camera-mode 1080p240 \
  --camera-frame-rate-fps 240 \
  --camera-shutter-mode fixed \
  --operator "operator name" \
  --annotator "annotator name" \
  --device-info latency-run/device-info.json \
  --host-artifact "host binary identity or hash" \
  --client-artifact "APK identity or hash" \
  --stimulus "visible Mac-side stimulus" \
  --start-event-definition "first camera frame where the stimulus is visible" \
  --end-event-definition "first camera frame where the result is visible" \
  --lighting "lighting conditions" \
  --mounting "camera and device mounting" \
  --max-frame-annotation-uncertainty-ms 4.2 \
  --gate-artifact latency-run/internet-public-route-record.txt \
  --gate-artifact-description "public TURN route, remote peer, ICE pair, and non-LAN topology proof" \
  --internet-route forced-public-turn \
  --turn-provider "provider" \
  --turn-region "region" \
  --turn-public-hostname "turn.example.net" \
  --turn-resolved-ip "$TURN_RESOLVED_IP" \
  --turn-tls turns \
  --turn-credential-source "authority-issued short-lived credential" \
  --remote-peer-operator "remote tester" \
  --remote-peer-network "remote carrier or ISP" \
  --remote-peer-public-ip-asn "AS number" \
  --remote-peer-location "city, country" \
  --local-candidate-type relay \
  --remote-candidate-type relay \
  --relay-protocol turn-tls \
  --host-network "host ISP" \
  --device-network "remote carrier or ISP" \
  --different-private-network \
  --notes "run-specific notes"
```

For a formal gate claim, validate the whole evidence directory with the stricter
latency provenance checker:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency_evidence \
  latency-run/manifest.json \
  --gate-profile internet-glass-to-glass-sub150 \
  --output latency-run/latency-evidence.json
```

For committed evidence directories, prefer the matching Make target so every
run writes the canonical report name in place:

```sh
make evidence-latency-gate \
  EVIDENCE_DIR=latency-run \
  LATENCY_GATE_PROFILE=usb-glass-to-glass-sub50
```

The manifest follows `tools/schemas/latency-evidence.schema.json` and must bind
the run ID, transport, profile, sample file, device identity, build identity,
annotation method, and the profile-specific retained artifact: USB connection
proof for `usb-glass-to-glass-sub50`, LAN network/stream preflight proof for
`lan-glass-to-glass-sub80`, public Internet route proof for
`internet-glass-to-glass-sub150`, or physical input actuation proof for
`input-p95-sub50`. External-camera packages also bind the raw camera recording
and camera mode; synchronized-clock input packages bind the clock sources,
skew, drift, timestamp methods, sub-5 ms total error budget, and a retained
`synchronization_record` artifact. The checker exits `0` only when the profile
verdict is `pass` and provenance is complete; missing raw video, missing
profile artifacts, mismatched metadata, or incomplete synchronization proof
stays `insufficient`. The step-by-step method is in
`docs/runbook/latency-measurement.md`.

Before spending device time on a full capture, record a fail-closed readiness
snapshot for the three README gate profiles:

```sh
make evidence-latency-preflight \
  EVIDENCE_DIR=.build/evidence/latency-preflight \
  LATENCY_DEVICE_INFO=.build/evidence/latency-preflight/device-info.json \
  LATENCY_PREFLIGHT_INPUT=.build/evidence/latency-preflight/preflight-input.json \
  LATENCY_REPOSITORY_REVISION="$(git rev-parse origin/main)"
```

Start from `tools/fixtures/latency/preflight-input.template.json` when creating
the input file. The target writes `latency-preflight.json` and
`latency-preflight-exit.txt`. Exit `2` means the run is blocked before a formal
gate attempt, which is an expected fail-closed outcome when external-camera or
synchronized-clock artifacts are missing.

For telemetry-stage diagnostics, prepare rows with `stage,latency_ms` and mark
the clock domain explicitly:

```sh
PYTHONPATH=tools python3 -m vibescreen_evidence.latency host-stages.csv \
  --kind telemetry-stage \
  --transport usb \
  --measurement-method host-telemetry \
  --output host-stage-summary.json
```

Use `--measurement-method client-telemetry` for Android decoder or render-stage
samples. The output has `status=informational` and
`gate.can_close_performance_gate=false`; keep it next to the camera/input
evidence to explain bottlenecks, not as a substitute for external measurement.
Synthetic CLI fixtures live in `tools/fixtures/latency/` and cover pass, fail,
insufficient, input, and telemetry-stage behavior. They are test data only, not
acceptance evidence.

## Troubleshooting

- `device ... not ready`: run `adb connect <serial>` and confirm the exact
  manufacturer/model/fingerprint before testing.
- Missing process metrics: install and start the package passed through
  `EVIDENCE_PACKAGE`; the run remains usable but is marked partial.
- Thermal entries vary by vendor. The collector archives every readable zone
  instead of assuming Xiaomi-specific names.
- A black Android `screencap` does not prove a black stream: hardware-decoded
  secure/overlay surfaces may be absent from screenshots. Use an external
  camera for visual and end-to-end latency evidence.
