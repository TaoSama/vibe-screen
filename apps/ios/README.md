# Vibe Screen for iPhone and iPad

This directory contains the native SwiftUI iOS client and its independently
testable Protocol v1, session, transport, and VideoToolbox modules.

The client is an early developer release. Its core modules build and self-test
on macOS; the iPhone Simulator UI smoke and unsigned iPhoneOS archive gates
pass in CI. Signing, installation, and iPhone/iPad hardware decode remain
separate gates; do not treat Simulator or Android records as that evidence.
The trusted-LAN Core client now uses the secure compatibility path by default:
it connects to the baseline MacHost on TCP port `54321`, completes authenticated
`SSWA`/`SSWR` admission, negotiates `VSLS`/`VSLR` AES-256-GCM application
records, sends the `0D` legacy-to-v1 upgrade inside the encrypted record stream,
and then runs its Protocol v1 main session. The old plaintext path is still
available only through an explicit legacy fallback switch and is reported as
plaintext. The real two-process loopback covers the secure Core boundary; it is
not iOS-device, UI, hardware VideoToolbox, real-network LAN, or advanced-host
evidence.

## Requirements

- macOS with full Xcode 16 or newer and an iOS 17 or newer SDK;
- iPhone or iPad running iOS/iPadOS 17 or newer for device installation;
- the baseline MacHost on TCP port `54321`, or another host implementing the
  trusted-LAN admission and Protocol v1 session described in the Phase 5
  technical design;
- an Apple development team and a unique bundle identifier for device signing.

The package requires exact `swift-protobuf` version `1.32.0`, which Swift
Package Manager resolves to immutable revision
`c6fe6442e6a64250495669325044052e113e990c` in `Package.resolved`. The first
build therefore needs network access unless the Swift Package cache is already
populated. The full Apache-2.0 license with runtime-library exception is retained at
`ThirdPartyLicenses/SwiftProtobuf-LICENSE.txt` and included in the application
Resources build phase.

## Build and test

Core modules and the deterministic self-test do not need an iOS SDK:

```bash
swift package --package-path apps/ios resolve
swift build --package-path apps/ios --configuration release
swift test --package-path apps/ios --configuration release
apps/ios/.build/release/vibescreen-ios-selftest
```

Before reporting current-base iOS acceptance readiness, generate the aggregate
fail-closed summary from the repository root:

```bash
make ios-current-base-gate EVIDENCE_DIR=.build/evidence/ios-current-base
```

Without full Xcode, signing, and real iPhone plus iPad evidence, this command is
expected to exit nonzero with `verdict=blocked`. That output is readiness
evidence only and does not claim device acceptance.

The self-test decodes the shared
`contracts/fixtures/client-hello-v1.hex` fixture also emitted by the HarmonyOS
codec, in addition to its protocol/session/media checks.

Run the real release-build, two-process iOS Core to baseline MacHost loopback:

```bash
apps/ios/Scripts/run_machost_loopback.py
```

This starts MacHost on an OS-assigned loopback test port with secure records
required by default and checks authenticated `SSWA`/`SSWR` admission, the
`VSLS`/`VSLR` record negotiation, the encrypted `0D`/`0D01` upgrade exchange,
Hello and negotiated capabilities, display list/start, video-config
acknowledgement, video media framing, ping/pong, display/stream-targeted touch,
invalid-target protocol error, and disconnect. Add `--legacy-plaintext` only to
exercise the explicitly reported old-peer plaintext fallback. The gate passes
the bound port through a strictly validated test-only environment variable;
production trusted-LAN connections still default to `54321`. Use `--skip-build`
only after both release products have already been built.

All outbound main-session control uses one session-owner-scoped FIFO writer;
message ID allocation, envelope encoding, and the TCP send therefore share one
serialization boundary. Replacing a connection invalidates its pending queue,
transport callbacks, heartbeat state, media gate, and decoder owners. Video is
delivered to VideoToolbox only after the matching positive `VideoConfigResult`
send completes. Before changing stream state, configs must carry a known codec,
an encoded size of `16...8192` per dimension, `1...240` FPS, nonzero bitrate,
rotation `0/90/180/270`, known color enums, and a matching local decode
capability. Each accepted config epoch starts a fresh frame-ID sequence; media
must then match session, stream, config epoch, codec, one-of-one fragment shape,
and a strictly increasing nonzero frame ID. Three expired Ping
deadlines without a matching Pong terminate the session.
Only transient transport send/connect failures and heartbeat timeouts enter the
automatic reconnect loop. The loop is generation-scoped, stops after five
attempts with delays capped at three seconds, and does not retry protocol,
authentication, or validation failures.

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
2. Start the baseline MacHost, open its Wireless pairing view, and obtain the
   `telemachus://` link for TCP port `54321`.
3. Paste that link into the iOS client and tap **连接**. The link contains a
   32-byte bearer token: paste it for each connection and do not store or share
   it.
4. Accept the iOS Local Network permission prompt.
5. The client negotiates H.264/HEVC and additive capabilities, asks for
   available displays, and attaches to as many as the negotiated limit allows.
6. Use the display selector to change the rendered/input target. Dragging sends
   native normalized touch events targeted at that stream. The keyboard button
   focuses hardware-key capture, and supported pointing devices send hover
   movement while they remain over the stream.
7. Tap **断开** before changing hosts.

The iOS developer transport requires authenticated trusted-LAN TCP and secure
records by default. It never silently downgrades to plaintext; use the
test-only `--legacy-plaintext` loopback flag or the explicit
`trustedLANLegacyPlaintext` startup mode only when validating old-peer
compatibility, and report that path separately. Do not expose either path to the
Internet or an untrusted network.

## Upgrade, reset, and uninstall

After updating source, resolve the pinned package again and perform a clean
build:

```bash
swift package --package-path apps/ios resolve
xcodebuild -project apps/ios/VibeScreen.xcodeproj -scheme VibeScreen clean
```

Install the new build over the old one. The trusted-LAN pairing URL and bearer
token are intentionally not persisted; paste a current link again for every
connection. Pairing keys are not yet stored by this client, so there is
currently no key migration step.

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
  `CustomGesturesAllowed`, `HostActionsAllowed`, `MaximumFileBytes`, and
  `AllowedHosts`. Invalid types fail closed.

## Advanced feature use

- Open **功能** while streaming to exchange clipboard content, select a file,
  approve/reject incoming files, export verified files, configure gestures, or
  request Wake-on-LAN.
- PCM S16LE audio uses the independent audio channel, current session/config
  epochs, and bounded jitter/playback queues.
- File chunks use the bulk channel with sequential offsets, negotiated chunk
  size, per-chunk and final SHA-256, limits, cancellation, and cleanup.
  These are iOS trusted-LAN/client-core semantics; they do not prove
  Mac/Android Internet product-session audio/bulk end-to-end behavior.
- The renderer does not advertise HDR output. HDR10/PQ/Main10 requests are
  explicitly rejected with an 8-bit BT.709 SDR fallback at a newer
  `config_epoch`; color is never changed silently. Use `make ios-hdr-edr-gate`
  with retained physical-device HDR/EDR observations before reporting any future
  iOS HDR output pass.
- Gesture definitions remain local. Only action IDs from a negotiated host
  catalog may be invoked.

## Troubleshooting

- **Connection refused:** confirm the baseline MacHost is listening on TCP
  `54321`, paste a current pairing link again, and confirm the iPhone/iPad can
  reach the Mac over the trusted LAN.
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

- iPhone Simulator UI smoke and an unsigned iPhoneOS archive pass in CI;
  signing, installation, and device execution remain separate evidence gates;
- automatic reconnect is limited to transient transport/heartbeat failures and
  stops after five attempts; protocol, authentication, and validation failures
  remain terminal;
- one host connection can route up to four negotiated display streams; actual
  multi-client admission and virtual-display allocation remain host work;
- touch, hardware-keyboard capture, and hover-pointer input are exposed in the
  app, but have no signed iPhone/iPad or physical-accessory evidence yet;
- PCM S16LE playback, explicit text clipboard, bounded file transfer, SDR
  fallback, gestures, WOL, and managed restrictions are implemented, but have
  no iOS-device evidence in this environment;
- no AAC/Opus, background audio, zero-copy HDR/EDR output, arbitrary clipboard
  MIME UI, Internet transport, or public-network E2EE;
- frame rendering currently creates a Core Image display image per decoded
  frame; Metal zero-copy rendering remains a measured optimization gate.

## Required host integration

The baseline MacHost compatibility boundary now admits the iOS trusted-LAN
client and composes it with the existing Protocol v1 main session. This closes
the basic port `54321` interoperability gap only. Advanced host integrations
must still preserve these client semantics:

- Hello plus explicit negotiated capabilities/resource limits;
- independent per-client epochs and unique per-session display stream IDs;
- multi-display allocation/input routing and bounded PCM audio capture;
- clipboard control, bulk file chunks, limits, cancellation, and digests;
- color-aware reject/retry using a newer config epoch;
- finite host action catalogs, authenticated/replay-safe wake helpers, and
  deny-wins managed policy;
- separate control/video/audio/bulk keys, sequences, and replay windows for
  trusted-LAN secure records and before enabling advanced channels on Internet
  transport.

See the [Phase 5 verification record](../../docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md)
and [dependency provenance](../../THIRD_PARTY.md) for exact evidence and
licensing.
