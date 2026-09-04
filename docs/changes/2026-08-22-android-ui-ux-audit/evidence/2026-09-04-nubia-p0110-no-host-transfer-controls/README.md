# 2026-09-04 Nubia P0110 no-Host transfer controls smoke

Date: 2026-09-04
Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial <redacted-adb-serial>
Repository: TaoSama/vibe-screen
Base commit: 322815420bfa24af40aa4cfd79425ff6803522cd
Branch: codex/android-no-host-transfer-controls-smoke-20260904

This record is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13 / fuxi evidence.

## Scope

This smoke verifies the Android client UI when no macOS Host route is available.
It specifically checks that the no-Host connection screen does not expose
Clipboard or File transfer controls before a product session negotiates the
corresponding Protocol v1 capabilities.

This is a UI/UX and fail-closed availability smoke only. It does not claim
Android <-> macOS clipboard transfer, file-transfer product E2E, stream
stability, reconnect timing, Host readiness, signing, TCC, LAN, Internet, or any
macOS behavior.

## Preconditions

- The debug APK was built from the current `origin/main` tree.
- The existing `tcp:54321` ADB reverse was removed before launch so the client
  could not reach a Host listener through the USB product port.
- No macOS Host was started and no macOS Screen Recording, Accessibility, or
  Microphone permission flow was touched.
- One unrelated reverse, `tcp:8908 -> tcp:8908`, remained present and is not the
  Vibe Screen product port.

## Device Identity

Recorded in `device-identity.txt` with explicit ADB serial commands:

- Manufacturer: nubia
- Model: P0110
- Codename: pacific
- Android release: 16
- SDK: 36
- Display: 1264x2800, density 560

All retained command transcripts redact the USB serial as
`<redacted-adb-serial>`.

## Result

PASS for this narrow no-Host UI smoke.

The stable UIAutomator dump shows the Vibe Screen app in foreground on the
waiting screen with these visible controls and messages:

- VIBE SCREEN
- Waiting for your Mac
- USB / LAN / Internet segmented controls
- CONNECT
- Looking for Vibe Screen on your Mac
- Connection details
- Display settings
- Open-source licenses

The same dump contains no `Clipboard`, `File transfer`, `Cancel file transfer`,
or `Mac content available` text or content descriptions. This verifies that the
Android client does not present clipboard or file-transfer actions while no
Host/product session is available.

## Retained Artifacts

- `adb-install.txt` - debug APK install transcript.
- `adb-no-host-stable-capture.txt` - redacted command transcript showing
  `tcp:54321` absent from `adb reverse --list`, the app foreground, UIAutomator
  dump success, and screenshot capture.
- `adb-no-host-ui-capture.txt` - first auto-connect retry capture; UIAutomator
  could not reach idle during the retry countdown, but the screenshot is
  retained.
- `device-identity.txt` - P0110 identity and display properties.
- `window-no-host-stable.xml` - stable UIAutomator hierarchy used for the
  pass/fail assertion.
- `screen-no-host-stable.png` - stable no-Host waiting screen screenshot.
- `screen-no-host.png` - first retry-state screenshot.

## Verification

The stable XML was checked with:

```bash
rg -o 'text="[^"]*"|content-desc="[^"]*"' window-no-host-stable.xml
rg -n 'Clipboard|File transfer|Cancel file transfer|Mac content available' window-no-host-stable.xml
```

The first command lists the expected no-Host waiting and connection controls.
The second command returns no matches.

## Not Proven

- No Android <-> macOS clipboard data exchange was attempted.
- No Android <-> macOS file transfer was attempted.
- No Host listener, product Protocol v1 session, file offer/request/content
  packet, receiver approval, saved remote file, SHA-256 equality, progress, or
  cancel cleanup was observed.
- This record does not close the `clipboard_android_macos_product_e2e` or
  `file_transfer_android_product_e2e` gates.
