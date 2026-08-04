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
- Full-screen aspect-fit rendering, letterbox-aware touch mapping, rotation,
  two-finger gestures, connection telemetry, and saved UI preferences.
- QR pairing for LAN, encrypted-at-rest pairing credentials, actionable camera
  permission states, and automatic USB/LAN reconnection.
- Adaptive layouts tested on phone and wide tablet-sized screens. The connected
  screen stays awake and is protected from Android screenshots.

Keyboard forwarding, native mouse/stylus fields, client-side display selection,
and the Internet transport are not exposed in the current product UI. The
Phase 3 source tree does contain a production libwebrtc adapter, REST signaling
client, Protocol v1 record encryption, and an AndroidKeyStore-backed factory
that atomically loads paired secrets into a protected Internet session. These
components still require the matching versioned host protocol and coordinated
device acceptance before they are presented as shipped behavior. The
legacy host accepts touch packets only; the client must not claim these controls
until both ends negotiate them.

## Requirements

- JDK 17 and Android SDK Platform/Build Tools 34.
- An Android 8.0 (API 26) or newer device with USB debugging enabled.
- The matching macOS host. USB uses port `54321` by default.

## Build and test

From this directory:

```bash
./gradlew clean testDebugUnitTest lintDebug assembleDebug
```

The debug APK is written to
`app/build/outputs/apk/debug/app-debug.apk`. The Gradle wrapper pins Gradle 8.6;
all Maven repositories and dependency versions are declared in the checked-in
build scripts.

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

LAN authentication does not encrypt legacy video or input traffic. Never use
this mode on public, guest, or otherwise untrusted Wi-Fi.

## Permissions and device behavior

- **Camera** is requested only when scanning a LAN pairing QR code. USB works
  without it. If permission is permanently denied, the UI links to Android app
  settings.
- **Network access/state** is used for the stream and for binding LAN sockets to
  the active Wi-Fi network.
- Pairing tokens are encrypted with a key held by Android Keystore and are not
  included in Android backups.
- While streaming, Android's keep-screen-on and secure-window flags are active.
  They are removed after disconnect.

## Phase 3 secure-session composition

Production Internet code must create sessions through
`AndroidStoredInternetSessionFactory`. It stores the shared and bootstrap
pairing secrets as one AES-256-GCM record protected by a non-exportable
AndroidKeyStore key, allocates a durable session epoch and nonce sequence, and
injects the resulting cipher into `AndroidWebRtcPeerEngine`. Missing or corrupt
pairing state fails closed; callers must not construct a production
`PeerConfiguration` with a null or test cipher.

The adapter and its instrumentation APK build locally, but the coordinated
device freeze prevented running that instrumentation in this change. Internet
mode remains absent from `MainActivity`, and public TURN/NAT interoperability is
not claimed.

## Upgrade and release packaging

Debug builds can be upgraded in place with `adb install -r`. A public release
must keep the same application ID and signing key. Build a versioned signed APK
or App Bundle with:

```bash
export TELEMACHUS_VERSION=0.1.0
export TELEMACHUS_KEYSTORE_FILE=/absolute/path/to/release.jks
export TELEMACHUS_KEYSTORE_PASSWORD='...'
export TELEMACHUS_KEY_ALIAS='...'
export TELEMACHUS_KEY_PASSWORD='...'
./gradlew clean testDebugUnitTest lintDebug assembleRelease bundleRelease
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

On 2026-08-04, the configured remote ADB endpoint
`100.72.246.116:5555` identified itself as a nubia P0110 (`pacific`) running
Android 16/API 36, not a Xiaomi 12. It installed and launched the debug APK and
decoded a real 1512×982 HEVC stream with Qualcomm's hardware decoder. This is
useful device evidence but does not satisfy Xiaomi 12 acceptance.

The following remain separate release gates: Xiaomi 12 coverage, a physical
8–9 inch tablet matrix, 30-minute and eight-hour controlled soak runs,
external-camera glass-to-glass latency, keyboard/mouse/stylus protocol
interoperability, and production encryption for LAN traffic.

## Source and licenses

The Android source was imported and is modified from Telemachus commit
`a5dd1298870846d749175812f936ceebfd8b6b69` (MIT), itself a derivative of
SideScreen commit `a651a81b7d6468c7a564c038551872d3346a2d55` (MIT). The copied
scope is the initial Android client implementation, including transport,
MediaCodec, touch, UI, and tests. See
`../../docs/changes/2026-08-04-phase-0-baseline/UPSTREAM.md` and the preserved
`../LICENSE` / `../NOTICE`. No GPL or AGPL code is included in this client.
