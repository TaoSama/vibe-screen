# P0110 Peripheral Gate Readiness

Date: 2026-08-24

Evidence collection baseline: `origin/main` at
`6bcf185094bb2a9c77abb7c642833b7ac03b5835`. The PR has since been
replayed and reverified on `origin/main` at
`32798e81bbb84e2155905a8e08ea7cc7c1ff8e46`, then again on `origin/main` at
`0ed49b5fd3b28f8504d2ea25747b176ca4971414`, and again on `origin/main` at
`8fcec1d95dbac1b41a587522f987f3890281a3ec`, then again on `origin/main` at
`d3c18962837b795e3069e8652ea8fa4111b6df8a`, then again on `origin/main` at
`549aa048d94e5131eb9f691a49a19a427fe2fe30`, then again on `origin/main` at
`fd15e0187bee7bd83b2d3938e301c2297bad4b5d`.

Device under test: `nubia P0110 / pacific / Android 16 / SDK 36`; the
published ADB serial is redacted as `<device-serial>`. Do not relabel this
evidence as Xiaomi 13/fuxi.

Evidence bundle:
`docs/changes/2026-08-24-p0110-peripheral-gates-readiness/evidence/2026-08-24-nubia-p0110-pacific-peripheral-readiness-v2/`

## Scope

This pass audits and hardens the three high-priority Android/P0110 peripheral
gates from the README:

- physical stylus drawing-app confirmation;
- native mouse pointer move/click physical HID confirmation;
- hardware-keyboard workflow confirmation.

No gate is closed by this record. The retained evidence is readiness and
fail-closed evidence only. Synthetic `adb input` events are not physical HID,
stylus, or hardware-keyboard evidence.

## Results

| Gate | Summary | Verdict | Can close gate | Blocking reason |
| --- | --- | --- | --- | --- |
| Physical stylus drawing app | `physical-stylus/stylus-summary.json` | `blocked` | `false` | P0110 exposes `goodix_stylus_input` with STYLUS/pressure/tilt capability, but no physical drawing, Host stable signed/TCC readiness, Host stylus injection excerpt, or visible macOS drawing-app output was captured. |
| Native pointer HID mouse | `native-pointer-hid/native-pointer-hid-summary.json` | `blocked` | `false` | No external Android input device with `MOUSE`, `MOUSE_RELATIVE`, `TOUCHPAD`, or `TRACKBALL` source was attached; Host stable signed/TCC readiness was not asserted. |
| Hardware keyboard workflow | `hardware-keyboard/hardware-keyboard-summary.json` | `blocked` | `false` | No external Android-attached keyboard was visible, and macOS Host preflight did not establish stable signing/TCC readiness. The current Host listener was observed on TCP 54321, but that alone cannot close the gate. |

## Commands

All Android commands that touched the device used an explicit `adb -s` target;
the published evidence redacts that target as `<device-serial>`.

```bash
git fetch origin --prune
git rev-parse origin/main

adb -s <device-serial> devices -l
adb -s <device-serial> shell getprop ro.product.manufacturer
adb -s <device-serial> shell getprop ro.product.model
adb -s <device-serial> shell getprop ro.product.device
adb -s <device-serial> shell getprop ro.build.version.release
adb -s <device-serial> shell getprop ro.build.version.sdk
adb -s <device-serial> shell dumpsys input

make physical-stylus-acceptance \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_DIR=docs/changes/2026-08-24-p0110-peripheral-gates-readiness/evidence/2026-08-24-nubia-p0110-pacific-peripheral-readiness-v2/physical-stylus \
  STYLUS_HOST_LOG="$HOME/Library/Logs/Telemachus/telemachus.log" \
  STYLUS_OBSERVE_SECONDS=0 \
  STYLUS_DRAWING_OBSERVATION=""

make native-pointer-hid-acceptance \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_DIR=docs/changes/2026-08-24-p0110-peripheral-gates-readiness/evidence/2026-08-24-nubia-p0110-pacific-peripheral-readiness-v2/native-pointer-hid \
  NATIVE_POINTER_HOST_LOG="$HOME/Library/Logs/Telemachus/telemachus.log" \
  NATIVE_POINTER_OBSERVE_SECONDS=0 \
  NATIVE_POINTER_VISIBLE_RESULT_NOTE=""

make hardware-keyboard-readiness \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_PACKAGE=dev.telemachus.display \
  EVIDENCE_PORT=54321 \
  EVIDENCE_DIR=docs/changes/2026-08-24-p0110-peripheral-gates-readiness/evidence/2026-08-24-nubia-p0110-pacific-peripheral-readiness-v2/hardware-keyboard
```

The physical stylus, native pointer, and hardware keyboard make commands
intentionally returned exit code `2`, which means blocked. Their exit codes are
retained in `physical-stylus/make-exit.txt`,
`native-pointer-hid/make-exit.txt`, and `hardware-keyboard/make-exit.txt`.

## Tooling Verification

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest \
  tools.tests.test_stylus \
  tools.tests.test_native_pointer_hid \
  tools.tests.test_hardware_keyboard \
  tools.tests.test_phase2_tablet_preflight \
  tools.tests.test_schemas

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest \
  scripts.tests.test_release_tools.AndroidStylusAcceptanceTests \
  scripts.tests.test_native_pointer_hid_acceptance \
  scripts.tests.test_hardware_keyboard_readiness

python3 -m py_compile \
  tools/vibescreen_evidence/stylus.py \
  tools/vibescreen_evidence/native_pointer_hid.py \
  tools/vibescreen_evidence/hardware_keyboard.py \
  scripts/android_stylus_acceptance.py \
  scripts/native_pointer_hid_acceptance.py \
  scripts/hardware_keyboard_readiness.py

shasum -a 256 -c \
  docs/changes/2026-08-24-p0110-peripheral-gates-readiness/evidence/2026-08-24-nubia-p0110-pacific-peripheral-readiness-v2/SHA256SUMS

git diff --check
```

## Remaining Open Work

- Attach a real Android-visible mouse or touchpad to P0110, run native pointer
  acceptance with move/press/release, retain Android forwarding logs, Host
  `Pointer injected` logs, and visible Mac result.
- Draw with a real physical stylus in a macOS drawing app through an active
  Protocol v1 session, retain Android `Stylus forwarded` diagnostics, Host
  `Stylus injected` logs, and visible drawing output.
- Attach a real Android-visible hardware keyboard, run a stable signed/TCC-ready
  Host, then capture press/release, shortcut, modifier cleanup, Host
  `Key injected` logs, and visible Mac result.
