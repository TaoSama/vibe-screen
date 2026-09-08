# Nubia P0110 no-Host UI/UX after-691 current-main refresh

Date: 2026-09-08

Scope: Android no-Host UI/UX instrumentation plus focused JVM control-surface
contract checks on the connected Nubia P0110 after current `origin/main`
advanced to `693b90a1919746f140a27ba625b039e7fa625d27` / PR #691. Coverage
includes disconnected connection surfaces, USB/LAN and Internet error guidance,
Settings, control bar, file-transfer offer and outgoing preflight dialogs,
clipboard confirmation dialogs, Internet pairing/profile-import dialogs, QR
scanner layout, connection-state accessibility, Internet control state colors,
gesture preferences, narrow portrait, landscape, large-text boundaries, and
focused Android source contracts that keep no-Host clipboard/file-transfer
control-surface refresh paths away from system clipboard, picker, file read,
Downloads write, and protocol-send boundaries.

No Vibe Screen, MacHost, or Telemachus macOS GUI was launched. No `swift run`,
macOS TCC, Screen Recording, Accessibility, Microphone, Keychain, System
Settings, signing configuration, or `adb reverse tcp:54321 tcp:54321` command
was used.

## Source

Recorded in `metadata/source-provenance.txt`:

    repository=TaoSama/vibe-screen
    worktree=/Users/luwentao/.codex/worktrees/036c/vibe-screen/.claude/worktrees/p0110-no-host-uiux-current-main-20260908
    branch=codex/p0110-no-host-uiux-current-main-20260908
    base_head=693b90a1919746f140a27ba625b039e7fa625d27
    origin_main=693b90a1919746f140a27ba625b039e7fa625d27
    base_subject=Harden controller runtime evidence gate (#691)
    date=2026-09-08
    date_time=2026-09-08T13:21:24+0800
    timezone=Asia/Shanghai
    local_change=Adds focused no-Host control-surface boundary contract checks for Android clipboard and file-transfer UI refresh paths before running device/UI evidence.

This evidence is captured from a branch created from current `origin/main` at
the source commit above, with the local test/evidence additions in this change.
It is not evidence for an older #681-only tree.

## Device

Recorded in `metadata/device-identity.txt`:

    serial=<redacted-adb-serial>
    manufacturer=nubia
    model=P0110
    device=pacific
    release=16
    sdk=36
    wm_size=Physical size: 1264x2800
    wm_density=Physical density: 560
    font_scale=1.0

This record is Nubia P0110 / pacific / Android 16 / API 36 evidence only. It
must not be reported as Xiaomi 13/fuxi evidence.

## Commands

Run from `baseline/AndroidClient` unless noted. Device commands used the
redacted serial placeholder shown below.

    adb -s <redacted-adb-serial> devices -l
    adb -s <redacted-adb-serial> shell getprop ro.product.manufacturer
    adb -s <redacted-adb-serial> shell getprop ro.product.model
    adb -s <redacted-adb-serial> shell getprop ro.product.device
    adb -s <redacted-adb-serial> shell getprop ro.build.version.release
    adb -s <redacted-adb-serial> shell getprop ro.build.version.sdk
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
    adb -s <redacted-adb-serial> reverse --list
    command -v lsof
    lsof -nP -iTCP:54321 -sTCP:LISTEN

## Results

| Check | Evidence | Result |
| --- | --- | --- |
| Device identity | `metadata/device-identity.txt` | Device matched Nubia P0110 / pacific / Android 16 / API 36 with 1264x2800 at density 560 and font scale 1.0. |
| Pre-run no-Host boundary | `logs/adb-reverse-before-tests.txt`, `logs/no-host-boundary-lsof-54321-before.txt` | `adb reverse --list` was empty; `lsof` was available and returned no local `tcp:54321` listener rows (`status=1`). |
| P0110 no-Host UI/UX instrumentation | `android-test-results/TEST-P0110 - 16-_app-.xml`, `logs/connected-no-host-uiux-instrumentation.log`, `android-test-report/index.html` | Passed `87/87` with `failures=0`, `errors=0`, `skipped=0`; Gradle logged `Finished 87 tests on P0110 - 16` and `BUILD SUCCESSFUL in 5m`. |
| Focused no-Host control-surface JVM contracts | `logs/focused-control-surface-jvm-rerun.log`, `unit-test-results/` | Passed `19/19` across `MainActivityClipboardSystemBoundaryContractTest` (`8`), `MainActivityFileTransferSystemBoundaryContractTest` (`7`), and `MainActivityTransferReadinessContractTest` (`4`); Gradle logged `BUILD SUCCESSFUL in 19s`. |
| Superseded local test compile attempt | `logs/focused-control-surface-jvm.log` | Failed before verification because the new file-transfer contract initially missed the `assertFalse` import. The import was fixed and the rerun above is the passing evidence. |
| Post-run no-Host boundary | `logs/adb-reverse-after-tests.txt`, `logs/no-host-boundary-lsof-54321-after.txt` | `adb reverse --list` stayed empty; `lsof` returned no local `tcp:54321` listener rows (`status=1`). |

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

The focused JVM contracts add explicit no-Host guardrails for clipboard and
file-transfer control-surface refresh paths. They verify that UI refresh, stale
state cleanup, disconnected reset, pending clipboard status, and transfer
readiness rendering do not touch Android `ClipboardManager`, `primaryClip`,
`setPrimaryClip`, `ACTION_OPEN_DOCUMENT`, `startActivityForResult`,
`contentResolver.openInputStream`, `MediaStore.Downloads`, or incoming save
boundaries. The same contracts keep those system and protocol boundaries tied to
explicit user actions such as Send to Mac, approved receive, file-picker click,
outgoing send confirmation, and incoming completion handling.

## No-Host Boundaries

This run did not start or require a macOS Host and did not negotiate Protocol
v1 with a product Host. It did not create an `adb reverse tcp:54321 tcp:54321`
mapping. The retained reverse samples are empty. The retained local `lsof`
samples show `lsof` was available and returned no `tcp:54321` listener rows.

This package does not prove Host-backed bytes landing, Android <-> macOS
file-transfer offer/request/content exchange, sender file selection in a real
product session, receiver approval in a real product session, saved remote
files, final SHA-256 equality, Android ClipboardManager <-> macOS NSPasteboard
E2E, LAN streaming, Internet traversal, video decode, input forwarding,
reconnect timing, latency, soak, Host signing/TCC readiness, native pointer,
stylus, controller, iOS behavior, macOS hardware acceptance, or Xiaomi 13/fuxi
behavior.

## Artifact Notes

UTP binary `device-info.pb`, `test-result.pb`, `cpuinfo`, `meminfo`,
`utp.0.log`, and lock files were omitted because text XML/HTML/log artifacts
are sufficient for this no-Host refresh and avoid retaining extra device
identifiers. Instrumentation screenshots were not retained, so this evidence
package uses XML, HTML, textproto, and text logs.

## Verification

Run the checksum verification from this evidence directory:

    shasum -a 256 -c SHA256SUMS
