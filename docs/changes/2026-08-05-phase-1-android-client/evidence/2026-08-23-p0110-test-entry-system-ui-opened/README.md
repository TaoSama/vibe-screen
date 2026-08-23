# P0110 Android visual UI E2E: system UI intercept handled

Status: test-entry system UI confirmed and bypassed to the product surface.
Gate closed: false.

This record follows the controller-side read-only sample captured under
`${EVIDENCE_DIR}`. The connected device was a Nubia P0110 / pacific running
Android 16 / SDK 36. All device-affecting ADB commands in this follow-up used
explicit serial targeting with `adb -s "$ADB_SERIAL"`, where
`ADB_SERIAL="${ANDROID_SERIAL}"`.

## Device

- Serial: EP0110PZ0B9110300B
- Manufacturer: nubia
- Model: P0110
- Device/codename: pacific
- Android: 16
- SDK: 36

This is Nubia P0110 / pacific evidence only. It must not be relabeled as
Xiaomi 13 / fuxi evidence.

## Starting State

The read-only sample and the first leased check both showed the foreground
Activity was not Vibe Screen:

```text
com.android.permissioncontroller/.permissionplus.ui.InterceptJumpDialogActivity
```

The retained screenshot `${EVIDENCE_DIR}/screenshots/before-open.png` shows a system
permission-controller confirmation asking whether Vibe Screen should open
`dev.telemachus.display.test`, with Chinese Cancel/Open actions. The stale
test-specific lock recorded from the run environment contained `pre-existing
lock` and is retained in `${EVIDENCE_DIR}/android-test-lock.txt`.

## Handling

This task acquired the Android coordination lock before touching the device and
released it after each bounded sample. No soak lock was present. For repeatable
runs, use variables rather than baking local paths or serials into procedure
text:

```bash
REPO=/path/to/vibe-screen
EVIDENCE_DIR="${REPO}/docs/changes/2026-08-05-phase-1-android-client/evidence/<run-id>"
ANDROID_SERIAL=<android-device-serial>
ADB_SERIAL="${ANDROID_SERIAL}"
ANDROID_LOCK=<android-coordination-lock>
SOAK_LOCK=<soak-coordination-lock>
```

The first tap used an incorrect y coordinate and did not activate the positive
button; window-after-open.xml retained the exact system button bounds:

```text
com.android.permissioncontroller:id/actionPositive text="打开" bounds="[653,2548][1180,2716]"
```

The second tap targeted the positive button center. After that tap, the focused
Activity changed to the test package empty instrumentation Activity:

```text
dev.telemachus.display.test/androidx.test.core.app.InstrumentationActivityInvoker$EmptyActivity
```

That confirms the blocker is a system confirmation for the test package entry
path, not a Vibe Screen product UI state.

Finally, the product Activity was launched directly with this reusable command
shape:

```bash
adb -s "$ADB_SERIAL" shell am start -n dev.telemachus.display/.MainActivity
```

After direct launch, the foreground changed to:

```text
dev.telemachus.display/dev.telemachus.display.MainActivity
```

The retained window-after-main-launch.xml shows the product UI reached the
Internet development preview surface, including the Vibe Screen wordmark,
USB/LAN/INTERNET mode toggles, route policy controls, scan/import actions, and
the disabled CONNECT PREVIEW button because no Internet pairing profile was
present.

## Classification

Classification: external_system_ui_test_entry_blocker.

This does not require a Vibe Screen product-code change. The appropriate fix is
in the visual/UI E2E harness or runbook: detect
`com.android.permissioncontroller/.permissionplus.ui.InterceptJumpDialogActivity`
when it asks to open `dev.telemachus.display.test`, tap the positive action by
resource id or bounds, then explicitly launch the product Activity intended for
the visual check with `adb -s "$ADB_SERIAL"`. If the dialog persists or the
product Activity cannot be launched afterward, keep the run blocked as external
system UI evidence.

## Evidence Boundary

This record proves only the test-entry blocker classification and the minimal
device-side workaround for reaching the product Activity. It does not run an
instrumentation suite, validate a real Mac Host stream, connected control
capsule behavior, display dropdown confirmation, display switching, LAN
stream/reconnect, latency, soak stability, Host RSS no-growth, native-pointer
HID, stylus, controller, rotated host-display, tablet productization, iOS, or
HarmonyOS.
