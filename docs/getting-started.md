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
- ad-hoc signed macOS source build and SHA-256:
  `.build/release-artifacts/`

The Debug APK uses the local Android debug certificate and is not a public
release artifact. A Developer ID-signed and notarized macOS build is also not
provided yet.

Version tags create draft development-prerelease artifacts for maintainer
review. They retain these same signing limitations and add an unsigned iOS
Simulator-only build, aggregate checksums, an SPDX SBOM, and third-party
notices. See the [release runbook](runbook/releasing.md); these drafts are not a
stable distribution channel.

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

Start the packaged host:

```bash
open ".build/release-artifacts/Vibe Screen.app"
```

On first launch:

1. grant Screen Recording in **System Settings → Privacy & Security**;
2. grant Accessibility if touch control is required;
3. restart the host after macOS requests it;
4. select USB mode and start streaming.

Then launch Android with automatic USB connection:

```bash
adb -s "$ANDROID_SERIAL" shell am start -S -W \
  -n dev.telemachus.display/.MainActivity \
  --ez auto_connect true
```

The client connects to `127.0.0.1:54321`; ADB reverse carries that socket to
the host. A successful session shows an active stream, rising frame counters,
and touch changes the Mac pointer position.

## Trusted LAN mode

LAN support is experimental. Pair with the QR code shown by the Mac host while
both devices are on the same trusted private network. Android camera permission
is used only to scan a new QR code. Existing USB use does not require it.

LAN currently uses authenticated but unencrypted TCP. Screen content and input
may be observable on the network. Do not use it on public or hostile networks.

## Release signing

Android release builds require `VIBE_SCREEN_VERSION` and the four
`VIBE_SCREEN_KEYSTORE_*` / `VIBE_SCREEN_KEY_*` signing variables defined in
`baseline/AndroidClient/app/build.gradle.kts`. Never commit a keystore or its
password. Public release signing and macOS notarization are not performed by
the preview workflow. The workflow generates unsigned SHA-256 checksum metadata
for its own draft artifacts; production signing and notarization remain
separate maintainer gates.
