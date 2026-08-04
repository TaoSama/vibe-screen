# Vibe Screen for iPhone and iPad

This directory contains the native SwiftUI iOS client and its independently
testable Protocol v1, session, transport, and VideoToolbox modules.

The client is an early developer release. Its core modules build and self-test
on macOS, and the unsigned application has built successfully with the iOS
Simulator SDK in CI. Simulator test execution, signing, installation, and
iPhone/iPad hardware decode are separate gates; do not treat the SDK build or
Android device record as that evidence. The Mac host now supports the Android
baseline's legacy-to-v1 upgrade and Protocol v1 session, but this iOS client
does not yet implement that upgrade or compose its session with the baseline
host, so the two are not currently interoperable.

## Requirements

- macOS with full Xcode 16 or newer and an iOS 17 or newer SDK;
- iPhone or iPad running iOS/iPadOS 17 or newer for device installation;
- a Mac host and client adapter implementing the same Protocol v1 upgrade and
  trusted-LAN session composition described in the Phase 5 technical design;
- an Apple development team and a unique bundle identifier for device signing.

The package pins `swift-protobuf` to immutable revision
`c6fe6442e6a64250495669325044052e113e990c`. The first build therefore needs
network access unless the Swift Package cache is already populated.

## Build and test

Core modules and the deterministic self-test do not need an iOS SDK:

```bash
swift package --package-path apps/ios resolve
swift build --package-path apps/ios
swift run --package-path apps/ios vibescreen-ios-selftest
```

The self-test decodes the shared
`contracts/fixtures/client-hello-v1.hex` fixture also emitted by the HarmonyOS
codec, in addition to its protocol/session/media checks.

After editing Protocol v1 schemas, regenerate the checked Swift bindings:

```bash
apps/ios/Scripts/generate-protocol.sh
git diff -- apps/ios/Sources/VibeScreenProtocol
```

With full Xcode selected, run the XCTest UI smoke test on an available iPhone
simulator and create an unsigned Release archive:

```bash
xcodebuild -version
xcodebuild -showsdks
apps/ios/Scripts/build_ios.py
```

Use `--action simulator-build`, `--action simulator-test`, or
`--action archive` to run one gate. The archive is written to
`apps/ios/.build/xcode/VibeScreen.xcarchive` and is intentionally unsigned; it
is build evidence, not an installable signed release.

For a physical device, open `apps/ios/VibeScreen.xcodeproj`, select the
`VibeScreen` target, choose your development team, replace
`dev.vibescreen.ios` with a unique bundle identifier, select the attached
device, and Run. The app supports both device families from one target.

## Connect and use

1. Put the iPhone/iPad and Mac on a trusted local network.
2. Start a Protocol v1 host and note its IP address and TCP port. The default
   client field is port `58008`; change it to the host's configured port.
3. Enter the host address and tap **连接**.
4. Accept the iOS Local Network permission prompt.
5. The client negotiates H.264/HEVC and additive capabilities, asks for
   available displays, and attaches to as many as the negotiated limit allows.
6. Use the display selector to change the rendered/input target. Dragging sends
   native normalized touch events targeted at that stream.
7. Tap **断开** before changing hosts.

The current developer transport is plaintext trusted-LAN TCP. Do not expose it
to the Internet or an untrusted network.

## Upgrade, reset, and uninstall

After updating source, resolve the pinned package again and perform a clean
build:

```bash
swift package --package-path apps/ios resolve
xcodebuild -project apps/ios/VibeScreen.xcodeproj -scheme VibeScreen clean
```

Install the new build over the old one to preserve the saved host and port.
Delete the app from the device to remove those preferences. Pairing keys are
not yet stored by this client, so there is currently no key migration step.

## Permissions and managed configuration

- **Local Network** is required for direct host discovery/connection. Denying
  it prevents LAN use; re-enable it in iOS Settings > Privacy & Security >
  Local Network.
- Screen capture and Accessibility permissions belong to the macOS host, not
  the iOS client.
- **Clipboard** is never polled. Sending reads `UIPasteboard` only after the
  user taps send; received content is staged and written only after approval.
- **Files** use the system document picker and security-scoped URL after user
  selection. Received chunks remain hidden until SHA-256 verification passes.
- **Audio** uses playback-only `AVAudioSession`/`AVAudioEngine`; microphone
  permission is not requested.
- **Wake-on-LAN** requires a previously authorized device identity, an explicit
  button press, and policy permission. A Magic Packet is not authentication.
- Managed App Configuration is read from
  `com.apple.configuration.managed`. Supported deny-wins keys are
  `ClipboardAllowed`, `FileTransferAllowed`, `AudioAllowed`, `WakeAllowed`,
  `CustomGesturesAllowed`, `MaximumFileBytes`, and `AllowedHosts`. Invalid
  types fail closed.

## Advanced feature use

- Open **功能** while streaming to exchange clipboard content, select a file,
  approve/reject incoming files, export verified files, configure gestures, or
  request Wake-on-LAN.
- PCM S16LE audio uses the independent audio channel, current session/config
  epochs, and bounded jitter/playback queues.
- File chunks use the bulk channel with sequential offsets, negotiated chunk
  size, per-chunk and final SHA-256, limits, cancellation, and cleanup.
- The renderer does not advertise HDR output. HDR10/PQ/Main10 requests are
  explicitly rejected with an 8-bit BT.709 SDR fallback at a newer
  `config_epoch`; color is never changed silently.
- Gesture definitions remain local. Only action IDs from a negotiated host
  catalog may be invoked.

## Troubleshooting

- **Connection refused:** confirm the Protocol v1 host is listening on the
  entered address/port. Port `54321` supports the Android baseline's explicit
  legacy-to-v1 upgrade, but the current iOS transport does not yet perform that
  upgrade and must not be pointed directly at this port.
- **No Local Network prompt:** check the app's permission in Settings, then
  delete/reinstall if the development bundle identifier changed.
- **Connected but no picture:** verify the host accepted `StartDisplayRequest`
  and is sending video-channel frames with the current `session_epoch`.
- **Decode errors:** force the host to H.264 SDR and send SPS/PPS on the next
  keyframe. HEVC requires VPS/SPS/PPS. Codec fallback must be explicit.
- **Swift package resolution fails:** verify network access, then run
  `swift package --package-path apps/ios reset` and resolve again.
- **`xcodebuild` says Xcode is required:** install full Xcode and select its
  developer directory; Command Line Tools alone have no iOS SDK.
- **No advanced controls:** inspect the negotiated capability intersection;
  unsupported or policy-denied features intentionally stay off.
- **Audio silent:** only PCM S16LE is accepted; verify sample rate, channels,
  frame count, session epoch, and config epoch.
- **File rejected:** verify basename safety, declared size, negotiated chunk
  limit, sequential offsets, and chunk/final SHA-256.

## Known limits

- unsigned iOS Simulator SDK compilation is recorded in CI; simulator XCTest,
  signing, installation, and device execution remain separate evidence gates;
- no automatic reconnect loop in the app UI yet, although epoch filtering and
  bounded reconnect backoff are implemented and self-tested;
- one host connection can route up to four negotiated display streams; actual
  multi-client admission and virtual-display allocation remain host work;
- touch only; keyboard/pointer UI is negotiated but not exposed yet;
- PCM S16LE playback, explicit text clipboard, bounded file transfer, SDR
  fallback, gestures, WOL, and managed restrictions are implemented, but have
  no iOS-device evidence in this environment;
- no AAC/Opus, background audio, zero-copy HDR/EDR output, arbitrary clipboard
  MIME UI, Internet transport, or production E2EE;
- frame rendering currently creates a Core Image display image per decoded
  frame; Metal zero-copy rendering remains a measured optimization gate.

## Required host integration

The Mac host has a Protocol v1 adapter for the Android baseline session. iOS
still needs the matching upgrade and baseline-session composition; advanced
host integrations must then preserve these client semantics:

- Hello plus explicit negotiated capabilities/resource limits;
- independent per-client epochs and unique per-session display stream IDs;
- multi-display allocation/input routing and bounded PCM audio capture;
- clipboard control, bulk file chunks, limits, cancellation, and digests;
- color-aware reject/retry using a newer config epoch;
- finite host action catalogs, authenticated/replay-safe wake helpers, and
  deny-wins managed policy;
- separate control/video/audio/bulk keys, sequences, and replay windows before
  enabling advanced channels on Internet transport.

See the [Phase 5 verification record](../../docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md)
and [dependency provenance](THIRD_PARTY.md) for exact evidence and licensing.
