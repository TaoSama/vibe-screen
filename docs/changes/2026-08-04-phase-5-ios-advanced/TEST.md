# Phase 5 verification record

Date: 2026-08-04  
Host: macOS 26.4.1, Apple silicon  
Swift: 6.3.1  
Selected developer directory: `/Library/Developer/CommandLineTools`

## Passed

```bash
swift package --package-path apps/ios resolve
swift build --package-path apps/ios
swift build --package-path apps/ios -c release
swift run --package-path apps/ios vibescreen-ios-selftest
make protocol
```

Observed result:

```text
Build complete!
RUN: framing
RUN: protocol/session
RUN: codec/backoff
RUN: multi-display/audio
RUN: clipboard/file/policy
RUN: HDR/gesture/wake/advanced-proto
PASS: Phase 5A-5D core protocol, limits, queues, digest, policy, fallback, wake
```

The self-test additionally covers multi-client epoch replacement, per-client
stream limits/routes, PCM validation and reorder, clipboard explicit-action
and feedback/digest rejection, managed deny-wins policy, safe filenames,
sequential chunks, file limits/final SHA-256/cleanup, HDR10→SDR config-epoch
fallback, gesture persistence/catalog enforcement, the 102-byte WOL vector,
and every advanced Envelope branch used by the client.

Project metadata also passes:

```text
plutil -lint apps/ios/VibeScreen.xcodeproj/project.pbxproj: OK
xmllint --noout .../VibeScreen.xcscheme: exit 0
swiftc -frontend -parse apps/ios/VibeScreenApp/*.swift: exit 0
GitHub Actions workflow YAML parse: OK
Buf format/lint/build/breaking: pass
Package.resolved revision: c6fe6442e6a64250495669325044052e113e990c
Pinned Swift binding regeneration: pass; checked output current
Second generation SHA-256 manifest diff: empty (deterministic)
Phase 3 protocol compatibility: 4/4 pass
Go security package: pass
```

## Environment gates and unproved behavior

`xcode-select -p` returns Command Line Tools. `xcodebuild -version` fails
because full Xcode is not installed; `iphoneos`, `iphonesimulator`, and
`simctl` are unavailable, and the keychain contains zero valid signing
identities. Therefore the following remain unproved:

- Xcode project resolution and iOS compilation;
- simulator launch and SwiftUI layout on iPhone/iPad sizes;
- signing, installation, Local Network permission, and lifecycle behavior;
- VideoToolbox hardware H.264/HEVC decode and sustained thermal/power behavior;
- end-to-end Protocol v1 host connection, video, touch, disconnect/reconnect;
- cross-client golden bytes against the Android application;
- AVAudioEngine audible output, UIPasteboard prompts/writes, security-scoped
  file picker/export, UDP broadcast, and managed App Configuration injection;
- host-side multi-client/display, audio capture, clipboard/file handlers,
  color retry, actions, wake helper, and audio/bulk E2EE replay isolation;
- HDR/EDR output (the current client deliberately advertises SDR only).

## Required iOS acceptance run

After installing full Xcode, run the commands in `apps/ios/README.md`, then on
real iPhone and iPad hardware record Xcode/OS/device identifiers, app revision,
host revision, negotiation envelopes, codec choice, stream/epoch telemetry,
touch acknowledgement, USB/network interruption, reconnect duration, and a
30-minute memory/latency series. Raw logs belong under this change directory's
`evidence/` subdirectory.

While the Phase 0 soak owns `100.72.246.116:5555`, Phase 5 performs only
read-only `getprop`, `logcat`, `dumpsys`, or `ps` queries and does not change
ADB, application, or session state. Any later Android Protocol v1 fixture run
must be coordinated by Phase 0. Android evidence is never an iOS build,
decode, UI, or device result.
