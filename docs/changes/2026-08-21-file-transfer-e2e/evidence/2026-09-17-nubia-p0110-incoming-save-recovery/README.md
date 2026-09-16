# Nubia P0110 incoming-save recovery

This current-source Android-local run verifies that a fully received file remains recoverable when publication to Downloads fails. It also exercises the durable publication journal that prevents duplicate Downloads rows across Activity recreation and process restart.

## Source and device

- Source base: `d8fde209161ddbf0ab26382e68f2b4bdbe79dacc`
- Verified source head: `528ceb7c3`
- Branch: `codex/android-incoming-save-recovery`
- Device: nubia P0110 (`pacific`), Android 16 / API 36
- Device serial is redacted in retained evidence.
- App APK SHA-256: `2a1d8b686a85968c0e38bb7fc8476b62f74927eb835878e00de3dacd0ac819ef`
- Test APK SHA-256: `26be5530531394b23d66e64309273e6acbcf21e30f093f75aa8f953bca025503`

## Results

- Android JVM suite: 1898 tests, 0 failures, 0 errors, 0 skipped.
- Focused device suite: 4/4 passed.
  - cold-start recovery survives Activity recreation, publishes exact bytes/SHA-256, creates exactly one visible Downloads row, and clears private recovery;
  - discard requires explicit confirmation and removes recovery;
  - a persisted pending MediaStore URI is reused after Store recreation and becomes `IS_PENDING=0` without inserting another row;
  - a `PUBLISHED` journal record with an already-removed private payload is cleaned after Store recreation without creating another Downloads row.
- External process-stop flow: seed 1/1 and verify 1/1 passed around `adb shell am force-stop`; the recovery surface returned after process restart.
- UI inspection: ordinary portrait, font scale 2.0 portrait, and landscape retained readable actions without incoherent overlap. Large-font content remains scrollable.
- No Host boundary: no ADB reverse mapping, no TCP 54321 listener, no macOS Host launch, and no macOS TCC request.
- The focused 4/4 suite and APK hashes were refreshed after review fixes at `528ceb7c3`; the force-stop logs and UI screenshots predate that review-only code/test adjustment.

## Product behavior covered

- USB/LAN and Internet final-chunk acceptance now adopts verified bytes into durable private ownership before sending accepted completion.
- Stale-session completion no longer hides an already-durable recovery from the current Activity.
- Downloads publication persists `RECEIVED`, reserved target, and `PUBLISHED` states. Retries reuse the same MediaStore URI or app-specific partial/target.
- Activity recreation is protected by a process-wide publication lease.
- Retry and discard are visible, separately disabled while running, and discard requires confirmation.

## Evidence boundary

This is Android-local no-Host evidence. It does not prove Host-origin bytes, a shared protocol session ID, ordered Android/macOS transfer chunks, Host destination bytes, or bidirectional Android ClipboardManager/NSPasteboard behavior. It therefore does not close the Android/macOS file-transfer product E2E gate or the Phase 0 stable-release aggregate. API 26-28 recovery is covered by JVM filesystem tests, not by this API 36 device. Strict power-loss durability after filesystem rename is not proven because directory fsync is not recorded.
