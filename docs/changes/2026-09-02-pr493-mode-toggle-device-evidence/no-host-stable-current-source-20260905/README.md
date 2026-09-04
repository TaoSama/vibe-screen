# PR493 Current-Source No-Host Bounded Stable XML Attempt

Date: 2026-09-05

Branch: codex/android-uiux-no-host-matrix-20260905

Then-current source revision: 3c97f98f21e8bc2a58f44a0a1e586f78cb874e89

Device: Nubia P0110 / pacific / Android 16 / SDK 36 / serial
<redacted-adb-serial>.

## Scope

This is Android-client UI/UX evidence only. The app was launched with
--ez auto_connect false for each scenario so the USB disconnected page stayed
in the no-Host idle state. No macOS Host binary was launched, no Screen
Recording or Accessibility/TCC path was exercised, and no product adb reverse
tcp:54321 tcp:54321 mapping was created, modified, or deleted.

This collection overlapped in time with another no-Host Android task using the
same physical device. For that reason this directory is retained as a bounded
current-source attempt, not as a replacement for the final 8/8 PR493 matrix. The
scenario table below marks exactly which captures are self-consistent and
usable as stable XML evidence.

## Result

| Scenario | Screenshot | XML | Result |
| --- | --- | --- | --- |
| Portrait, day, font scale 1.0 | screenshots/phone-portrait-day-font1.png | metadata/phone-portrait-day-font1.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |
| Portrait, night, font scale 1.0 | screenshots/phone-portrait-night-font1.png | metadata/phone-portrait-night-font1.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |
| Portrait, day, font scale 1.3 | screenshots/phone-portrait-day-font13.png | metadata/phone-portrait-day-font13.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |
| Portrait, night, font scale 1.3 | screenshots/phone-portrait-night-font13.png | metadata/phone-portrait-night-font13.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |
| Landscape, day, font scale 1.0 | screenshots/phone-landscape-day-font1.png | metadata/phone-landscape-day-font1.xml | NOT USED: captured before Android reached the requested landscape state |
| Landscape, night, font scale 1.0 | screenshots/phone-landscape-night-font1.png | metadata/phone-landscape-night-font1.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |
| Landscape, day, font scale 1.3 | screenshots/phone-landscape-day-font13.png | not present | NOT USED: captured before Android reached the requested landscape state and no stable semantic XML was captured |
| Landscape, night, font scale 1.3 | screenshots/phone-landscape-night-font13.png | metadata/phone-landscape-night-font13.xml | PASS: screenshot size, Android state, semantic XML, and xml_stable_state=true |

The six PASS rows show the stable no-Host USB disconnected semantics: modeUSB
checked, modeWireless and modeInternet unchecked, Waiting for your Mac,
USB-ready guidance, CONNECT, Looking for Vibe Screen on your Mac, and DISPLAY
SETTINGS, with no connectionProgress visible in accessibility XML.

## Guardrails

- metadata/adb-reverse-before.txt and metadata/adb-reverse-after.txt show no
  tcp:54321 product reverse mapping. They retain the unrelated existing UsbFfs
  tcp:8908 tcp:8908 entry.
- metadata/device-identity.txt records Nubia P0110 / pacific / Android 16 /
  SDK 36 identity with the serial redacted.
- metadata/validation.json and metadata/final-validation-summary.txt retain
  per-scenario png_ok, state_ok, xml_status, xml_errors, and xml_stable_state
  values.
- SHA256SUMS records checksums for every retained evidence file in this
  directory.
- The raw metadata/*.pull-xml.txt attempt transcripts retain the collector
  result labels from capture time. The repository collector was hardened after
  this run to separate semantic XML failures from unstable disconnected-state
  XML and now validates the retained no-Host idle XML with the current text
  anchors.
- The device was restored to font scale 1.0, day mode, portrait rotation, and
  app force-stopped before this collection stopped issuing device-mutating ADB
  commands.

## Not Proven

This evidence does not prove Android/macOS product E2E behavior, Host readiness,
streaming, latency, clipboard transfer, file transfer, Protocol v1 negotiation,
USB/LAN transport readiness, public Internet traversal, or Xiaomi 13/fuxi
behavior.
