# PR493 Android UI Device Evidence

Final evidence uses the debug APK at:

    1429c213396d42b452abfa53bc0d109c6e45ffd8fbbb14b7172d37bc8623b98a  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk

Device:

- Serial: EP0110PZ0B9110300B
- Model: P0110
- Android: 16
- Physical size: 1264x2800
- Physical density: 560

Install result:

    Performing Streamed Install
    Success

ADB reverse guard:

- final-1429c21-real-rotation-matrix/metadata/adb-reverse-before.txt: empty
- final-1429c21-real-rotation-matrix/metadata/adb-reverse-after.txt: empty
- final-1429c21-real-rotation-matrix/metadata/adb-reverse-final.txt: empty

## Final Device Matrix

Directory: final-1429c21-real-rotation-matrix/

The final matrix contains eight Android-only captures from the installed APK. Portrait captures are 1264x2800 with mDisplayRotation=ROTATION_0 and port. Landscape captures are real system-rotation captures at 2800x1264 with cmd window user-rotation: lock 1, mDisplayRotation=ROTATION_90, and land. No display-size override was used for the landscape evidence.

| Scenario | Screenshot | State |
| --- | --- | --- |
| Portrait, day, font scale 1.0 | final-1429c21-real-rotation-matrix/screenshots/phone-portrait-day-font1.png | final-1429c21-real-rotation-matrix/metadata/phone-portrait-day-font1.state-after.txt |
| Portrait, night, font scale 1.0 | final-1429c21-real-rotation-matrix/screenshots/phone-portrait-night-font1.png | final-1429c21-real-rotation-matrix/metadata/phone-portrait-night-font1.state-after.txt |
| Portrait, day, font scale 1.3 | final-1429c21-real-rotation-matrix/screenshots/phone-portrait-day-font13.png | final-1429c21-real-rotation-matrix/metadata/phone-portrait-day-font13.state-after.txt |
| Portrait, night, font scale 1.3 | final-1429c21-real-rotation-matrix/screenshots/phone-portrait-night-font13.png | final-1429c21-real-rotation-matrix/metadata/phone-portrait-night-font13.state-after.txt |
| Landscape, day, font scale 1.0 | final-1429c21-real-rotation-matrix/screenshots/phone-landscape-day-font1.png | final-1429c21-real-rotation-matrix/metadata/phone-landscape-day-font1.state-after.txt |
| Landscape, night, font scale 1.0 | final-1429c21-real-rotation-matrix/screenshots/phone-landscape-night-font1.png | final-1429c21-real-rotation-matrix/metadata/phone-landscape-night-font1.state-after.txt |
| Landscape, day, font scale 1.3 | final-1429c21-real-rotation-matrix/screenshots/phone-landscape-day-font13.png | final-1429c21-real-rotation-matrix/metadata/phone-landscape-day-font13.state-after.txt |
| Landscape, night, font scale 1.3 | final-1429c21-real-rotation-matrix/screenshots/phone-landscape-night-font13.png | final-1429c21-real-rotation-matrix/metadata/phone-landscape-night-font13.state-after.txt |

Visual result:

- Default font scale 1.0 keeps the segmented control horizontal; USB, LAN, and Internet are not truncated.
- Large font scale 1.3 stacks the mode buttons vertically in portrait; USB, LAN, and Internet are not truncated.
- Landscape keeps the mode buttons horizontal; USB, LAN, and Internet are not truncated.
- TRY AGAIN appears before the diagnostic checklist and is visible in all eight captures.
- Wide landscape keeps the settings entry inline, so no floating settings button covers the primary retry action.
- Wide landscape uses compact header spacing so the header guidance and retry action are both visible at font scale 1.3.

## Device Restore

The final restore state is recorded at final-1429c21-real-rotation-matrix/metadata/final-restored.state-after.txt and confirms:

    Physical size: 1264x2800
    Physical density: 560
    font_scale: 1.0
    Night mode: no
    user_rotation: 0
    mDisplayRotation=ROTATION_0
    mRotation=ROTATION_0

## Auxiliary Metadata

Each scenario also includes:

- *.am-start.txt with Status: ok and Activity: dev.telemachus.display/.MainActivity
- *.pull-png.txt for screenshot pull results
- *.xml, *.pull-xml.txt, and *.uiautomator.*.txt as auxiliary UI hierarchy evidence
- metadata/final-validation-summary.txt with screenshot timestamps, dimensions, touch-target source lines, and the source order proving connectButton appears before checklistContainer

uiautomator reported ERROR: could not get idle state. while still writing bounded XML hierarchy files. The PNG captures and state files are the primary visual and rotation evidence.

## Intermediate Evidence

Other sibling directories in this folder are earlier captures kept for audit history. Use only final-1429c21-real-rotation-matrix/ for final PR493 device evidence.
