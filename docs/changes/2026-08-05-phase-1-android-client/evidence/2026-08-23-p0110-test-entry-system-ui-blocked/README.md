# P0110 Android visual UI E2E: system UI blocked

Status: blocked before reaching the product surface. Gate closed: false.

This record classifies a read-only Android visual/UI E2E sampling result from
the connected Nubia device. The sample was provided by a controller-side
read-only check and retained under `${EVIDENCE_DIR}`.

## Device

- Serial: EP0110PZ0B9110300B
- Manufacturer: nubia
- Model: P0110
- Device/codename: pacific
- Android: 16
- SDK: 36

This is Nubia P0110 / pacific evidence only. It must not be relabeled as
Xiaomi 13 / fuxi evidence.

## Sample

Retained inputs:

- `${EVIDENCE_DIR}/state.txt` copied from the run-specific state sample
- `${EVIDENCE_DIR}/screenshots/current.png` copied from the run-specific screenshot
- `${EVIDENCE_DIR}/android-test-lock.txt` copied from the test-specific lock snapshot

The copied screenshot is a 1264x2800 PNG with SHA-256
acdaee7e6af88c615df8d15747bac4f20349bc2eefad6c207bd7dd8d67476588.
The copied state file has SHA-256
80beb79e3d01e107b7826ab63648904757be689b296589f7a3091e2ae50e283d.

The state sample reported:

```text
focus:
  mCurrentFocus=Window{de91c2e u0 com.android.permissioncontroller/com.android.permissioncontroller.permissionplus.ui.InterceptJumpDialogActivity}
  mFocusedApp=ActivityRecord{1507543 u0 com.android.permissioncontroller/.permissionplus.ui.InterceptJumpDialogActivity t569}
packages:
package:dev.telemachus.display
package:dev.telemachus.display.test
```

The screenshot shows an Android/firmware system confirmation dialog, not the
Vibe Screen product UI. The visible prompt asks whether Vibe Screen should open
dev.telemachus.display.test, with Cancel and Open actions shown in Chinese. The
background is the launcher with the Vibe Screen icon, so the E2E entry point was
intercepted before the product surface appeared.

## Classification

Classification: external_system_ui_test_entry_blocker.

This is a system permission-controller / jump-interception prompt affecting the
test package entry path. It is not evidence of a Vibe Screen product UI
regression and does not call for a product-code change by itself.

The appropriate mitigation is in the test harness or runbook: pre-acknowledge
or bypass this device-specific confirmation before visual/UI E2E starts, or
record this exact permissioncontroller Activity as an external system UI
blocker when it appears. A later passing visual/UI E2E run still needs to reach
dev.telemachus.display/.MainActivity or the intended app/test surface and retain
screenshots or UI dumps from that surface.

## Evidence Boundary

No device command was executed by this classification step. It reused the
provided read-only sample and therefore did not create or remove ADB reverse
mappings, install packages, launch the app, clear logs, inject input, or touch
the main Android device coordination lock.

This record does not close any README acceptance gate, including USB/LAN
streaming, connected control capsule behavior, display dropdown confirmation,
display switching, latency, soak stability, Host RSS no-growth, native-pointer
HID, stylus, controller, rotated host-display, tablet productization, iOS, or
HarmonyOS.
