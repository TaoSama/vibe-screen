# PR493 Android Mode Toggle Device Evidence

Final evidence uses this debug APK:

    076333b301475dfe3d949eab3c80f626053f3b68e95e500c4a8911ad669d4a87  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
    0f2c36d433dc855f3b8b1407ba984887894f90025954963eded29d8aa66536b9  baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk

Device:

- Serial: `<redacted-adb-serial>`
- Manufacturer: `nubia`
- Model: `P0110`
- Codename: `pacific`
- Android: `16` / API `36`
- Physical size: `1264x2800`
- Physical density: `560`

## Final Device Matrix

Directory: `final-076333b-real-rotation-matrix/`

The final matrix contains eight Android-only captures from the installed APK. All eight scenarios passed screenshot and system-state validation. Portrait captures are `1264x2800` with `mDisplayRotation=ROTATION_0` and `port`. Landscape captures are real system-rotation captures at `2800x1264` with `cmd window user-rotation: lock 1`, `mDisplayRotation=ROTATION_90`, and `land`. No display-size override was used for this final matrix.

| Scenario | Screenshot | State | XML |
| --- | --- | --- | --- |
| Portrait, day, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-day-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-day-font1.state-after.txt` | present |
| Portrait, night, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-night-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-night-font1.state-after.txt` | present |
| Portrait, day, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-day-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-day-font13.state-after.txt` | unavailable |
| Portrait, night, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-portrait-night-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-portrait-night-font13.state-after.txt` | unavailable |
| Landscape, day, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-day-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-day-font1.state-after.txt` | unavailable |
| Landscape, night, font scale 1.0 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-night-font1.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-night-font1.state-after.txt` | unavailable |
| Landscape, day, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-day-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-day-font13.state-after.txt` | unavailable |
| Landscape, night, font scale 1.3 | `final-076333b-real-rotation-matrix/screenshots/phone-landscape-night-font13.png` | `final-076333b-real-rotation-matrix/metadata/phone-landscape-night-font13.state-after.txt` | unavailable |

`final-076333b-real-rotation-matrix/metadata/validation.json` and `final-076333b-real-rotation-matrix/metadata/final-validation-summary.txt` record the 8/8 `png_ok=true` and `state_ok=true` result. The validation metadata records the device as `nubia`/`P0110`/`pacific` on Android `16` / API `36`, with the ADB serial redacted. The semantic XML coverage gate requires at least two `present` XML captures and specifically requires the two default portrait scenarios, `phone-portrait-day-font1` and `phone-portrait-night-font1`; this retained evidence satisfies that gate only under `semantic_minimum_only_not_stable_state` scope.
The validation metadata was rebuilt offline from the existing screenshots, state files, XML files, install logs, instrumentation log, the recorded app APK SHA-256, and the locally computed androidTest APK SHA-256 after the collector script was hardened. No device recapture or ADB command was run for that metadata rebuild. A later Android-only cleanup recheck then reverified `restored.packages_stopped=true` without launching Host, GUI, product binaries, or mutating adb reverse state.

## Current-Source No-Host Stable XML Attempt

Directory: `no-host-stable-current-source-20260905/`

This Android-only follow-up was collected from then-current `origin/main` source
revision `3c97f98f21e8bc2a58f44a0a1e586f78cb874e89` using an APK with SHA-256
`e7dc02b7655cd6548f838c07ce0402559c9777e2b27c631a0f6f8e0f3856b25f`. The app
was launched with `--ez auto_connect false` for each scenario so the default USB
screen stayed in a no-Host disconnected state rather than entering automatic
retry. Device identity is retained as `nubia` / `P0110` / `pacific` / Android
`16` / SDK `36`, with the ADB serial redacted.

This run overlaps in time with another no-Host Android task using the same
physical device, so it is retained as bounded supplemental evidence rather than
an 8/8 replacement matrix. The self-consistent stable XML captures are:

| Scenario | Screenshot | XML | Result |
| --- | --- | --- | --- |
| Portrait, day, font scale 1.0 | `no-host-stable-current-source-20260905/screenshots/phone-portrait-day-font1.png` | `no-host-stable-current-source-20260905/metadata/phone-portrait-day-font1.xml` | stable XML, screenshot size, and state all pass |
| Portrait, night, font scale 1.0 | `no-host-stable-current-source-20260905/screenshots/phone-portrait-night-font1.png` | `no-host-stable-current-source-20260905/metadata/phone-portrait-night-font1.xml` | stable XML, screenshot size, and state all pass |
| Portrait, day, font scale 1.3 | `no-host-stable-current-source-20260905/screenshots/phone-portrait-day-font13.png` | `no-host-stable-current-source-20260905/metadata/phone-portrait-day-font13.xml` | stable XML, screenshot size, and state all pass |
| Portrait, night, font scale 1.3 | `no-host-stable-current-source-20260905/screenshots/phone-portrait-night-font13.png` | `no-host-stable-current-source-20260905/metadata/phone-portrait-night-font13.xml` | stable XML, screenshot size, and state all pass |
| Landscape, night, font scale 1.0 | `no-host-stable-current-source-20260905/screenshots/phone-landscape-night-font1.png` | `no-host-stable-current-source-20260905/metadata/phone-landscape-night-font1.xml` | stable XML, screenshot size, and state all pass |
| Landscape, night, font scale 1.3 | `no-host-stable-current-source-20260905/screenshots/phone-landscape-night-font13.png` | `no-host-stable-current-source-20260905/metadata/phone-landscape-night-font13.xml` | stable XML, screenshot size, and state all pass |

The two landscape/day attempts are not used as passing evidence.
`phone-landscape-day-font1` was captured before Android reported the requested
landscape state, and `phone-landscape-day-font13` did not produce stable XML.
Because of the concurrent device use, no additional device-mutating commands
were run to recapture those two scenarios.

The retained current-source XML files demonstrate the steady disconnected USB
semantic state: `modeUSB` checked, `modeWireless` and `modeInternet` unchecked,
`Waiting for your Mac`, USB-ready guidance, `CONNECT`, `Looking for Vibe Screen
on your Mac`, and `DISPLAY SETTINGS`, with `connectionProgress` absent from the
accessible bounds. This evidence does not close Android/macOS product E2E, Host
readiness, streaming, latency, clipboard, or file-transfer gates.

## Guardrails

- `final-076333b-real-rotation-matrix/metadata/adb-reverse-before.txt`, `adb-reverse-after.txt`, and `adb-reverse-final.txt` are empty.
- `final-076333b-real-rotation-matrix/metadata/device-identity.txt` records independent read-only `adb devices` and `adb shell getprop` evidence for manufacturer `nubia`, model `P0110`, codename `pacific`, Android release `16`, API `36`, and a redacted ADB serial.
- `final-076333b-real-rotation-matrix/metadata/device-manufacturer.txt`, `device-model.txt`, `device-codename.txt`, `android-version.txt`, and `android-api.txt` record the individual identity values used by the collector contract.
- `final-076333b-real-rotation-matrix/metadata/apk-sha256.txt` and `androidTest-apk-sha256.txt` record the app and instrumentation APK provenance.
- The scenario state files record physical dimensions only; the final matrix has no `Override size` entries.
- The final restore state is recorded at `final-076333b-real-rotation-matrix/metadata/final-restored.state-after.txt` and confirms `font_scale: 1.0`, `Night mode: Night mode: no`, `cmd window user-rotation: lock 0`, `accelerometer_rotation: 0`, `user_rotation: 0`, and `mDisplayRotation=ROTATION_0`.
- Post-restore package stop was not reverified in the original offline metadata rebuild because that retained run did not persist `pidof` output. The Android-only cleanup recheck in `20260902-continued-cleanup.pidof-after-force-stop.txt` now records empty `pidof` output for `dev.telemachus.display` and `dev.telemachus.display.test` after force-stop, so `restored.packages_stopped=true` is backed by retained runtime evidence.
- New runs of `collect_final_matrix.py` now record `metadata/android-instrumentation-cleanup.json` after instrumentation completes or fails. That cleanup force-stops and uninstalls only `dev.telemachus.display.test`, verifies `pm list packages dev.telemachus.display.test` is empty, and records that the cleanup command set does not target the product package, product data, or ADB reverse state. A Nubia cross-package prompt that names the `.test` package is therefore Android instrumentation residue, not macOS Screen Recording or Accessibility/TCC rollback evidence.
- `20260902-continued-cleanup.adb-reverse-before.txt` and `20260902-continued-cleanup.adb-reverse-after.txt` show adb reverse state was read before and after the cleanup recheck and remained empty. No adb reverse entry was created or modified.
- `20260902-continued-cleanup.device-state-before.txt` and `20260902-continued-cleanup.device-state-after.txt` record unchanged restored Android state: physical size `1264x2800`, physical density `560`, font scale `1.0`, night mode `no`, user rotation `lock 0`, `accelerometer_rotation=0`, and `user_rotation=0`.

## XML Boundary

The two available XML files are the minimum semantic XML coverage for this retained matrix. They cover the default portrait day and night cases, show USB selected, LAN and Internet unselected, `TRY AGAIN` before the diagnostic content, and the USB unavailable guidance text. They are explicitly retained as `semantic_minimum_only_not_stable_state` evidence: both portrait XML files show the `connectionProgress` spinner bounds alongside the `TRY AGAIN` button and `USB route unavailable` error text, so they capture a transient mixed frame rather than a stable post-fix spinner state. The stable eight-scenario matrix claim comes from screenshots and state-after files, not from treating these XML files as new spinner steady-state evidence. Future live captures fail if fewer than two XML files validate, either default portrait XML is missing, any captured XML is rejected, or a present XML omits its `xml_stable_state` marker.

The other six hierarchy captures are intentionally unavailable because `uiautomator` returned `ERROR: could not get idle state.` Their `*.pull-xml.txt` files record `dump invalid; not pulling XML`, and no stale XML file was reused.

Screenshots plus state-after metadata remain the primary evidence for all eight scenarios. Auxiliary state-before, PNG pull, screencap, uiautomator stdout/stderr, remote XML listing, launch, and collector run logs were pruned from the retained bundle; the `*.pull-xml.txt` files are kept because they document the XML-unavailable boundary without retaining stale XML.
