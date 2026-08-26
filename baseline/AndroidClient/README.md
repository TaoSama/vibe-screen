# Vibe Screen Android client

The Android client turns a trusted Android phone or tablet into a low-latency
display and touch terminal for the macOS host. The imported package name is
currently `dev.telemachus.display`; changing it is a release migration because
Android treats a new application ID as a different app.

## Supported now

- USB streaming through ADB reverse and authenticated TCP streaming on a
  trusted LAN.
- Hardware H.264 and HEVC decoding with explicit codec negotiation, sync-frame
  recovery, stale-frame dropping, and bounded buffers.
- Full-screen fit/fill rendering, real client-local Surface rotation,
  rotation/crop/letterbox-aware touch mapping, two-finger gestures, connection
  telemetry, and saved UI preferences.
- Protocol v1 main-session negotiation, display/video configuration, logical
  control/video channels, host-issued session epochs, touch, heartbeat, and
  actionable protocol errors. Older hosts remain available through an explicit
  legacy fallback.
- QR pairing for LAN, encrypted-at-rest pairing credentials, actionable camera
  permission states, and automatic USB/LAN reconnection.
- Adaptive layouts tested on phone and wide tablet-sized screens. The connected
  screen stays awake and is protected from Android screenshots. Backgrounding
  pauses new retry attempts and input; returning to the foreground resumes
  retry or requests a fresh keyframe without discarding a live session.
- Input writes use a bounded single-writer scheduler: recovery controls are
  prioritized, pointer moves coalesce to the newest pending position, and
  down/up/cancel boundaries retain FIFO order.
- Touch tap, long-press right click, long-press drag, two-finger scroll/pinch,
  external mouse wheel, and external secondary-button events use the existing
  touch path. Secondary mouse clicks are adapted to the host's long-press
  gesture rather than sent as native pointer-button packets.

The client captures common physical-keyboard keys and shortcuts into
protocol-neutral USB HID usages. Protocol v1 capability-gates keyboard, native
pointer, and stylus input; stylus samples preserve Android historical motion,
normalized pressure, signed two-axis tilt, pen/eraser tool kind, two barrel
buttons, and hover/proximity state over USB, LAN, and Internet. Extended stylus
fields use an independent capability gate, while legacy or unnegotiated peers
receive the existing pen-contact/touch behavior instead of unknown protocol
bytes. The explicit legacy fallback is intentionally touch-compatible only:
physical keyboard input shows the compatibility message without sending bytes,
and native pointer move/click are rejected unless Protocol v1 has negotiated the
pointer capability and installed a session input sink. Wheel and secondary
mouse button input continue through the existing touch adapters for old peers.
Physical-stylus drawing-app confirmation and other peripherals remain release
gates.

Internet mode is exposed as
a development-preview UI: it scans the one-time pairing offer, completes the
strict request/acceptance exchange, imports a short-lived session profile,
selects direct or forced TURN, and drives the Protocol v1 video/touch product
session. The request/acceptance and session profile are intentionally copied or
scanned in this local integration surface; no production account/session
authority is bundled. The prior curated M144↔M150/UI pass remains withdrawn.
A fresh reachable-source run now records the real UI plus direct and forced
local-coturn M144↔M150 product sessions on Nubia P0110 with synthetic Protocol v1
media; see the Phase 3 evidence README for its exact boundary.
Public Internet, real ScreenCaptureKit output, rotation, handoff/reconnect, cross-service
revocation and soak remain gates, so this is not yet a shipped Internet feature.

## Requirements

- JDK 17 and Android SDK Platform/Build Tools 34.
- An Android 8.0 (API 26) or newer device with USB debugging enabled.
- The matching macOS host. USB uses port `54321` by default.

## Build and test

From this directory:

```bash
./gradlew clean :transport:check testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest
./gradlew :transport:check --configuration-cache --configuration-cache-problems=fail
```

The second command is the transport boundary's configuration-cache gate. Its
live dependency-graph tasks explicitly opt out, so Gradle must run them and
report that the cache entry was discarded instead of reusing a stale verdict.

The debug APK is written to
`app/build/outputs/apk/debug/app-debug.apk`. The Gradle wrapper pins Gradle 8.6;
all Maven repositories and dependency versions are declared in the checked-in
build scripts.

`InternetMainActivityAcceptanceInstrumentedTest` drives the real Internet tab,
route toggle, pairing, strict lease import, local revoke, and re-pair UI against
AndroidKeyStore-backed storage. Its host authority and credentials are generated
in memory, sensitive dialogs must retain `FLAG_SECURE`, and its output is limited
to a fixed boolean marker. A passing device run proves the local credential UI only; the
separate external-host instrumentation run is required for WebRTC, Protocol v1,
application AEAD, media, and touch evidence.

## Install and run over USB

```bash
adb devices -l
adb reverse tcp:54321 tcp:54321
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n dev.telemachus.display/.MainActivity --ez auto_connect true
```

Open the macOS host before starting the client. The connection page checks USB
debugging, the data cable, the reverse mapping, and host reachability. A normal
USB reconnect is automatic and keeps retry delays bounded.

## Connect on a trusted LAN

1. Put the Mac and Android device on the same private Wi-Fi network.
2. Open the Wireless tab in both apps.
3. Scan the one-time QR code displayed by the Mac and accept the warning.
4. On a network handoff or brief host interruption, leave the client open; it
   retries automatically. Use **Forget this Mac** to remove the stored token.

Current Mac and Android peers protect the admitted LAN session with
per-session AES-256-GCM application records. Explicit legacy fallback remains
plaintext and must be reported separately if it is ever used. Never use this
mode on public, guest, or otherwise untrusted Wi-Fi.

## Permissions and device behavior

- **Camera** is requested only when scanning a LAN pairing QR code. USB works
  without it. If permission is permanently denied, the UI links to Android app
  settings and re-evaluates the permission when the user returns.
- **Network access/state** is used for the stream and for binding LAN sockets to
  the active Wi-Fi network.
- Pairing tokens are encrypted with a key held by Android Keystore and are not
  included in Android backups.
- While streaming, Android's keep-screen-on and secure-window flags are active.
  Keep-screen-on and retries pause in the background; screenshot protection
  remains until disconnect.

## Phase 3 secure-session composition

Production Internet code must create sessions through
`AndroidStoredInternetSessionFactory`. It stores the shared and bootstrap
pairing secrets as one AES-256-GCM record protected by a non-exportable
AndroidKeyStore key, reserves the authority-agreed session epoch above the
durable high-water mark, and injects the resulting cipher into
`AndroidWebRtcPeerEngine`. The imported signaling token and TURN credentials are
also AndroidKeyStore-wrapped; only non-secret routing metadata is stored in
preferences. Missing/corrupt state, an old epoch, relay-only without TURN, or a
null/test cipher fails closed.

`MainActivity` connects this protected transport to Protocol v1 negotiation,
MediaCodec configuration and frames, touch input, keyframe requests, route/state
display, disconnect, local revoke, and fresh-session errors. A network change
closes the old session and requires an imported profile with a larger epoch; it
does not reuse the old signaling session or downgrade to plaintext. Automatic
authority issuance, public TURN/NAT, signed cross-service revocation propagation,
real screen capture, handoff and soak are not claimed. The local
direct/forced-coturn device result and its limits are recorded in the Phase 3
test plan.

The imported lease is strict JSON with exactly these fields. The paired Mac
signs the canonical lease transcript, including the signaling token and TURN
credentials, before the client persists any part of it:

```text
version, pairing_id, pinned_host_id, signaling_url, signaling_session_id,
session_epoch, identity_epoch, transcript_context, protocol_session_id,
signaling_token, ice_servers[{urls, username, credential}],
allow_insecure_for_testing, lease_host_key_id, lease_signature
```

Unknown/missing fields fail closed, a replacement lease must use a strictly
larger `session_epoch`, and production signaling requires HTTPS. Plain HTTP is
accepted only for loopback in a debuggable build. Treat the complete imported
JSON as secret because it contains role/TURN credentials. Pairing secrets come
only from the completed signed pairing and are never accepted in a lease. Do not
save the JSON in logs, screenshots, shell history, or tracked files.

## Upgrade and release packaging

Debug builds can be upgraded in place with `adb install -r`. A public release
must keep the same application ID and signing key. Build a versioned signed APK
or App Bundle with:

```bash
export VIBE_SCREEN_VERSION=0.1.0
export VIBE_SCREEN_KEYSTORE_FILE=/absolute/path/to/release.jks
export VIBE_SCREEN_KEYSTORE_PASSWORD='...'
export VIBE_SCREEN_KEY_ALIAS='...'
export VIBE_SCREEN_KEY_PASSWORD='...'
./gradlew clean :transport:check testDebugUnitTest lintDebug assembleRelease bundleRelease
```

Signing secrets must remain outside the repository. Release tasks fail closed
when any signing variable is absent. Every APK packages the upstream MIT
license, NOTICE, Apache-2.0 text, and a generated runtime dependency list; users
can read the notice from **Open-source licenses** on the connection page.

## Troubleshooting

- **Waiting for Mac:** confirm `adb reverse --list` contains
  `tcp:54321 tcp:54321`, then verify the host listens on the same port.
- **Black stream:** check the on-device diagnostic log with
  `adb shell run-as dev.telemachus.display tail -200 files/diag.log`. A decoder
  selection and `First output frame` entry prove the media path; request a new
  host keyframe or reconnect if the client remains unsynchronized.
- **LAN cannot connect:** verify both devices use the same private Wi-Fi, the IP
  in the QR is current, and the macOS firewall permits the configured port.
- **Pairing rejected:** use **Forget this Mac**, reset the host token, and scan a
  fresh QR code.
- **Camera blocked:** Android Settings → Apps → Vibe Screen → Permissions →
  Camera, or continue with USB.
- **Codec failure:** capture `adb shell dumpsys media.codec` and the diagnostic
  log. Runtime HEVC failure is recorded so the next negotiated connection can
  explicitly choose H.264.

## Verification status and known limits

For the Phase 3 development-preview composition, the local JVM suite, lint,
debug app/test assembly, instrumentation compilation and release-dependency
audit pass. The merged release manifest disables cleartext traffic. On
2026-08-05, clean reachable commit
`597518f948075e396352bc353afcec01a30303f3` installed those controlled artifacts
on `Nubia P0110 / pacific / Android 16`. The real credential UI and Android
M144/macOS M150 adapters passed direct and forced local coturn with Protocol v1,
AES-256-GCM control/media, synthetic video config/keyframe/delta and authenticated
touch. Local revoke/re-pair used production listeners and AndroidKeyStore-backed
state. The evidence contains paired before/after device-lock gates for every ADB
subprocess and no private endpoint, hardware serial, or credential values.

That device run does not claim ScreenCaptureKit, real display content, visible
Mac input effects, Android rotation, disconnect/reconnect or handoff, public
Internet, cross-service revoke, packet capture, latency, or soak.

On 2026-08-04, the controlled remote ADB endpoint (redacted as
`$ADB_ENDPOINT`) identified itself as a nubia P0110 (`pacific`) running
Android 16/API 36, not a Xiaomi 13 (2211133C). It installed and launched the debug APK and
decoded a real 1512×982 HEVC stream with Qualcomm's hardware decoder. This is
useful device evidence but does not satisfy Xiaomi 13 (2211133C) acceptance.

On 2026-08-05, the same Nubia device installed the Phase 1 Android client and
decoded a repository-generated 2000×1124 HEVC stream with Qualcomm hardware.
Fit geometry, actionable pre-display failure, Camera denial/recovery,
foreground resume, HID compatibility gating, touch packets, and a synthetic
cold reconnect were exercised. The Mac remained locked, so this run does not
prove visible Mac input results, real display selection/rotation, physical
mouse or keyboard behavior, or ScreenCaptureKit end-to-end recovery. See the
[Phase 1 verification record](../../docs/changes/2026-08-05-phase-1-android-client/TEST.md).

Subsequent review fixes for true 90°/270° rendering, inverse input mapping,
session-generation isolation, bounded outbound input, typed terminal errors,
and Camera settings-return recovery are covered by JVM/lint/build gates only.
That post-device build has not been installed or exercised with a real Mac or
physical peripherals.

The following remain separate release gates: a physical 8–9 inch tablet
matrix, unlocked-Mac Phase 1 interaction acceptance, controlled stability
runs, external-camera glass-to-glass latency, physical keyboard/native-mouse
and stylus interoperability, physical eraser/barrel/hover confirmation, and
real-device trusted-LAN stream/reconnect evidence for the current encrypted
application-record path.

## Source and licenses

The Android source was imported and is modified from Telemachus commit
`a5dd1298870846d749175812f936ceebfd8b6b69` (MIT), itself a derivative of
SideScreen commit `a651a81b7d6468c7a564c038551872d3346a2d55` (MIT). The copied
scope is the initial Android client implementation, including transport,
MediaCodec, touch, UI, and tests. See
`../../docs/changes/2026-08-04-phase-0-baseline/UPSTREAM.md` and the preserved
`../LICENSE` / `../NOTICE`. No GPL or AGPL code is included in this client.
