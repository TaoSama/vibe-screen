# Nubia P0110 no-Host UI/UX smoke current-source codex-2326

Date: 2026-09-05

Branch: codex/android-no-host-p0110-evidence

Source revision: 5b1b62c1248715e34d43a4d104235dd1cf7c057b

Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial
<redacted-adb-serial>.

## Scope

This is Android-client no-Host UI/UX evidence from the connected P0110 device.
The run deliberately did not start the macOS Host, did not create adb reverse
tcp:54321 tcp:54321, and did not exercise Screen Recording, Accessibility, or
any other macOS TCC path.

The purpose is to add current-source real-device evidence for surfaces that do
not require a Host session: connection pages, no-Host error state, retry
controls, display settings, transfer-readiness messaging, LAN/Internet entry
points, and a landscape/font-scale stress case.

This record is Nubia P0110 / pacific evidence only. It must not be reported as
Xiaomi 13/fuxi evidence.

## Result

PASS for this Android-only no-Host UI/UX smoke. No Android code change was
required.

## Valid Evidence

| Area | Retained artifacts | Result |
| --- | --- | --- |
| Device identity | logs/preflight-boundary.txt, metadata.json | ADB identified nubia / P0110 / pacific / Android 16 / SDK 36. |
| Build | logs/assemble-debug.txt, metadata/apk-sha256.txt | ./gradlew --no-daemon assembleDebug completed successfully and produced the debug APK. |
| Install | logs/adb-install.txt | adb install -r completed with Success. |
| no-Host boundary | logs/preflight-boundary.txt, logs/final-boundary.txt | adb reverse --list did not include tcp:54321; lsof -nP -iTCP:54321 -sTCP:LISTEN produced no listener output. |
| USB no-Host retry/error | screenshots/screen-08-after-restart.png, logs/front-activity-after-restart.txt, logs/logcat-vibescreen-filtered.txt | App stayed foreground and rendered USB route unavailable, retry control, and Mac server Not ready without crashing. Filtered logcat records expected ECONNREFUSED attempts to localhost 54321. |
| LAN no-Host page | screenshots/screen-09-lan-from-retry.png, logs/lan-capture-command.txt | App stayed foreground and rendered Connect wirelessly, trusted-network copy, and SCAN QR CODE. |
| Internet no-Host page | screenshots/screen-10-internet-from-lan.png, ui-dumps/ui-13-internet-after-settings.xml, logs/tokens-13-internet-after-settings.txt | App rendered Internet preview, no-profile state, DIRECT/TURN route policy, disabled CONNECT PREVIEW, SCAN QR, IMPORT, and REVOKE MAC. |
| Transfer readiness in settings | screenshots/screen-12-settings-transfer-readiness.png, ui-dumps/ui-12-settings-transfer-readiness.xml, logs/tokens-12-settings-transfer-readiness.txt | Settings rendered Clipboard & files, Waiting for a compatible Mac session, and Clipboard and file controls require Protocol v1. |
| Landscape/font stress | screenshots/screen-15-landscape-fontscale-1_3.png | USB retry/error page remained visible and readable at font_scale=1.3 in landscape. |

## Collection Notes

The USB retry page is animated and repeatedly retries; on that surface the
device-side UIAutomator command returned ERROR: could not get idle state and
did not always produce a fresh XML file. For the dynamic retry/error page, this
package therefore treats the retained screenshots, foreground-activity dumps,
and filtered Vibe Screen logcat as the evidence source. Stable settings and
Internet surfaces have successful XML dumps and token summaries.

Some intermediate captures were discarded because a BACK/key sequence briefly
returned the device to the launcher during coordinate calibration. Those files
are intentionally not retained in this evidence package and are not used for
the result above.

## Not Proven

This package does not prove macOS Host readiness, Protocol v1 negotiation,
video streaming, input forwarding, clipboard transfer, file-transfer bytes,
LAN transport, Internet traversal, reconnect timing, Host signing/TCC
readiness, display switching, window actions, or Xiaomi 13/fuxi behavior.

## Verification

Run from this directory:

    shasum -a 256 -c SHA256SUMS

All retained files in this evidence package are covered by SHA256SUMS.
