# Nubia P0110 Android UI/UX smoke

Date: 2026-08-28
Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial <redacted-adb-serial>
Repository: TaoSama/vibe-screen
Base commit: f5db90a761e158798065ce1078bf49428031ce49
Branch: codex/p0110-android-uiux-smoke-20260828

This record is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13 / fuxi evidence.

## Scope

This smoke covers the Android client's visible UI paths that were reachable in a
short shared-device lease: app launch, current USB streaming status, control
capsule, display selector affordance, settings dialog, disconnect confirmation,
plus code-level coverage for an actionable USB error-state visual fix.

It is a smoke record only. It does not close README acceptance gates for stream
stability, reconnect timing, display switching, native pointer, stylus,
controller, LAN, audio, latency, soak, Host RSS, or macOS hardware support.

## Change Under Test

The Android USB inline failure presenter now turns the primary connection status
indicator red while the inline error guidance is visible. Checklist refreshes
preserve that red indicator instead of overwriting it with waiting/ready state
until the guidance is cleared.

## Device Identity

Recorded in device-identity.txt with explicit ADB serial commands:

- Manufacturer: nubia
- Model: P0110
- Codename: pacific
- Android release: 16
- SDK: 36
- Serial: <redacted-adb-serial>
- Display: 1264x2800, density 560

All ADB commands used adb -s <redacted-adb-serial> ... .

## Automated Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Protocol gate | PASS | protocol-check.txt |
| Focused JVM guidance tests | PASS | focused-unit-tests.txt |
| Android offline gate (clean testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies) | PASS | android-offline-gate.txt |
| Debug APK install on P0110 | PASS | adb-install-final.txt |

## P0110 UI Observations

| Path | Result | Evidence |
| --- | --- | --- |
| App foreground / current USB session | PASS | adb-start.txt, window-focus.txt, window-launch.xml |
| Control capsule visible | PASS | window-controlbar-revealed.xml, ui-summary.txt |
| Display selector affordance | PASS, current display affordance observed | window-display-selector-retry.xml |
| Settings dialog | PASS | window-settings-retry.xml, screen-settings-retry.png, ui-summary.txt |
| Disconnect confirmation | PASS | window-disconnect-confirm-retry2.xml, screen-disconnect-confirm-retry2.png, ui-summary.txt |
| Error-state red indicator | Code-level PASS, device-state not reproduced | focused-unit-tests.txt; P0110 stayed in an active USB stream during the short lease |

The control capsule UIAutomator dump shows the current USB connection label,
ADB reverse detail, Choose display currently DELL U2723QE, Settings, and
Disconnect controls. Settings dump shows Display settings, Show Stats, video
quality controls, and sustained-use device-health text. Disconnect confirmation
shows Disconnect?, the session-ending message, and Cancel/Disconnect actions.

## Screenshot Note

Some P0110 screenshots are black because the streaming Activity uses secure
window behavior. XML dumps and app diagnostic logs are the primary evidence for
control presence and text in this smoke. Black screenshots are retained rather
than edited.

## Not Proven

- The new red error indicator was not reproduced on-device because the Mac Host
  was already serving a live USB stream and the app remained connected during
  the short lease.
- Full display dropdown contents were not captured in the retry path; the
  selector affordance and current display label were captured.
- TalkBack traversal, visual color sampling, reconnect timing, and any release
  acceptance gate remain open.
