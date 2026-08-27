# P0110 USB UI end-to-end owner

Status: current-base Android USB/UI evidence recorded; stable release gates stay open
Date: 2026-08-27
Source branch: codex/p0110-usb-ui-e2e
Evidence collection base commit: 3b2ba11e832a3618eaedfc67f92414b161423a00
Current PR base after refresh: 27d2b0e493e807ae439fbd43b06b4c2f0ce9c503
  (origin/main)

## Scope

This record owns a current-base Android real-device pass for the README-facing
USB streaming and UI/UX paths on the connected substitute Android handset. It
covers the Android client build/install path, ADB reverse USB connection,
Protocol v1 streaming, display picker and in-place display switch, settings,
video quality/FPS/bitrate controls, disconnect confirmation, and force-stop /
relaunch reconnect behavior.

The retained device identity is exactly nubia P0110 / pacific / Android 16 /
SDK 36. This evidence is a general Android substitute-device record only and
must not be relabeled as Xiaomi 13/fuxi evidence.

## Non-goals

- Do not claim Phase 0 stable release readiness from this run.
- Do not close the macOS Host current-source stable-signing, TCC, virtual HID,
  login/headless, or Host RSS gates.
- Do not claim two-hour soak, latency, native HID mouse, physical stylus,
  controller, trusted-LAN, Internet, or Xiaomi/fuxi device acceptance.
- Do not publish raw screenshots or private raw logs from the local run.

## Evidence

The public, sanitized evidence bundle is
[evidence/2026-08-27-p0110-pacific-usb-ui](evidence/2026-08-27-p0110-pacific-usb-ui/README.md).

The private raw evidence used to prepare the bundle remains outside git. Public
files intentionally contain only summarized or filtered logs and UI hierarchy
snippets after removing local paths, real device serials, and macOS privacy
database details.

The PR branch has since been refreshed onto a newer origin/main at
`27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`. That refresh did not rerun the
device session and does not change the committed evidence bundle's recorded
collection base.

## Result

No product or UI defect requiring a code change was found in the validated
paths. The observed disconnect-control automation miss was caused by stale
coordinates after the control capsule auto-hidden or shifted width after display
selection; dynamically reading the current UI hierarchy and tapping the current
button bounds produced the expected confirmation dialog.

The run records a useful current-base USB/UI pass for P0110, but the README
stable-release and hardware-specific gates remain bounded by the open items in
[TEST.md](TEST.md).
