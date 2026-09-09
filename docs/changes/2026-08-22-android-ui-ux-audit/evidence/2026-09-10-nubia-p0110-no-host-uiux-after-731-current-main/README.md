# Nubia P0110 no-Host UI/UX after-731 current-main refresh

Date: 2026-09-10

Scope: Android no-Host UI/UX instrumentation, focused control-surface JVM
contracts, and a manual no-Host first-screen screenshot on the connected Nubia
P0110 after current `origin/main` advanced to
`0da8602c67d6f3a9fcbd461eb757fa6754b0e1f5` / PR #731. Coverage includes
disconnected connection surfaces, USB/LAN and Internet error guidance, Settings,
control bar, file-transfer offer and outgoing preflight dialogs, clipboard
confirmation dialogs, Internet pairing/profile-import dialogs, QR scanner
layout, connection-state accessibility, Internet control state colors, gesture
preferences, narrow portrait, landscape, large-text boundaries, and focused
Android source contracts that keep no-Host clipboard/file-transfer
control-surface refresh paths away from system clipboard, picker, file read,
Downloads write, and protocol-send boundaries.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used. The only reverse command used was read-only `adb reverse --list` to
prove no reverse mapping was present.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    worktree=<local-codex-worktree>/vibe-screen
    branch=codex/nubia-nohost-uiux-current-main
    base_head=0da8602c67d6f3a9fcbd461eb757fa6754b0e1f5
    origin_main=0da8602c67d6f3a9fcbd461eb757fa6754b0e1f5
    base_subject=Guard macOS host readiness login probe (#731)
    date=2026-09-10
    timezone=Asia/Shanghai
    local_change=Refreshes Nubia P0110 no-Host Android UI/UX instrumentation and focused control-surface JVM evidence after current main advanced through PR #731.

This evidence is captured from a branch created from current `origin/main` at
the source commit above. It is not evidence for an older after-713 tree.

## Device

The online serial was confirmed with `adb devices -l` before running tests and
matched the connected Nubia device. Retained artifacts redact the serial. The
old offline/user-provided serial was not used or substituted.

Recorded in `metadata/device-identity.txt`:

    serial=<redacted-adb-serial>
    actual_serial_verified_online=yes
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    fingerprint=nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from `baseline/AndroidClient` unless noted. Device commands used the
redacted serial placeholder shown below. The exact command list is retained in
`commands.txt`.

    adb -s <redacted-adb-serial> devices -l
    adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-adb-serial> shell getprop ro.product.model
    adb -s <redacted-adb-serial> shell getprop ro.product.device
    adb -s <redacted-adb-serial> shell getprop ro.build.version.release
    adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk
    adb -s <redacted-adb-serial> shell getprop ro.build.fingerprint
    adb -s <redacted-adb-serial> shell wm size
    adb -s <redacted-adb-serial> shell wm density
    adb -s <redacted-adb-serial> shell settings get system font_scale
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN
    ./gradlew --no-daemon :app:testDebugUnitTest \
      --tests dev.telemachus.display.MainActivityClipboardSystemBoundaryContractTest \
      --tests dev.telemachus.display.MainActivityFileTransferSystemBoundaryContractTest \
      --tests dev.telemachus.display.MainActivityTransferReadinessContractTest
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:connectedDebugAndroidTest \
      -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ConnectionGuidanceLayoutInstrumentedTest,dev.telemachus.display.ConnectionStateAccessibilityInstrumentedTest,dev.telemachus.display.ControlBarLayoutInstrumentedTest,dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.InternetControlStateColorsInstrumentedTest,dev.telemachus.display.InternetPairingDialogLayoutInstrumentedTest,dev.telemachus.display.QRScannerLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest,dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest,dev.telemachus.display.ClipboardConfirmationDialogLayoutInstrumentedTest
    ANDROID_SERIAL=<redacted-adb-serial> ./gradlew --no-daemon :app:installDebug
    adb -s <redacted-adb-serial> shell am start -W -n dev.telemachus.display/.MainActivity
    adb -s <redacted-adb-serial> shell screencap -p /sdcard/vibescreen-nohost-main.png
    adb -s <redacted-adb-serial> pull /sdcard/vibescreen-nohost-main.png screenshots/nohost-main.png
    adb -s <redacted-adb-serial> shell uiautomator dump /sdcard/vibescreen-nohost-main.xml
    adb -s <redacted-adb-serial> reverse --list
    lsof -nP -iTCP:54321 -sTCP:LISTEN

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Device identity | `metadata/device-identity.txt`, `logs/adb-devices.txt` | Device matched Nubia P0110 / pacific / Android 16 / API 36 with 1264x2800 at density 560, font scale 1.0, and build fingerprint `nubia/pacific/pacific:16/2.6.2.0/20260907.013634:userdebug/test-keys`. |
| Pre-run no-Host boundary | `logs/adb-reverse-before-tests.txt`, `logs/no-host-boundary-lsof-54321-before.txt`, `logs/no-host-boundary-lsof-54321-before-status.txt` | Read-only `adb reverse --list` was empty; `lsof` was available and returned no local `tcp:54321` listener rows (status=1). |
| P0110 no-Host UI/UX instrumentation | `android-test-results/TEST-P0110 - 16-_app-.xml`, `logs/connected-no-host-uiux-instrumentation.log`, `android-test-report/index.html` | Passed 87/87 with failures=0, errors=0, skipped=0; Gradle logged `Finished 87 tests on P0110 - 16` and `BUILD SUCCESSFUL in 1m 17s`. |
| Focused no-Host control-surface JVM contracts | `logs/focused-control-surface-jvm.log`, `unit-test-results/` | Passed 19/19 across `MainActivityClipboardSystemBoundaryContractTest` (8), `MainActivityFileTransferSystemBoundaryContractTest` (7), and `MainActivityTransferReadinessContractTest` (4); Gradle logged `BUILD SUCCESSFUL in 35s`. |
| Manual first-screen visual audit | `screenshots/nohost-main.png`, `logs/manual-launch-mainactivity.txt` | Debug APK launched cold into the no-Host USB retry surface. The retained 1264x2800 screenshot shows the retry title, segmented USB/LAN/Internet control, Retry Now button, USB route unavailable state, checklist, and explanatory card visible without obvious overlap or clipping. |
| UIAutomator dump attempt | `logs/uiautomator-dump.txt`, `logs/uiautomator-pull.txt` | Failed to produce a hierarchy because the live retry spinner prevented idle detection (`ERROR: could not get idle state.`). This is retained as diagnostic context only and is not counted as a layout failure. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-after.txt`, `logs/no-host-boundary-lsof-54321-after-status.txt` | Read-only `adb reverse --list` stayed empty; `lsof` returned no local `tcp:54321` listener rows (status=1). |

The retained instrumentation classes are:

- `ConnectionGuidanceLayoutInstrumentedTest`
- `ConnectionStateAccessibilityInstrumentedTest`
- `ControlBarLayoutInstrumentedTest`
- `SettingsDialogLayoutInstrumentedTest`
- `InternetControlStateColorsInstrumentedTest`
- `InternetPairingDialogLayoutInstrumentedTest`
- `QRScannerLayoutInstrumentedTest`
- `GestureShortcutPreferencesInstrumentedTest`
- `FileTransferOfferDialogLayoutInstrumentedTest`
- `ClipboardConfirmationDialogLayoutInstrumentedTest`

The focused JVM contracts verify that UI refresh, stale state cleanup,
disconnected reset, pending clipboard status, and transfer readiness rendering do
not touch Android ClipboardManager, `primaryClip`, `setPrimaryClip`,
`ACTION_OPEN_DOCUMENT`, `startActivityForResult`, `contentResolver.openInputStream`,
`MediaStore.Downloads`, or incoming save boundaries. The same contracts keep
those system and protocol boundaries tied to explicit user actions such as Send
to Mac, approved receive, file-picker click, outgoing send confirmation, and
incoming completion handling.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol v1
with a product Host. It did not create an `adb reverse tcp:54321 tcp:54321`
mapping. The retained read-only reverse samples are empty. The retained local
`lsof` samples show `lsof` was available and returned no `tcp:54321` listener
rows.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection in a real
product session, receiver approval in a real product session, saved remote
files, final SHA-256 equality, Android ClipboardManager <-> macOS NSPasteboard
E2E, LAN streaming, Internet traversal, video decode, input forwarding,
reconnect timing, latency, soak, Host signing/TCC readiness, native pointer,
stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi
behavior.

## Artifact Notes

UTP binary `device-info.pb`, `test-result.pb`, `cpuinfo`, `meminfo`, `utp.0.log`,
lock files, and Gradle binary unit-test caches were omitted because text XML,
HTML, screenshot, and log artifacts are sufficient for this no-Host refresh and
avoid retaining extra device identifiers. The retained screenshot is a manual
visual audit supplement, not Host-backed runtime evidence.

No Android source or test code change was required; no clear, safe UI/UX defect
was found in this pass.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
