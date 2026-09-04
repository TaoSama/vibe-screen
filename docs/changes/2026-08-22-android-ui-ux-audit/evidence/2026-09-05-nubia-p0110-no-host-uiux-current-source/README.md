# Nubia P0110 no-Host UI/UX smoke current-source

Date: 2026-09-05

Branch: `codex/android-uiux-no-host-smoke-20260905`

Source revision: the containing commit for this evidence package.

Base source revision: `f87ff5b99985925405443139494393132370dd2d`

Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial
`<redacted-adb-serial>`.

## Scope

This is Android-client UI/UX smoke evidence only. The run deliberately kept the
macOS Host out of scope: no Host binary was launched, no Screen Recording or
Accessibility/TCC path was exercised, no `adb reverse tcp:54321 tcp:54321` was
created, and no Protocol v1 product session was negotiated.

The retained no-Host boundary samples show an empty local TCP `54321` listener
probe and `adb reverse --list` samples containing only `UsbFfs tcp:8908
tcp:8908`. Those samples support only the no-Host/no-product-transport boundary
for this smoke; they do not prove global Host absence outside the sampled
checks.

This record is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13/fuxi evidence.

## Valid Evidence

| Area | Retained artifacts | Result |
| --- | --- | --- |
| Build | `logs/assemble-debug.txt` | `./gradlew --no-daemon assembleDebug` completed successfully. |
| Lint | `logs/lint-debug.txt` | `./gradlew --no-daemon lintDebug` completed successfully. |
| Focused JVM tests | `logs/focused-unit-tests.txt` | Focused connection, settings, transfer-readiness, actionable-error, and status-overlay unit checks passed. |
| Focused P0110 instrumentation | `logs/focused-instrumentation-tests.txt` | `ConnectionGuidanceLayoutInstrumentedTest`, `SettingsDialogLayoutInstrumentedTest`, and `ControlBarLayoutInstrumentedTest` completed 35/35 tests with 0 failures on P0110 / Android 16. |
| no-Host boundary | `logs/no-host-boundary.txt`, `logs/adb-reverse-before.txt` | Local TCP `54321` had no retained listener output, and ADB reverse samples did not include `tcp:54321`. |
| USB disconnected page | `screenshots/screen-01-disconnected.png`, `ui-dumps/ui-01-disconnected.xml` | USB mode renders `Waiting for your Mac`, the USB/LAN/Internet segmented control, `CONNECT`, and `DISPLAY SETTINGS` while disconnected. |
| USB retry/error page | `screenshots/screen-03-usb-retry-error.png`, `ui-dumps/ui-03-usb-retry-error.xml` | A no-Host retry renders `USB route unavailable` and a checklist with `Mac server · Not ready`. |
| Settings transfer readiness | `screenshots/screen-12-settings-after-fix.png`, `ui-dumps/ui-12-settings-after-fix.xml` | Settings renders `Clipboard & files`, `Waiting for a compatible Mac session`, and the shortened `Clipboard and file controls require Protocol v1.` copy. |
| LAN no-Host page | `screenshots/screen-08-lan.png`, `ui-dumps/ui-08-lan.xml` | LAN mode renders `Connect wirelessly`, trusted-network copy, and `SCAN QR CODE` without a Host session. |
| Internet no-Host page | `screenshots/screen-09-internet.png`, `ui-dumps/ui-09-internet.xml` | Internet preview renders no-profile state, DIRECT/TURN route policy, and `CONNECT PREVIEW` without a Host session. |
| Orientation/font stress | `screenshots/screen-10-landscape-fontscale-1_3.png`, `ui-dumps/ui-10-landscape-fontscale-1_3.xml` | The disconnected USB page remains readable under landscape with `font_scale=1.3`. |

## Excluded Artifacts

Earlier captures from this run included unrelated system-home and private-app UI
state while the test driver was navigating between screens. Those artifacts
were removed from this source evidence package and are not valid evidence for
the no-Host UI/UX gate. The retained package intentionally keeps only Vibe
Screen UI dumps, screenshots, device metadata, no-Host boundary logs, and
current verification logs. The XML dumps omit non-content boolean fields from
the raw UIAutomator export so the retained text evidence stays scanner-friendly.

## Not Proven

This package does not prove Android <-> macOS clipboard transfer, file-transfer
offer/request/content packets, receiver approval, saved remote file bytes,
SHA-256 equality across endpoints, Protocol v1 capability negotiation, USB/LAN
transport readiness, public Internet traversal, video decode, input forwarding,
reconnect timing, Host signing/TCC readiness, display switching, window actions,
or Xiaomi 13/fuxi behavior.

## Verification

Run the checksum verification from this evidence directory:

```bash
cd docs/changes/2026-08-22-android-ui-ux-audit/evidence/2026-09-05-nubia-p0110-no-host-uiux-current-source
shasum -a 256 -c SHA256SUMS
```

The submitted evidence set was checked after the README, assertions, commands,
and final verification logs were added; every entry in `SHA256SUMS` reported
`OK`.
