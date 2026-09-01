# PR493 Android responsive UI review-fix evidence

Date: 2026-09-02
Branch: `codex/recover-android-ui-responsive-20260901`
Base before this fix: `8818895efd4d77d38ac0738d309c8daeb8ff17a9`
Scope: Android client only. This record does not start, install, replace,
copy, re-sign, or validate any macOS Host app, and it does not use `adb reverse`
or Host-connected end-to-end flows.

## What changed

- Top-align the connection content in stacked and width-qualified two-column
  layouts so scrollable content starts at the top instead of being vertically
  centered.
- Let the USB / LAN / Internet mode buttons wrap naturally up to two lines
  without forcing every label to reserve a second line.
- Use a checked-state-specific mode-toggle stroke selector and strengthen the
  `outline_strong` tokens so non-text borders remain visible in light and dark
  themes.
- Add unit/contract coverage for the layout policy, XML mode-button contract,
  and selector contrast checks.

## Offline verification

From `baseline/AndroidClient`:

```bash
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests "dev.telemachus.display.ConnectionPanelLayoutPolicyTest" \
  --tests "dev.telemachus.display.MainActivityTerminalGuidanceContractTest" \
  --tests "dev.telemachus.display.DesignTokenContrastTest"

./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

Both commands completed with `BUILD SUCCESSFUL` during the final local run.

## Android-only device verification

Device: `EP0110PZ0B9110300B`, Nubia P0110. The debug APK was installed with
`adb install -r` only. No Host app was launched or modified.

The matrix captures day/night and font scale 1.0/1.3 for:

- phone portrait on the physical P0110 geometry: `1264x2800`, density `560`
- phone landscape using `wm size 2800x1264`, density `560`
- tablet portrait using `wm size 1600x2560`, density `320`
- tablet landscape using `wm size 2560x1600`, density `320`

The tablet and phone-landscape entries are explicit `wm` override simulations,
not physical tablet hardware or a physical rotation proof.

Primary artifacts:

- Screenshots: `screenshots/*.png` (16 files)
- Per-scenario metadata and successful UI dumps: `metadata/*.txt` and `metadata/*.xml`
- Install log: `logs/install-debug-apk.txt`
- App-only log summary: `logs/logcat-summary.txt`
- Final live device restoration check: `metadata/final-restored-live.txt`

Final restoration state recorded:

- `Physical size: 1264x2800`
- `Physical density: 560`
- `font_scale=1.0`
- `Night mode: no`
- `accelerometer_rotation=0`
- `user_rotation=0`
- `adb reverse --list` empty

## Known boundary

The app attempts the Android-side localhost USB route and logs expected
`ECONNREFUSED` entries because no Host route is allowed in this run. Those logs
do not indicate a crash. Host-connected E2E, long-error Host scenarios,
macOS permissions, TCC, keychain, re-signing, and `/Applications/Vibe Screen.app`
operations were intentionally not run under the current safety constraints.
