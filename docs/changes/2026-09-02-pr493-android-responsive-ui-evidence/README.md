# PR 493 Android responsive UI evidence

This directory captures the local Android client validation for the PR 493 responsive connection UI cleanup.

## Build and test coverage

- Focused unit tests passed: `:app:testDebugUnitTest` with `ConnectionPanelLayoutPolicyTest`, `StatusOverlayLayoutPolicyTest`, and `MainActivityTerminalGuidanceContractTest`.
- Full offline validation passed: `:transport:check :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest`.
- Final targeted validation after the last source edit passed: focused unit tests, `:app:lintDebug`, and `:app:assembleDebug`.

## Device and install coverage

- Device: `<redacted-adb-serial>` (`P0110`, Android device `pacific`).
- APK install evidence: `after/logs/install.txt` shows `Performing Streamed Install` followed by `Success`.
- Host app was intentionally not started or installed, and no `adb reverse` rule was configured.
- App-only log summary: `after/logs/logcat-app-summary.txt`. The observed `StreamClient` `ECONNREFUSED` entries are expected for this no-host, no-reverse validation pass.

## Screenshot matrix

Use these screenshots as the validated after-state matrix:

- `after/matrix/phone-portrait-day-font1.png`
- `after/matrix/phone-portrait-night-font13-long-error.png`
- `after/matrix/phone-landscape-day-font1-recaptured.png`
- `after/matrix/phone-landscape-night-font13-recaptured.png`
- `after/matrix/tablet-portrait-day-font1-clean.png`
- `after/matrix/tablet-portrait-night-font13-long-error.png`
- `after/matrix/tablet-landscape-day-font1.png`
- `after/matrix/tablet-landscape-night-font13.png`

The phone-landscape, tablet-portrait, and tablet-landscape entries in this
directory are `wm size` simulations on the physical P0110 device, with
tablet-landscape additionally using `user_rotation=1`. They are useful layout
coverage, but they are not physical tablet hardware evidence or the real
rotation proof used by the final mode-toggle matrix.

The same-named files under `after/metadata/` record the screen size, density, font scale, night mode, rotation, `adb reverse --list`, focused activity, and window frame for each screenshot.

## Baseline evidence

- `baseline/device-baseline.txt` records the initial physical device state.
- `baseline/pr-head-portrait-day-font1.png` and `baseline/pr-head-portrait-day-font1.dumpsys-window.txt` capture the starting PR-head portrait baseline before the final responsive layout changes.

## Excluded evidence

These files were generated during capture but are intentionally not part of the curated evidence set:

- `after/logs/logcat-tail.txt` and `after/logs/logcat-summary.txt`: raw device logcat output includes unrelated apps and noisy telemetry.
- `after/matrix/phone-landscape-day-font1.png` and `after/matrix/phone-landscape-night-font13.png`: superseded by the `*-recaptured.png` landscape screenshots.
- `after/matrix/tablet-portrait-day-font1.png` and `after/matrix/tablet-portrait-day-font1-recaptured.png`: superseded by `tablet-portrait-day-font1-clean.png` after a system dialog was cleared.

## Final restored device state

The final device restoration is recorded in `after/metadata/final-clean-restored.txt` and `after/metadata/final-restored-after-tablet-day-recapture.txt`:

- `wm size`: `Physical size: 1264x2800`
- `wm density`: `Physical density: 560`
- `font_scale`: `1.0`
- Night mode: `no`
- `user_rotation`: `0`
- `accelerometer_rotation`: `0`
- `adb reverse --list`: empty

## UIAutomator limitation

Several UIAutomator hierarchy captures failed with `ERROR: could not get idle state.` The evidence set therefore relies on screenshots plus `dumpsys window` and metadata files for the visual matrix.
