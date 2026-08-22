# Peripheral gates current-base preflight

Date: 2026-08-23

## Scope

This record is a current-base, read-only preflight for the three physical
peripheral gates that remain open in README.md:

- native pointer HID mouse move/click;
- controller runtime acceptance;
- physical stylus drawing-app confirmation.

The run used the connected Android device explicitly as adb -s
EP0110PZ0B9110300B. The device identified as nubia P0110 / pacific / Android 16
/ SDK 36. A zero-byte /tmp/vibe-screen-device-android.lock existed, but lsof
/tmp/vibe-screen-device-android.lock returned no owner. Collection was limited
to read-only device inventory and existing fail-closed evidence tools: no app
install, app start, log clearing, ADB reverse mutation, input injection, or Host
session mutation was performed.

Evidence root:

- evidence/2026-08-23-nubia-p0110-pacific-peripheral-preflight/

The worktree base was origin/main commit
de2752e0033713ad48bb7f86960f9180d8e7342f.

## Results

| Gate | Current-base result | Blocking condition |
| --- | --- | --- |
| Native pointer HID | blocked | No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached. |
| Controller runtime | blocked, can_close_runtime_gate=false | No physical Android gamepad/joystick source is visible; /Applications/Vibe Screen.app has no Apple team identifier and no com.apple.developer.hid.virtual.device entitlement; no Host virtual-gamepad availability line was found. |
| Physical stylus drawing-app | blocked_physical_stylus_not_observed | P0110 exposes a pass-eligible goodix_stylus_input candidate, but no physical stylus drawing, same-session Host Stylus injected: log, Android Stylus forwarded: sample, or visible macOS drawing-app output was observed. |

This preflight does not close any of the three README gates. It is intended to
give the native pointer, controller, stylus, and peripheral framework owners a
current-base fail-closed device snapshot so the Nubia P0110/pacific is not
misreported as having physical mouse, controller, or completed drawing-app
evidence.

## Raw Android input inventory

Read-only inputs retained under
evidence/2026-08-23-nubia-p0110-pacific-peripheral-preflight/raw-adb/:

- adb-devices-l.txt records EP0110PZ0B9110300B as product:pacific model:P0110
  device:pacific.
- dumpsys-input.txt records internal keyboard/power/touch devices and
  goodix_stylus_input. No external mouse-like device and no external GAMEPAD /
  JOYSTICK controller source is present.
- getevent-lp.txt records /dev/input/event7 as goodix_stylus_input with
  BTN_TOUCH, BTN_STYLUS, BTN_STYLUS2, ABS_X, ABS_Y, ABS_PRESSURE, ABS_TILT_X,
  and ABS_TILT_Y.
- getevent-event7-5s.txt records a five-second observation window on
  /dev/input/event7; it timed out with exit code 124 and no event lines, so no
  physical stylus contact was observed in that window.
- settings-input-filtered.txt records only ordinary input settings such as
  pointer_speed=0, selected IME state, and touch exploration disabled; it does
  not show an attached external pointer/controller.

## Gate-specific bundles

### Native pointer HID

Command:

    python3 scripts/native_pointer_hid_acceptance.py \
      --serial EP0110PZ0B9110300B \
      --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
      --visible-result-note "" \
      --no-wait \
      --evidence-dir docs/changes/2026-08-23-peripheral-gates-current-base-preflight/evidence/2026-08-23-nubia-p0110-pacific-peripheral-preflight/native-pointer-hid

Exit code: 2

Evidence:

- native-pointer-hid/result.json
- native-pointer-hid/README.md
- native-pointer-hid/dumpsys-input.txt

The result is blocked before any interactive observation because Android does
not expose an external mouse-like source. No Android native pointer forwarding
logs, Host pointer injection logs, or visible Mac pointer/click result were
recorded.

### Controller runtime

Command:

    python3 scripts/controller_runtime_readiness.py \
      --serial EP0110PZ0B9110300B \
      --host-log "$HOME/Library/Logs/Telemachus/telemachus.log" \
      --host-app "/Applications/Vibe Screen.app" \
      --allow-existing-device-lock \
      --evidence-dir docs/changes/2026-08-23-peripheral-gates-current-base-preflight/evidence/2026-08-23-nubia-p0110-pacific-peripheral-preflight/controller-runtime-readiness

Exit code: 2

Evidence:

- controller-runtime-readiness/controller-runtime-summary.json
- controller-runtime-readiness/controller-runtime-readiness.json
- controller-runtime-readiness/README.md
- controller-runtime-readiness/host-codesign.txt

The structured summary reports verdict=blocked and can_close_runtime_gate=false.
The blocking reasons include missing physical controller hardware, missing Apple
identity signing, missing virtual HID entitlement, and missing Host virtual
gamepad availability.

### Physical stylus drawing-app

Command:

    python3 scripts/android_stylus_acceptance.py \
      --serial EP0110PZ0B9110300B \
      --allow-existing-device-lock \
      --output-dir docs/changes/2026-08-23-peripheral-gates-current-base-preflight/evidence/2026-08-23-nubia-p0110-pacific-peripheral-preflight/physical-stylus

Exit code: 0 for evidence generation; status inside stylus-evidence.json is
blocked_physical_stylus_not_observed.

Evidence:

- physical-stylus/stylus-evidence.json
- physical-stylus/README.md
- physical-stylus/dumpsys-input.txt
- physical-stylus/android-diag.log

The device exposes one pass-eligible goodix_stylus_input candidate with
KEYBOARD, STYLUS, TOUCHSCREEN sources and ORIENTATION, PRESSURE, TILT, X, and Y
axes. Capability alone is not acceptance: no physical drawing was observed, no
Host stylus log was supplied, and no visible macOS drawing-app output was
captured.

## Commands and verification

Read-only ADB inventory was collected with:

    adb -s EP0110PZ0B9110300B devices -l
    adb -s EP0110PZ0B9110300B shell getprop ro.product.manufacturer
    adb -s EP0110PZ0B9110300B shell getprop ro.product.model
    adb -s EP0110PZ0B9110300B shell getprop ro.product.device
    adb -s EP0110PZ0B9110300B shell getprop ro.build.version.release
    adb -s EP0110PZ0B9110300B shell getprop ro.build.version.sdk
    adb -s EP0110PZ0B9110300B shell wm size
    adb -s EP0110PZ0B9110300B shell wm density
    adb -s EP0110PZ0B9110300B shell dumpsys input
    adb -s EP0110PZ0B9110300B shell getevent -lp
    adb -s EP0110PZ0B9110300B shell settings list system
    adb -s EP0110PZ0B9110300B shell settings list secure
    adb -s EP0110PZ0B9110300B shell settings list global
    adb -s EP0110PZ0B9110300B shell 'timeout 5 getevent -lt /dev/input/event7'

Local verification:

    python3 scripts/native_pointer_hid_acceptance.py ... # exit 2, blocked
    python3 scripts/controller_runtime_readiness.py ... # exit 2, blocked
    python3 scripts/android_stylus_acceptance.py ... # wrote blocked evidence
    git diff --check

## Owner notes

- #268 / native pointer: current P0110 has no usable physical HID mouse event
  source. Keep the native pointer HID gate open until a real mouse produces
  Android MOVE / BUTTON_PRESS / BUTTON_RELEASE, Host pointer injection, and
  visible Mac pointer/click evidence in the same window.
- #270 and #220 / controller runtime: current P0110 has no physical controller
  source, and the installed Host app is not Apple identity-signed with the
  virtual HID entitlement. Keep runtime acceptance open until physical
  controller, entitled Host runtime, Mac-side response, and neutral release are
  all observed.
- #266 and #271 / physical stylus: current P0110 has stylus capability but no
  observed physical drawing-app run. Keep the drawing-app gate open until the
  physical stylus stroke produces Android and Host same-session logs plus
  visible macOS drawing output.
- #217 / peripheral framework: this record does not change the framework PR's
  offline-only/fail-closed boundary.
