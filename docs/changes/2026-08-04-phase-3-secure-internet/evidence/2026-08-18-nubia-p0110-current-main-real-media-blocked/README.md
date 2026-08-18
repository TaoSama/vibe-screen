# Nubia P0110 current-main real-media re-verification - BLOCKED

This record captures a blocked verification attempt on `Nubia P0110 / pacific /
Android 16`, not Xiaomi 13 or fuxi. The source and both application artifacts
were built from clean commit
`5f7a4c394ac6f33b75636b17e12d15b425a0688b`, which matched `origin/main`
before and after the run. No product source changed for this attempt.

## Result

**BLOCKED by missing macOS Screen Recording permission.** The current-main
packaged Host launched, but its scoped log reported `Screen recording permission
not granted yet`, did not open the USB listener, and never entered display
capture or encoding. A read-only TCC query independently showed
`auth_value=0` for `kTCCServiceScreenCapture` and
`dev.telemachus.display`. No TCC, Keychain, or permission state was reset.

The Android client was rebuilt, installed with `adb install -r`, and cold-launched
successfully without uninstalling or clearing application data. During the
blocked observation it stayed on the non-sensitive `Waiting for your Mac`
surface. Its app-private diagnostic recorded 72 retryable
`TRANSPORT_CLOSED` endings over 108.453 seconds, with no Protocol v1 session,
decoder selection, MediaCodec first output frame, or fatal entry. These retries
are pre-session connection attempts and are not reconnect acceptance evidence.

The upstream task named gates `G18` and `G23`, but those literal identifiers do
not exist in this repository. For this task only, the real-capture continuity
gate is recorded as **BLOCKED**, while reconnect after an initially successful
media session is **NOT RUN**.

## What this proves

- The identified current-main commit and Android/macOS artifacts built
  successfully within the 20-minute command limit.
- The Android APK was installed in place with the same first-install time, CE/DE
  data inodes, signature, and denied Camera permission before and after the
  update.
- The packaged current-main Host passed strict code-signature verification and
  could launch on macOS 26.4.1.
- The blocker occurred before Host listening, capture, encoding, transport
  negotiation, or decoder configuration.

## What this does not prove

This attempt does not prove real ScreenCaptureKit or CGDisplayStream capture,
VideoToolbox output, USB media delivery, MediaCodec configuration or first
frame, sustained FPS, decode latency, dropped-frame behavior, a successful
session, reconnect, stale-epoch rejection, public Internet, remote TURN, E2EE,
glass-to-glass latency, memory stability, or soak. It does not update any
Phase 3 release gate and must not be presented as a stable release result.

The historical 2026-08-05 Nubia P0110 Phase 3 record used synthetic media at a
different commit and is not extended by this blocked run.

## Evidence layout

- [`acceptance.json`](acceptance.json): machine-readable blocked result.
- [`device-and-artifact-identity.txt`](device-and-artifact-identity.txt): redacted
  device facts, source identity, artifact hashes, and signing identity.
- [`build-and-install.txt`](build-and-install.txt): bounded build/install results
  and in-place data-retention checks.
- [`host-signing-and-permissions.txt`](host-signing-and-permissions.txt): Host
  signature and Screen Recording diagnostics.
- [`android-blocked.log`](android-blocked.log): privacy-safe projection of the
  blocked Android observation.
- [`host-permission-window.log`](host-permission-window.log): only the six Host
  lines emitted by the current-main launch; older Host history is excluded.
- [`android-blocked-window.log`](android-blocked-window.log): the app-private
  diagnostic window for this blocked observation.
- [`commands.txt`](commands.txt): redacted command ledger.
- [`android-waiting-for-mac.png`](android-waiting-for-mac.png): inspected device
  screenshot with no captured Mac content or personal data.
- [`privacy-scan.json`](privacy-scan.json): deterministic privacy scan.
- [`SHA256SUMS`](SHA256SUMS): integrity binding for every archived file except
  itself.

Full logcat, UI XML, unredacted device identity, Host logs, and raw app-private
diagnostics remain outside the repository. They were not required to state the
blocker and contain data outside this evidence scope.
