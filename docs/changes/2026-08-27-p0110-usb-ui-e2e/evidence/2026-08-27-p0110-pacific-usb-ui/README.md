# P0110 USB UI evidence

Date: 2026-08-27
Base commit: 3b2ba11e832a3618eaedfc67f92414b161423a00
Device: nubia P0110 / pacific / Android 16 / SDK 36
Scope: Android USB live stream and UI/UX owner pass on a general Android
substitute handset.

## Summary

The Android debug build passed testDebugUnitTest, lintDebug, and assembleDebug,
installed on the P0110 device, launched the product Activity, and connected to
a running macOS Host over adb reverse tcp:54321 tcp:54321.

The live run observed Protocol v1 negotiation, three displays from the Host,
HEVC hardware decoding, first frame and first output frame, control capsule
controls, display dropdown, in-place display switch to the external display,
settings, video preference updates, disconnect confirmation, and app relaunch
reconnect.

The macOS Host readiness check was intentionally read-only and reports
status=blocked, so this evidence does not close Host runtime or stable-release
gates.

## Files

| File | Purpose |
| --- | --- |
| [device-baseline.txt](device-baseline.txt) | Sanitized device identity, source commit, display, and battery baseline. |
| [device-fingerprint.txt](device-fingerprint.txt) | Sanitized build fingerprint. |
| [android-gradle-check.txt](android-gradle-check.txt) | Android build, lint, and JVM unit-test summary. |
| [adb-reverse.txt](adb-reverse.txt) | ADB reverse mapping state. |
| [android-launch.txt](android-launch.txt) | Product Activity launch summary. |
| [host-readiness-summary.txt](host-readiness-summary.txt) | Human-readable Host blocker summary. |
| [host-readiness-sanitized.json](host-readiness-sanitized.json) | Machine-readable, sanitized Host readiness subset. |
| [usb-live-smoke-sanitized.json](usb-live-smoke-sanitized.json) | Machine-readable, sanitized USB live-smoke subset. |
| [android-logcat-key-events.txt](android-logcat-key-events.txt) | Filtered Android Protocol v1, decoder, display, preferences, and reconnect events. |
| [ui/](ui) | Sanitized UI hierarchy excerpts for capsule, display picker, settings, video preferences, disconnect confirmation, and final reconnect. |

## Boundary

This bundle intentionally excludes raw screenshots and unfiltered logs. It also
does not include the true Android serial, local user paths, macOS privacy
database paths, or credentials.

The run must be cited as nubia P0110 / pacific / Android 16 / SDK 36 only.
It is not Xiaomi 13/fuxi evidence.
