# P0110 Android UI polish smoke

Date: 2026-08-20

PR: [#141](https://github.com/TaoSama/vibe-screen/pull/141)
Code commit: `ae7d5c2d1067577b09dff55fcb1c3fb350232923`
Debug APK SHA-256:
`606ffbc1990bdc0adfc36c4a21f8f206d5debd93b49785866062bfa7274e25f7`

Device identity:

```text
nubia
P0110
pacific
16
36
```

This is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13 / fuxi evidence.

## Scope

The debug APK built from PR #141 after the reveal-only gesture pointer-input fix
installed and launched on the connected P0110. The retained screenshots show the
stream surface UI before and after an ADB tap near the top control-reveal region:

- [`initial.png`](initial.png)
- [`after-top-tap.png`](after-top-tap.png)
- [`diff-thumb.png`](diff-thumb.png)

The launch reported `Status: ok`, `LaunchState: COLD`, and `TotalTime: 445` ms.
The app kept focus as `dev.telemachus.display/.MainActivity` before and after the
tap. The two screenshots are both `1264x2800` PNGs and differ by 1913 pixels in an
absolute-error image comparison. That proves the app was visible and the smoke
step produced a small rendered-state change, but it is intentionally treated as
weak UI smoke evidence rather than a full interaction acceptance run.

## Local validation

```bash
cd baseline/AndroidClient
./gradlew :app:testDebugUnitTest \
  --tests dev.telemachus.display.DisplayCapsulePolicyTest \
  --tests dev.telemachus.display.ControlBarAccessibilityPolicyTest \
  --tests dev.telemachus.display.ControlRevealGesturePolicyTest
./gradlew :app:assembleDebug
cd ../..
git diff --check
adb -s EP0110PZ0B9110300B install -r -t baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B shell am start -W -S -n dev.telemachus.display/.MainActivity --ez auto_connect false
adb -s EP0110PZ0B9110300B exec-out screencap -p > initial.png
adb -s EP0110PZ0B9110300B shell input tap 632 170
adb -s EP0110PZ0B9110300B exec-out screencap -p > after-top-tap.png
```

## Not proved

This record does not prove:

- an active Mac stream;
- display switching;
- video preference renegotiation;
- reconnect behavior;
- that tapping the hidden control region avoids forwarding a Mac touch event;
- full control-bar accessibility or menu interaction;
- any Xiaomi 13 / fuxi behavior.

Those gates require a connected Host session with retained Host/client logs or a
dedicated end-to-end device run.
