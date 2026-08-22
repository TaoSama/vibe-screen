# Nubia P0110 peripheral gates current-base preflight

Created: 2026-08-23

Base commit: de2752e0033713ad48bb7f86960f9180d8e7342f

Device: nubia P0110 / pacific / Android 16 / SDK 36 / serial
EP0110PZ0B9110300B

This evidence directory is a read-only snapshot of the currently connected
Nubia P0110/pacific for the native pointer HID, controller runtime, and physical
stylus drawing-app gates. It does not claim a pass for any physical peripheral
gate.

## Summary

| Gate | Evidence bundle | Result |
| --- | --- | --- |
| Native pointer HID | native-pointer-hid/ | blocked: no external mouse, relative mouse, touchpad, or trackball source attached. |
| Controller runtime | controller-runtime-readiness/ | blocked: no physical gamepad/joystick; Host is not Apple identity-signed with the virtual HID entitlement; no Host virtual-gamepad availability. |
| Physical stylus drawing-app | physical-stylus/ | blocked_physical_stylus_not_observed: goodix_stylus_input is pass-eligible at capability level, but no physical drawing-app observation was captured. |

## Raw inventory

The raw-adb/ directory contains only read-only ADB outputs collected with adb -s
EP0110PZ0B9110300B. Important files:

- preflight-context.txt: timestamp, repo head, branch, and the zero-byte Android
  device lock with no lsof owner.
- adb-devices-l.txt and getprop-* files: device identity.
- dumpsys-input.txt: Android input devices and sources.
- getevent-lp.txt: kernel input device capabilities.
- getevent-event7-5s.txt: five-second read of /dev/input/event7, which timed
  out with no stylus event lines.
- settings-input-filtered.txt: filtered input-related Android settings.

## Gate decision

Keep all three gates open. Current P0110 hardware readiness is useful for the
stylus gate because goodix_stylus_input exposes STYLUS plus pressure and tilt,
but this is not a physical drawing-app result. Current P0110 state is not ready
for native pointer or controller runtime because no external mouse-like source
and no external gamepad/joystick source are visible.
