# Getting started

The current runnable applications are presented to users as **Vibe Screen**. The
macOS SwiftPM product and packaged executable use that name as well. The internal
source-module name remains historical; compatibility identifiers also stay
unchanged so existing permissions and settings continue to work. These instructions
build from source; there is no notarized stable release yet.

## Prerequisites

### macOS host

- macOS 13 or newer;
- full Xcode 16 or newer, with its Swift 6 toolchain, for the complete
  Phase 3 macOS build/test workflow;
- Python 3 for local `.app` packaging;
- Android Platform Tools (`adb`) for USB mode.

macOS 13 or newer is a minimum source/runtime requirement, not a published
hardware compatibility matrix. Apple silicon is locally exercised; Intel Macs,
additional macOS builds, and built-in/external/multi-display/dummy/headless or
Screen Sharing display setups need exact-row evidence from the
[macOS Host compatibility gate](runbook/macos-host-compatibility.md) before they
are listed as supported.

Select full Xcode and verify it:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -version
swift --version
```

The MacHost package manifest remains readable by Swift 5.9, but its local
Protocol v1 dependency uses a Swift 6 package manifest. A Swift 5.9-only
toolchain therefore cannot resolve or build the current Phase 3 product
session. Command Line Tools with Swift 6 can run supported SwiftPM builds, but
XCTest and the complete verification workflow still require full Xcode.

### Android client

- JDK 17;
- Android SDK Platform 34 and Build Tools 34.0.0;
- an Android 8.0 / API 26 or newer device;
- developer options and USB debugging enabled.

```bash
sdkmanager "platforms;android-34" "build-tools;34.0.0" "platform-tools"
java -version
adb version
```

Protocol checks additionally use Go 1.25.12. `make protocol` downloads the
pinned Buf v1.72.0 module through Go on first use.

## Build from a clean checkout

```bash
make protocol

cd baseline/AndroidClient
./gradlew --no-daemon clean testDebugUnitTest lintDebug assembleDebug
cd ../..

make baseline-macos-build
make baseline-macos-test
make baseline-macos-self-test
make baseline-macos-app
```

Outputs:

- Android Debug APK:
  `baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk`
- pinned stable-identity macOS source build and SHA-256:
  `.build/release-artifacts/`

The Debug APK uses the local Android debug certificate and is not a public
release artifact. `make baseline-macos-app` resolves `Vibe Screen Dev` to the
pinned historical Host signing leaf
`9AAE572BF6D764E3436A6109197D345B5A87998C` by default so rebuilt local Host
bundles keep the same designated requirement for existing macOS TCC (Screen
Recording/Accessibility) grants. A Developer ID-signed and notarized macOS build
is also not provided yet.

Version tags create draft development-prerelease artifacts for maintainer
review. CI and release-preview workflows may pass `--sign-identity -` explicitly
for ad-hoc preview artifacts on machines without the pinned local identity; that
path changes the designated requirement and cannot reuse local Host TCC grants.
The draft workflow also adds an unsigned iOS Simulator-only build, aggregate
checksums, an SPDX SBOM, and third-party notices. See the
[release runbook](runbook/releasing.md); these drafts are not a stable
distribution channel.

## Install and run over USB

Replace the serial below with the exact value from `adb devices -l`.

```bash
export ANDROID_SERIAL="device-serial-or-host:port"
adb -s "$ANDROID_SERIAL" get-state
adb -s "$ANDROID_SERIAL" install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s "$ANDROID_SERIAL" reverse tcp:54321 tcp:54321
adb -s "$ANDROID_SERIAL" reverse --list
```

Install, preflight, and start the packaged host through the guarded entry
points. The preflight and readiness targets are read-only checks: they inspect
codesign/source provenance and existing TCC rows, but they do not request
Screen Recording, Accessibility, or Microphone permission and they do not open
System Settings. On a first-run machine they are expected to block until the
installed app has been authorized explicitly.

```bash
make baseline-macos-dev-install
make baseline-macos-host-preflight
make baseline-macos-launch
```

Do not launch `.build/release-artifacts/Vibe Screen.app` directly for device
evidence. The supported path installs and preflights the source-bound,
stable-signed bundle at `/Applications/Vibe Screen.app` before launch so stale
artifacts or drifted signing identities cannot silently reuse Host permissions.
macOS treats privacy grants as bound to the installed bundle identity, signing
requirement, and path, so authorize only `/Applications/Vibe Screen.app` with
`CFBundleIdentifier=dev.telemachus.display` and the pinned stable signing leaf.

On first authorization for a new machine or a missing TCC row:

1. use **System Settings → Privacy & Security** to add and grant
   `/Applications/Vibe Screen.app` for Screen Recording;
2. grant Accessibility to the same app bundle if touch control is required;
3. grant Microphone to the same app bundle only when testing Host microphone
   capture;
4. quit Vibe Screen after macOS records the grants;
5. rerun `make baseline-macos-host-preflight`, then use
   `make baseline-macos-launch` for the guarded launch path;
6. select USB mode and start streaming.

Then launch Android with automatic USB connection:

```bash
adb -s "$ANDROID_SERIAL" shell am start -S -W \
  -n dev.telemachus.display/.MainActivity \
  --ez auto_connect true
```

The client connects to `127.0.0.1:54321`; ADB reverse carries that socket to
the host. A successful session shows an active stream, rising frame counters,
and touch changes the Mac pointer position.

If the run is intended to add a macOS Host compatibility row, record the Host
identity, macOS build, display topology, Host build/signing/TCC state, capture
backend, VideoToolbox path, Android counterpart, logs, and screenshots before
summarizing the row with `make macos-hardware-compatibility-gate`.

## Trusted LAN mode

LAN support is experimental. Pair with the QR code shown by the Mac host while
both devices are on the same trusted private network. Android camera permission
is used only to scan a new QR code. Existing USB use does not require it.

Current macOS and Android peers require the QR/token admission gate and then
protect the admitted LAN session with per-session AES-256-GCM application
records. Explicit legacy fallback remains plaintext for old peers only and must
not be described as encrypted. Do not use LAN mode on public or hostile
networks.

## Release signing

Android release builds require `VIBE_SCREEN_VERSION` and the four
`VIBE_SCREEN_KEYSTORE_*` / `VIBE_SCREEN_KEY_*` signing variables defined in
`baseline/AndroidClient/app/build.gradle.kts`. Never commit a keystore or its
password. Public release signing and macOS notarization are not performed by
the preview workflow. The workflow generates unsigned SHA-256 checksum metadata
for its own draft artifacts; production signing and notarization remain
separate maintainer gates.
