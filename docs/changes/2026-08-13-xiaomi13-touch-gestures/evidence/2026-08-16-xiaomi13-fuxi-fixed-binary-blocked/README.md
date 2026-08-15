# Xiaomi 13 fixed-binary touch-gesture rerun (blocked)

Date: 2026-08-16 (Asia/Shanghai)

## Result

**BLOCKED.** The fixed, stable-signed Host reached Protocol v1 streaming on the
Xiaomi 13, but its Accessibility grant was absent during the run. The Host
checks `AXIsProcessTrusted()` before accepting touch input, so the opt-in
instrumentation driver was deliberately not run. A client-only `OK` result
would not have proved that macOS received or posted any gesture events.

Consequently, none of the requested gestures is passed by this record:

| Gesture | Result | Evidence boundary |
| --- | --- | --- |
| Tap | BLOCKED | No opt-in instrumentation run and no synchronized Host gesture event |
| Long-press right click | BLOCKED | No right-click gesture event |
| Long-press drag | BLOCKED | No target drag gesture event |
| Two-finger scroll | BLOCKED | No target two-finger gesture event |
| Pinch | BLOCKED | No Command-modified target scroll event |
| Ordinary pointer event after pinch | BLOCKED | Pinch never ran, so modifier isolation was not exercised end to end |

## Source and timing

- Device-window source: `c275838e0758f2aaaa7a7edde42306ac1420514e`.
- `c275838` was the fetched `origin/main` at the start of the device run.
- Window: `2026-08-15T16:29:41Z` through `2026-08-15T16:34:43Z`
  (5 minutes 2 seconds, below the 20-minute limit).
- `104a4a979be278491021ac7ffd3a51bafd6b0c88` reached `main` at
  `2026-08-16T00:39:04+08:00`, after the device window ended. This evidence
  directory is based on that newer `main` commit, but it does not extend the
  device result to that source.

## Device and artifacts

- Xiaomi 13, model `2211133C`, codename `fuxi`.
- Android 16 / API 36.
- Build fingerprint:
  `Xiaomi/fuxi/fuxi:16/BP2A.250605.031.A3/OS3.0.2.0.WMCCNXM:user/release-keys`.
- Physical display: `1080x2400`, density `420`.
- ADB-over-network endpoint is intentionally omitted.
- Debug APK SHA-256:
  `b96f0d4430fe7cf18b77dde770c34103679cb8f543beed9f1b6684a86d5d5c8b`.
- Test APK SHA-256:
  `c051c96e9beba94e10d713ca094dd969620094daf989ccb27315fbc822988f48`.
- Fixed Host binary SHA-256:
  `aa1cdba1d65b8a4ed7e9376fcd329b3c8dbb6e635dbf61f1c1b61af727fb592d`.

The Android build ran `:transport:check`, `testDebugUnitTest`, `lintDebug`,
`assembleDebug`, and `assembleDebugAndroidTest`; it finished `BUILD SUCCESSFUL
in 48s`. The release Host build finished in 130.87 seconds.

## Host identity and permissions

The fixed Host was packaged with the existing `Vibe Screen Dev` identity:

- certificate SHA-1: `9AAE572BF6D764E3436A6109197D345B5A87998C`;
- CDHash: `e4ac7dab68720d647550f2e031f40070ab291e8b`;
- identifier: `dev.telemachus.display`;
- designated requirement:
  `identifier "dev.telemachus.display" and certificate leaf = H"9aae572bf6d764e3436a6109197d345b5a87998c"`;
- `codesign --verify --deep --strict` reported the bundle valid on disk and
  satisfying its designated requirement.

No Keychain reset, password request, password storage, import, ACL update, or
partition-list update was performed in this run. Identity discovery and signing
were the only Keychain-related operations.

The read-only TCC capture used the field order
`service|client|client_type|auth_value|auth_reason|last_modified` and recorded:

```text
kTCCServiceAccessibility|dev.telemachus.display|0|0|4|1786811429
kTCCServiceScreenCapture|dev.telemachus.display|0|2|4|1786811437
```

Thus Screen Recording (`auth_value=2`) was authorized and Accessibility
(`auth_value=0`) was not. The Host log independently recorded Screen Recording
as granted and established a stream.

## Protocol v1 and media evidence

The installed client recorded `Protocol v1 upgrade accepted`. The Host recorded
`Protocol v1 selected for connection epoch 2`. Negotiated capabilities included
touch, keyboard, pointer, stylus, multi-display, Host actions, client video
control, and extended stylus. The Qualcomm HEVC decoder
`c2.qti.hevc.decoder` was configured for `2000x1200`.

After upgrade, the Host repeatedly reported about 60 FPS, zero Host-side drops,
and roughly 7.5-9.6 ms average frame age. This proves the production transport,
Protocol v1 session, capture, encode, and decode path was active; it does not
prove any gesture.

No `adb shell am instrument ... -e vibeScreenTouchE2E true` command ran. There
is no instrumentation `OK (1 test)` output and no Host `Touch gesture:` line. A
listen-only event tap ran to confirm observation capability, but its unrelated
desktop input is intentionally excluded because it cannot substitute for a
synchronized target gesture sequence.

## Offline test boundary

The focused command was attempted after the device window:

```bash
cd baseline/MacHost
swift test --filter Phase1HostCapabilityTests/testTouchGestureFactoryIsolatesSyntheticZoomModifier
```

It did not execute the test body. This machine exposes only Command Line Tools
at `/Library/Developer/CommandLineTools`, and SwiftPM failed while compiling the
test target with `error: no such module 'XCTest'`. Historical coverage in the
parent `TEST.md` remains valid for its recorded source, but this rerun adds no
new offline pass.

## Cleanup

The fixed Host and event tap were stopped. The previously installed
`/Applications/Vibe Screen.app` was restored byte-for-byte:

- restored binary SHA-256:
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`;
- restored CDHash: `2fe65fd5cd69c80249140da3f139cfa68037c5c2`;
- restored authority: `Vibe Screen Dev`;
- strict deep verification passed.

The Android client was force-stopped. No Host, event-tap, or Android application
process remained. The repository-root `midscene_run` content was not deleted,
modified, or added to this evidence.

## Files

- `device-and-artifact-identity.txt`: device identity, hashes, and timing.
- `host-signing-and-permissions.txt`: stable signing and TCC evidence.
- `protocol-and-media.log`: redacted session and decoder excerpts.
- `build-and-test-results.txt`: build results and the XCTest toolchain block.
- `android-blocked-screen.png`: client screenshot captured near the block.
- `android-streaming-screen-secure.png`: active fixed-binary stream screenshot.
- `privacy-scan.json`: generated privacy manifest for the evidence directory.

Raw logs and application packages remain outside Git because they contain
private paths/endpoints or redundant binary artifacts.
