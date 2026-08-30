# P0110 Android visual UI E2E: launcher idle state

Status: read-only device state update. Gate closed: false.

This record preserves a controller-side read-only Android state sample from the
run-specific evidence directory. No device command was run by this
classification step.

## Device

- Serial: <redacted-adb-serial>
- Manufacturer: nubia
- Model: P0110
- Device/codename: pacific
- Android: 16
- SDK: 36

This is Nubia P0110 / pacific evidence only. It must not be relabeled as
Xiaomi 13 / fuxi evidence.

## State

The retained state sample reported:

```text
time=2026-08-23T08:09:22+08:00
adb_state=device
manufacturer=nubia
model=P0110
device=pacific
android=16
sdk=36
foreground=com.android.launcher3/com.obric.feature.ObricLauncher
locks=/tmp/vibe-screen-device-android-test.lock
```

The retained screenshot screenshots/current.png shows the Nubia launcher rather
than the earlier system permission-controller confirmation. This means the
device is no longer visibly blocked on
com.android.permissioncontroller/.permissionplus.ui.InterceptJumpDialogActivity,
but it also is not on the Vibe Screen product surface.

The stale test-specific lock recorded from the run environment still existed
with content `pre-existing lock` and is retained in `android-test-lock.txt`. The
main Android coordination lock and soak lock were absent at the time this
record was prepared.

## Classification

Classification: launcher_idle_ready_for_next_leased_ui_step.

This state does not require a Vibe Screen product-code change. A future
visual/UI E2E run should set `REPO`, `EVIDENCE_DIR`, `ANDROID_SERIAL`,
`ADB_SERIAL="${ANDROID_SERIAL}"`, and the coordination-lock path variables,
acquire the Android coordination lock, then explicitly launch the intended
product or test Activity with `adb -s "$ADB_SERIAL"` before judging product UI.
If the system permission-controller confirmation appears again while opening the
test package, use the existing test-entry workaround record for that blocker.

## Evidence Boundary

This record only documents the current launcher foreground state and device
identity. It does not prove app startup, instrumentation execution, a real Mac
Host stream, connected control capsule behavior, display dropdown confirmation,
display switching, LAN stream/reconnect, latency, soak stability, Host RSS
no-growth, native-pointer HID, stylus, controller, rotated host-display, tablet
productization, iOS, or HarmonyOS.
