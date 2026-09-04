# Nubia P0110 no-Host UI/UX smoke current-base

Date: 2026-09-04

Branch: `codex/p0110-no-host-ui-ux-smoke-20260904`

Source revision: `e4d7861b8af3ffa8d32fff99b022e92193acc071`

Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial
`<redacted-adb-serial>`.

## Scope

This is Android-client UI/UX smoke evidence only. It deliberately keeps the
macOS Host out of scope: no Host binary was launched, no Screen Recording or
Accessibility/TCC path was exercised, no `adb reverse tcp:54321 tcp:54321` was
created, and no Protocol v1 session was negotiated.

The retained `adb reverse --list` samples show only `UsbFfs tcp:8908 tcp:8908`.
The retained local port probes for TCP `54321` are empty. Those records support
only the no-Host/no-product-transport boundary; they do not prove Host absence
globally beyond the sampled checks.

## Valid evidence

| Area | Retained artifacts | Result |
| --- | --- | --- |
| Current-base build and install | `logs/final-no-host-smoke-14.txt` | `./gradlew --no-daemon assembleDebug` completed successfully, the debug APK installed on the P0110, and `MainActivity` was foregrounded with `auto_connect=false`. |
| USB no-Host waiting page | `screenshots/screen-14-final-disconnected.png`, `ui-dumps/ui-hierarchy-14-final-disconnected.xml` | USB mode renders `Waiting for your Mac`, `CONNECT`, the USB/LAN/Internet segmented control, and the display settings entry while disconnected. |
| LAN no-Host page | `screenshots/screen-16-final-lan.png`, `ui-dumps/ui-hierarchy-16-final-lan.xml` | LAN mode renders `Connect wirelessly`, the trusted-private-network warning, and `SCAN QR CODE` without requiring a Host session. |
| Internet no-Host page | `screenshots/screen-17-final-internet.png`, `ui-dumps/ui-hierarchy-17-final-internet.xml` | Internet preview renders the no-profile state, DIRECT/TURN route policy, disabled `CONNECT PREVIEW`, and settings/revoke actions. |
| Connection failure state | `screenshots/screen-02-disconnected-controlbar-reveal-attempt.png`, `ui-dumps/ui-hierarchy-02-disconnected-controlbar-reveal-attempt.xml` | A disconnected USB retry shows `USB route unavailable` and the connection checklist. No active stream control bar or transfer actions are present. |
| Orientation/font stress | `screenshots/screen-06-no-host-landscape-fontscale-1_3.png`, `ui-dumps/ui-hierarchy-06-no-host-landscape-fontscale-1_3.xml`, `screenshots/screen-08-restored-portrait.png`, `ui-dumps/ui-hierarchy-08-restored-portrait.xml` | The disconnected USB page remains usable under forced landscape with `font_scale=1.3`, then returns to the standard portrait layout after settings restoration. |
| Settings page, normal font | `screenshots/screen-15-final-settings.png`, `ui-dumps/ui-hierarchy-15-final-settings.xml` | The settings dialog shows `Display settings`, `Clipboard & files`, `Waiting for a compatible Mac session`, and the Protocol v1 readiness copy in the final rerun. |
| Settings page, font stress | `screenshots/screen-10-settings-portrait-fontscale-1_3-recaptured.png`, `ui-dumps/ui-hierarchy-10-settings-portrait-fontscale-1_3-recaptured.xml` | The same settings content remains visible with `font_scale=1.3`; text wraps within the panel and the readiness section stays readable. |
| Final smoke log | `logs/final-no-host-smoke-15-settings-lan-internet.txt` | The final navigation pass captured Settings, LAN, and Internet dumps/screenshots, recorded `adb reverse --list` before and after navigation, and sampled logcat without a matching Vibe Screen crash line. |

`assertions.txt` records the targeted checks for device identity, absence of the
product reverse port, connection-page foreground capture, disconnected-page
absence of product transfer controls, and settings readiness copy.

## Excluded artifacts

The original `screen-03-settings-portrait`,
`screen-07-settings-landscape-fontscale-1_3`, and
`screen-09-settings-portrait-recaptured` artifacts were attempted captures
only. Their XML shows the disconnected connection page, not the settings dialog,
so they are excluded from the submitted checksum and are not used as settings
evidence.

The original LAN/Internet captures were superseded because they landed on the
Android launcher instead of the Vibe Screen app. Their screenshots and XML/token
artifacts are excluded from the submitted checksum; `screen-16` and
`screen-17` are the valid LAN/Internet evidence.

Intermediate duplicate captures such as `screen-11`, `screen-12`, and
`screen-13` were used only while collecting the final run. They are excluded
from the submitted checksum to avoid numbered-artifact ambiguity; `screen-14`
through `screen-17` are the final indexed captures.

Broad process snapshots are not used to prove Host absence. The narrower
retained boundary is the empty TCP `54321` listener probes plus the ADB reverse
listings that do not include `tcp:54321`.

## Not proven

This package does not prove any Android <-> macOS clipboard transfer,
file-transfer offer/request/content packet, receiver approval, saved remote
file, SHA-256 equality across endpoints, Protocol v1 capability negotiation,
USB/LAN transport readiness, public Internet traversal, video decode, reconnect,
Host signing/TCC readiness, or Xiaomi 13/fuxi behavior. The device identity for
this evidence remains Nubia P0110 / pacific / Android 16 only.

## Verification

Run the checksum verification from this evidence directory:

```bash
cd docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-04-nubia-p0110-no-host-ui-ux-current-base
shasum -a 256 -c SHA256SUMS
```

The submitted evidence set was checked after redaction and artifact cleanup;
every entry in `SHA256SUMS` reported `OK`.
