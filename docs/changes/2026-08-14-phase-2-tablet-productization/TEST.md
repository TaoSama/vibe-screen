# Phase 2 tablet productization verification

## Automated scope

Run the focused Android checks within the task's ten-minute validation budget:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon \
  testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest \
  assembleDebug
```

Run the settings layout instrumentation separately when a device is available.
The test constrains the dialog to the production 85% screen-height viewport and
covers 600x960dp portrait and 960x600dp landscape in addition to the existing
narrow-window, large-text, and responsive toggle-group cases. It also includes
an evidence-image test that renders the sustained-use card for portrait and
landscape review:

```bash
./gradlew --no-daemon connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.SettingsDialogLayoutInstrumentedTest
```

When more than one Android device is attached, bind the evidence run to the
intended device with explicit `adb -s` installs and instrumentation so emulator
results are not confused with the physical-device record:

```bash
adb -s "$ADB_SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk
adb -s "$ADB_SERIAL" install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s "$ADB_SERIAL" shell am instrument -w -r \
  -e class 'dev.telemachus.display.SettingsDialogLayoutInstrumentedTest' \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

## Required device evidence

No target-tablet or long-duration result is recorded by this change. Before
closing Phase 2, execute [RUNBOOK.md](RUNBOOK.md) and retain evidence under
[`evidence/`](evidence/README.md) for all of the following:

- exact 8–9 inch tablet model, OS/build, logical window sizes, density, and both
  orientations, including split/freeform resizing where supported;
- settings status matching `dumpsys battery`, `dumpsys power`, and thermal status
  while charging, discharging, in power saver, and under controlled load;
- stand-mounted charging without cable/data instability or unsafe heat buildup;
- foreground/background and transport interruption recovery with new session
  epochs and no stale frame/input acceptance;
- login launch and headless Mac mini recovery after reboot;
- an eight-hour sample series for live processes, frames/drops, reconnects,
  Android RSS, battery/current/voltage where exposed, and thermal status.

The eight-hour run must not be replaced by this focused test or by a short soak.

## Focused offline result

On 2026-08-14, the focused validation completed well inside the ten-minute
budget:

- `DeviceHealthMonitorTest`: 4 tests, 0 skipped, 0 failures, 0 errors;
- `assembleDebug` and Android test compilation: successful in the same 9-second
  Gradle invocation;
- `SettingsDialogLayoutInstrumentedTest`: 6 tests passed on an Android 16
  `2211133C` device (1080x2400, 420 dpi) in 17 seconds. Its tablet cases use
  synthetic 600x960dp and 960x600dp configurations and do not prove behavior on
  a physical 8–9 inch tablet;
- debug APK SHA-256:
  `f1da0ce7fe726043b45f63ada90ec91e3d8a0a045cdd925a3b7366e414744fcf`.

This follow-up's Gradle validation invocations consumed less than one minute of
wall-clock time in aggregate.

No physical-tablet check, thermal load, or soak was run. The result proves the
focused policy/lifecycle behavior and settings layout under the tested Android
runtime and synthetic configurations only.

## 2026-08-20 Nubia P0110 readiness result

This follow-up used the attached Nubia P0110/pacific (`<device-serial>`) as
an Android phone substitute only. It must not be relabeled as 8-9 inch tablet
evidence and it does not replace the required eight-hour run. Evidence is under
[`evidence/2026-08-20-nubia-p0110-readiness`](evidence/2026-08-20-nubia-p0110-readiness/README.md).

- `DeviceHealthMonitorTest` plus `assembleDebug`: `BUILD SUCCESSFUL in 35s`.
- `assembleDebugAndroidTest`: `BUILD SUCCESSFUL in 9s`.
- Target-device `SettingsDialogLayoutInstrumentedTest`: 7 tests, 0 failures,
  `OK (7 tests)` from direct `adb -s <device-serial> shell am instrument`.
- Sustained-use screenshot test: 1 test, 0 failures, `OK (1 test)` from direct
  `adb -s <device-serial> shell am instrument`.
- The run captured the device identity, `wm size`/density, battery, power, and
  thermal dumps. The short sample read 100% battery, AC powered, power saver
  disabled, and thermal status `0`.
- The screenshot artifacts
  `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png` show the settings sustained-use card
  rendered from the instrumentation path.
- The native screen captures are named `screenshots/portrait.png` and
  `screenshots/portrait-physical-landscape.png` because `user_rotation` remained
  `0`; the physical-landscape capture produced the same portrait Android buffer
  and must not be treated as a real system-landscape screenshot.
- An initial launch attempt recorded `Error type 3`; the app launch was
  reverified afterward under the same device lock, and `am-start-reverify.txt`
  records `Starting: Intent { cmp=dev.telemachus.display/.MainActivity }` with
  exit code `0` in `am-start-reverify-status.txt`.

Still open after this result: real 8-9 inch tablet panel behavior, split or
freeform resizing on target hardware, stand-mounted charging stability,
controlled thermal-load behavior, background/foreground recovery, transport
interruption recovery, login startup, headless Mac recovery, stylus and hardware
keyboard workflows, and the eight-hour sample series required by
[RUNBOOK.md](RUNBOOK.md).

## 2026-08-21 hardware-keyboard blocked preflight

This follow-up added a schema-backed hardware-keyboard workflow evidence summary
for the Phase 2 peripheral gate. The target serial for a future run is
`<device-serial>`, which must be recorded as nubia P0110 / pacific /
Android 16 when used. The real-device workflow did not start because the shared
Android lock already existed, no Host listener was present on TCP `54321`, and
the local keychain reported `0 valid identities found` for code signing. No ADB
commands were run and no physical keyboard condition was evaluated.

Evidence is under
[`evidence/2026-08-21-nubia-p0110-pacific-hardware-keyboard-blocked`](evidence/2026-08-21-nubia-p0110-pacific-hardware-keyboard-blocked/README.md).

Validation performed for this tooling and evidence update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_hardware_keyboard tools.tests.test_schemas -v`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_hardware_keyboard_readiness -v`
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-nubia-p0110-pacific-hardware-keyboard-blocked`

The generated `hardware-keyboard-summary.json` records `verdict=blocked` and
`can_close_hardware_keyboard_gate=false`. The Phase 2 hardware-keyboard workflow
gate remains open until a physical keyboard attached to the recorded Android
device drives production Protocol v1 keyboard forwarding into a stable
signed/TCC-ready Host with retained Host `Key injected:` logs and a visible Mac
result.

The preferred current-base readiness command is now:

```bash
make hardware-keyboard-readiness \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/YYYY-MM-DD-nubia-p0110-pacific-hardware-keyboard-readiness
```

It acquires the shared Android lock, records the P0110 identity and input-device
snapshot when the lock allows ADB, collects Host listener/signing/TCC preflight
artifacts, and writes `hardware-keyboard-readiness.json`,
`hardware-keyboard-observations.json`, and `hardware-keyboard-summary.json`. A
nonzero blocked or insufficient exit is expected when the physical keyboard,
stable signed/TCC Host, or live production keyboard evidence is missing; that
output is readiness evidence only and does not close the Phase 2 gate.

## 2026-08-23 hardware-keyboard current-base readiness

Evidence is under
[`evidence/2026-08-23-nubia-p0110-pacific-hardware-keyboard-readiness`](evidence/2026-08-23-nubia-p0110-pacific-hardware-keyboard-readiness/README.md).
The collector ran against `<device-serial>` and recorded the device as
nubia P0110 / pacific / Android 16 / SDK 36. It exited `2` with
`verdict=blocked` and `can_close_hardware_keyboard_gate=false` because no
external Android-attached hardware keyboard was visible in `dumpsys input`, no
Host listener was present on TCP `54321`, and the Host preflight could not find
the stable `Vibe Screen Dev` signing identity. The package snapshot records the
installed APK as `dev.telemachus.display` version `0.0.0` (`100000`), so APK
identity is present but does not close the gate without the missing physical
keyboard and Host-path evidence.

Additional current-base validation performed for this update:

- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/hardware_keyboard_readiness.py`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.tests.test_hardware_keyboard_readiness -v`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_hardware_keyboard tools.tests.test_phase2_tablet_preflight tools.tests.test_controller_runtime tools.tests.test_schemas -v`
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-nubia-p0110-pacific-hardware-keyboard-blocked`
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-23-nubia-p0110-pacific-hardware-keyboard-readiness`
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.AndroidKeyInputMapperTest --tests dev.telemachus.display.ClientInputDispatchTest --tests dev.telemachus.display.StreamInputDispatcherTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest --tests dev.telemachus.display.ControllerInputMapperTest`
- `cd baseline/MacHost && swift build`

`cd baseline/MacHost && swift test --filter ProtocolV1SessionTests` was attempted
but the local SwiftPM test environment failed before executing tests with
`no such module XCTest`.

## 2026-08-21 Phase 2 evidence manifest readiness

This follow-up added a schema-backed `phase2-tablet-manifest.json` preparation
record for future eight-hour runs. It binds the run to `device-info.json`, the
declared device class, stand/charger/cable setup, host/APK identity, transport,
video preferences, pass/fail thresholds, and planned recovery scenarios before
the timer starts. It also maps the ADB `ro.product.device` value to the manifest
`codename` field so Nubia P0110/pacific and Xiaomi/fuxi evidence keep their real
device identity.

Validation performed for this tooling-only update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_manifest tools.tests.test_device_info tools.tests.test_schemas -v`
- `make phase2-tablet-manifest EVIDENCE_DIR=.build/phase2-manifest-smoke ...`
  using the retained P0110 readiness `device-info.json`; the generated manifest
  recorded `manufacturer=nubia`, `model=P0110`, `codename=pacific`,
  `android_release=16`, and `device_class=android_substitute`.

No device soak, physical-tablet run, controlled thermal load, background or
transport recovery pass, login startup, headless Mac recovery, stylus, or
hardware-keyboard evidence was produced by this tooling update. All Phase 2
device gates above remain open.

## 2026-08-21 Nubia P0110 lifecycle readiness result

This follow-up used the attached Nubia P0110/pacific (`<device-serial>`) as
an Android phone substitute only. Evidence is under
[`evidence/2026-08-21-nubia-p0110-lifecycle-readiness`](evidence/2026-08-21-nubia-p0110-lifecycle-readiness/README.md).

Android lifecycle hardening in this change is covered by focused local tests:

- `StreamingWindowStatePolicyTest`: verifies that a connected foreground stream
  adds both `FLAG_KEEP_SCREEN_ON` and `FLAG_SECURE`, a connected background
  stream clears only `FLAG_KEEP_SCREEN_ON` while reapplying `FLAG_SECURE`, debug
  screenshot opt-in affects only foreground capture, and disconnect clears both
  streaming flags.
- `MainActivityControllerForwardingContractTest`: verifies that foreground
  return requests a fresh USB/LAN keyframe and an Internet-session keyframe, that
  background lifecycle cancellation runs before stop, and that key, touch, and
  generic-motion input paths are gated by foreground state before transport
  dispatch.

Validation performed:

- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.DeviceHealthMonitorTest --tests dev.telemachus.display.MainActivityStatePrimitivesTest --tests dev.telemachus.display.StreamingWindowStatePolicyTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest assembleDebug assembleDebugAndroidTest`: `BUILD SUCCESSFUL in 10s`.
- Direct target-device install of the final debug APK with
  `adb -s <device-serial> install -r ...`.
- Direct target-device `SettingsDialogLayoutInstrumentedTest` with
  `adb -s <device-serial> shell am instrument`: 7 tests, 0 failures,
  `OK (7 tests)`.
- Final debug APK SHA-256:
  `112ceac607210546dfd8f7a8d4e8f7c0644ef9e67f35e94f7d4de83770d3e1e5`.

Observed short-device evidence:

- Device identity remained nubia P0110, codename `pacific`, Android 16 / SDK 36,
  1264x2800 at 560 dpi. This must not be relabeled as Xiaomi/fuxi or as tablet
  evidence.
- The sustained-use settings card screenshots are retained in
  `screenshots/sustained-use-portrait.png` and
  `screenshots/sustained-use-landscape.png`; the final instrumentation run kept
  the settings layout test at 7/7 passing.
- Battery snapshots around the final check stayed at 100%, AC powered true, USB
  powered false, and 34.0 C. Power dumps were collected before and after the
  lifecycle pass. Thermal dumps were collected before and after; the final pass
  observed thermal status `1`, which is below the severe/critical states but was
  not produced by a controlled thermal-load test.
- App-filtered logcat recorded foreground -> background -> foreground lifecycle
  transitions and the background line `connected=false; retries paused`.
- Host transport was blocked: no local listener was present on TCP `54321`, even
  though `adb reverse` listed `UsbFfs tcp:54321 tcp:54321`. Logcat recorded
  repeated `Protocol upgrade probe closed before a response`, so no live stream
  was established.

Still open after this result: real 8-9 inch tablet panel behavior, stand-mounted
charging stability, controlled thermal-load behavior, live foreground/background
recovery with fresh keyframe or bounded reconnect, transport interruption
recovery, login startup, headless Mac recovery, stylus and hardware-keyboard
workflows, and the eight-hour sample series required by [RUNBOOK.md](RUNBOOK.md).

## 2026-08-21 Phase 2 device-memory gate tooling

This follow-up split the Phase 2 device-memory requirement into its own
fail-closed verifier and kept the broader package-aware tablet gate. The
verifiers consume `phase2-tablet-manifest.json`, the exact-window soak report,
and raw evidence artifacts. Before either can return `pass`, the evidence must
declare a physical 8-9 inch tablet, provide an eight-hour window, include
manifested Host PID sampling, Android app PSS samples, Host RSS samples,
charging/full-state samples, thermal-status samples, and the required raw
battery, power, thermal, log, screenshot, build, APK, and device identity
artifacts. Nubia P0110/pacific is explicitly rejected as a tablet substitute
even if a manifest is mislabeled.

Validation performed for this tooling-only update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_device_memory_gate tools.tests.test_phase2_tablet_manifest tools.tests.test_soak_report tools.tests.test_schemas -v`
- `make evidence-tools-test`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_device_memory_gate --manifest docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/phase2-tablet-manifest.json --report docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/exact-window-report.json --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json`

The blocked fixture under
[`evidence/2026-08-21-device-memory-gate-blocked`](evidence/2026-08-21-device-memory-gate-blocked/README.md)
reports `verdict=insufficient` because it has only the Nubia P0110/pacific
phone substitute, a 30-second placeholder window, no Host PID, no Host RSS
series, no charging/full-state series, and no thermal-status series. No new
physical-tablet run or eight-hour soak was performed, so the Phase 2
device-memory gate remains open.

No ADB command or new Android device run was performed for this update. The
readiness smoke uses the retained Nubia P0110/pacific Android 16 identity as
`android_substitute`, and the gate correctly blocks it from becoming formal
physical 8-9 inch tablet evidence. Stand-mounted charging stability, controlled
thermal-load behavior, power stability, background/transport recovery, login
startup, headless Mac recovery, and the eight-hour physical-tablet sample series
remain open.

## 2026-08-21 Phase 2 acceptance preflight readiness

This follow-up added a fail-closed `phase2-tablet-preflight` verifier for the
whole evidence bundle. It is intentionally separate from `phase2-tablet-gate`:
the existing gate evaluates the eight-hour telemetry window, while the preflight
checks that the bundle also contains physical 8-9 inch tablet identity, real
portrait/landscape tablet UI screenshots, physical stylus evidence, hardware
keyboard evidence, recovery evidence, thermal/power raw logs, and the derived
eight-hour gate.

The retained Nubia P0110/pacific readiness directory was rechecked as blocked
evidence only:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_manifest \
  --output docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-20-nubia-p0110-readiness/phase2-tablet-manifest.json \
  --device-info docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-20-nubia-p0110-readiness/device-info.json \
  --device-class android_substitute \
  --stand-setup "bench phone stand; not 8-9 inch tablet hardware" \
  --charger "AC powered device state from retained P0110 readiness evidence" \
  --cable-or-dock "USB-C data cable used for P0110 readiness collection" \
  --transport usb \
  --video-preferences "Balanced 60 FPS readiness placeholder; no eight-hour stream" \
  --allow-missing-host-pid \
  --battery-temperature-limit-celsius 45 \
  --maximum-net-battery-drain-percent 0 \
  --recovery-scenarios "blocked_no_physical_tablet" \
  --host-identity "local Mac host used for retained readiness evidence" \
  --host-build "no formal signed Phase 2 tablet host build; readiness evidence only" \
  --apk-sha256 "cebbaacfb7bc26a4fbdfee61a272b2f35247c8692b306afec0b6b99f3ffacfba" \
  -- make soak-8h \
    EVIDENCE_SERIAL=<device-serial> \
    EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-20-nubia-p0110-readiness
make phase2-tablet-preflight \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-20-nubia-p0110-readiness
```

The `make phase2-tablet-preflight` invocation exited nonzero as expected and
wrote `evidence/2026-08-20-nubia-p0110-readiness/phase2-tablet-preflight.json`
with `verdict=blocked` because the manifest records
`device_class=android_substitute`. The same report preserves the missing gates:
no physical stylus pass, no hardware-keyboard pass, no eight-hour soak gate, no
real tablet orientation/touch-mapping pass, no stand-mounted thermal/power pass,
and no recovery evidence.

Validation performed for this tooling/documentation update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_tablet_gate tools.tests.test_phase2_tablet_manifest tools.tests.test_schemas -v`

No physical 8-9 inch tablet was attached for this follow-up. The Nubia P0110
remains a general Android substitute only and must not be used to claim Phase 2
tablet acceptance.

## 2026-08-21 Phase 2 soak evidence runner

This follow-up added `vibescreen_evidence.phase2_tablet_soak` and Makefile
targets `phase2-tablet-soak-preflight` and `phase2-tablet-soak-run`. The runner
coordinates the device lock, static Host/device/APK artifacts, Android battery,
power, thermal and logcat captures, short preflight sampling, formal 8-hour
sampling, and the exact-window gate derivation when the formal run is allowed to
start. It writes `phase2-soak-readiness.json` with `result=blocked` whenever the
setup cannot legitimately close the Phase 2 tablet gate.

Focused validation for this tooling update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_soak -v`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_soak tools.tests.test_soak tools.tests.test_phase2_tablet_gate tools.tests.test_phase2_tablet_manifest tools.tests.test_device_info tools.tests.test_schemas -v`

The runner tests cover existing-lock behavior without running ADB, preflight
blocker generation, Android logcat derivative extraction, and atomic lock
release. Any Nubia P0110/pacific run produced through this runner remains
Android-substitute readiness only; it is not Xiaomi/fuxi evidence and cannot
close the 8-9 inch tablet, stand-mounted charging, login/headless recovery, or
eight-hour sustained-use gates.

A 2-second target-device preflight also ran against the attached Nubia
P0110/pacific (`adb -s <device-serial>`) and wrote evidence under
[`evidence/2026-08-21-nubia-p0110-phase2-soak-preflight`](evidence/2026-08-21-nubia-p0110-phase2-soak-preflight/README.md).
The command returned exit code `2` by design because the readiness result is
`blocked`. The runner captured device identity, battery, power, thermal dumps,
Android PID, raw logcat, derived log filters, and a complete one-sample
`soak-preflight/summary.json` with `reconnect_count=0`. The recorded blockers
are: device class is `android_substitute`, no Host PID was provided for RSS
sampling, and no Host telemetry JSONL path was provided. The gate remains open.

## 2026-08-22 Phase 2 stand-mounted charging gate owner readiness

This follow-up makes the Phase 2 stand-mounted charging owner explicit in the
pre-run evidence manifest and auditable in `phase2-tablet-gate`. New manifest
runs must provide `PHASE2_GATE_OWNERS`, including owners for
`stand_mounted_charging`, `thermal_power_sampling`, `posture_and_mount`, and
`eight_hour_sustained_stream`. The gate reports each owner under
`evidence_package.gate_owners` and keeps the evidence `insufficient` when any
owner is missing. The follow-up also makes `gate_owners` schema-required for
new manifests, requires physical-tablet manifests to declare an 8.0-9.0 inch
size, and rejects Nubia P0110/pacific when a hand-written manifest mislabels it
as `physical_8_9_inch_tablet`.

Validation performed for this tooling/readiness update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_manifest tools.tests.test_phase2_tablet_gate tools.tests.test_schemas -v`
  - 31 tests passed.
- `make evidence-tools-test`
  - 221 tests passed.

No ADB command or new Android device run was performed for this update. The
existing Nubia P0110/pacific records remain Android substitute evidence only;
they are useful for readiness and blocked-preflight documentation, but they do
not close the physical 8-9 inch tablet, stand-mounted charging, thermal-load,
power, recovery, login-startup, headless Mac, or eight-hour sustained-stream
gates.

## 2026-08-23 current-base aggregate owner readiness

This follow-up added a schema-backed `phase2-aggregate-owner` report for the
open Phase 2 physical-tablet, thermal/power, charging, recovery, and 8h
workstreams. The aggregate does not replace child gates; it records the current
owner matrix, stale/duplicate PR classifications, and final README-level
`blocked` verdict while hardware evidence is missing.

Current owner/stale decisions recorded by the aggregate report:

1. #174 owns the current-base eight-hour soak runner child path.
2. #285 owns the device-environment child path for stand charging, controlled
   thermal load, and power stability.
3. #234 and #240 remain active child slices for tablet UI and hardware keyboard.
4. #189 and #213 are merged baseline inputs.
5. #252 is stale/duplicate by #285, #255 is partially superseded by #285 plus
   aggregate owner mapping, and the old #274 branch is superseded by this
   current-base aggregate owner.

Validation performed for this tooling/readiness update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-23-phase2-aggregate-owner-current-base PHASE2_TABLET_GATE=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json PHASE2_TABLET_MANIFEST=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json PHASE2_HARDWARE_KEYBOARD=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-nubia-p0110-pacific-hardware-keyboard-blocked/hardware-keyboard-summary.json PHASE2_DEVICE_MEMORY=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json`

The generated `phase2-aggregate-owner.json` records `verdict=blocked` and
`can_close_readme_phase2_gates=false`. It consumes existing P0110 substitute
readiness inputs only as blocked evidence; P0110/pacific remains an Android
phone substitute and cannot close the physical 8-9 inch tablet gate.

## 2026-08-24 hardware-keyboard current-base owner

This follow-up refreshes the dedicated hardware-keyboard owner on current
`origin/main` (`942fee8d1b8a4495c24dbe3a5aacf538e04bb6f0`) without claiming a
workflow pass. The audit result is: #179 is merged and provides the baseline
hardware-keyboard evidence gate; #240 is closed and superseded by this
current-base owner; #287 remains a peripheral-gates draft outside this keyboard
workflow; #315 is merged and owns reconnect timing; #321 is merged and provides
the actionable-error baseline consumed by this owner.

The evidence contract now requires explicit observations for the active selected
display stream, Android foreground/focus and IME boundary, Host key-injection
or acknowledgement/CGEvent logs, and modifier press/release semantics in addition to the existing
physical keyboard, Protocol v1 keyboard capability, shortcut, cleanup, retained
logs, and visible Mac-result requirements. `adb shell input keyevent`, emulator
input, and offline mapper tests remain readiness only. The dedicated runbook is
[`../../runbook/hardware-keyboard-workflow.md`](../../runbook/hardware-keyboard-workflow.md).

Fresh P0110/pacific readiness evidence is under
[`evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base`](evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base/README.md).
The collector used the explicit local ADB serial, redacted it to
`<device-serial>` in committed artifacts, and recorded the device as nubia
P0110 / pacific / Android 16 / SDK 36. It exited `2` with
`verdict=blocked` and `can_close_hardware_keyboard_gate=false`: no external
Android-attached hardware keyboard was visible in `dumpsys input`, and the Host
preflight failed stable signed/TCC readiness because the `Vibe Screen Dev`
signing identity was unavailable. A Host listener was present on TCP `54321`,
but listener presence alone does not close the Host path.

The current-base aggregate owner evidence is under
[`evidence/2026-08-24-phase2-hardware-keyboard-current-base-owner`](evidence/2026-08-24-phase2-hardware-keyboard-current-base-owner/README.md).
It consumes the new hardware-keyboard blocked summary and records
`verdict=blocked` with `can_close_readme_phase2_gates=false`; no README gate is
closed by this update.

Validation performed for this tooling/readiness update:

- `make hardware-keyboard-readiness EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base` (exit `2`, expected blocked readiness)
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base`
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-phase2-hardware-keyboard-current-base-owner PHASE2_TABLET_GATE=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json PHASE2_TABLET_MANIFEST=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json PHASE2_HARDWARE_KEYBOARD=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-24-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json PHASE2_DEVICE_MEMORY=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/hardware_keyboard_readiness.py`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest scripts.tests.test_hardware_keyboard_readiness scripts.tests.test_hardware_keyboard_readiness_redaction tools.tests.test_hardware_keyboard tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `make evidence-tools-test`
- `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.AndroidKeyInputMapperTest --tests dev.telemachus.display.NativeInputWireTest --tests dev.telemachus.display.NativeInputSessionStateTest --tests dev.telemachus.display.ClientInputDispatchTest --tests dev.telemachus.display.StreamInputDispatcherTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest`
- `cd baseline/MacHost && swift build`
- `shasum -a 256 -c SHA256SUMS` in both new 2026-08-24 evidence directories
- `git diff --check`

## 2026-08-25 device-environment current-base readiness

Fresh P0110/pacific device-environment readiness evidence is under
[`evidence/2026-08-25-p0110-device-environment-readiness`](evidence/2026-08-25-p0110-device-environment-readiness/README.md).
The retained summary records nubia P0110 / pacific / Android 16 / SDK 36 as an
`android_substitute` phone and reports `verdict=blocked`,
`can_close_stand_charging_gate=false`, and
`can_close_device_environment_gate=false`. The retained battery, power, and
thermal dumps are readiness-only snapshots; they do not prove a physical
8-9 inch tablet, stand-mounted charging setup, controlled thermal-load
recovery, or eight-hour environment window.

The aggregate owner record under
[`evidence/2026-08-25-phase2-aggregate-owner-current-base`](evidence/2026-08-25-phase2-aggregate-owner-current-base/README.md)
consumes the device-environment summary and remains `verdict=blocked` with
`can_close_readme_phase2_gates=false`.

Validation recorded for this update:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_device_environment tools.tests.test_phase2_tablet_gate tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `make phase2-device-environment-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness`
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-phase2-aggregate-owner-current-base ...`
- `shasum -a 256 -c SHA256SUMS`

## 2026-08-27 login/headless current-base readiness

Evidence is under
[`evidence/2026-08-27-macos-login-headless-current-base-blocked`](evidence/2026-08-27-macos-login-headless-current-base-blocked/README.md).
The passive macOS startup/recovery verifier reports `verdict=blocked` and
`can_close_login_headless_gate=false`. It observed a local Host listener and
startup defaults, but no current-source installed Host provenance, read-only TCC
verification, Launch at Login machine verification, Virtual HID entitlement,
reboot/login launch, headless display, client-rendered first frame, bounded
recovery, or window-restore artifact was available.

This evidence did not run `/usr/bin/sfltool dumpbtm`, did not pass any
login-item diagnostic opt-in flag, did not touch ADB, and did not close login
startup or headless Mac mini acceptance. The local `phase2-aggregate-owner.json`
inside the same directory consumes only the login/headless blocked summary and
keeps `can_close_readme_phase2_gates=false`.

## 2026-08-28 P0110 tablet soak preflight current-base

Evidence is under
[`evidence/2026-08-28-nubia-p0110-phase2-soak-preflight-current-base`](evidence/2026-08-28-nubia-p0110-phase2-soak-preflight-current-base/README.md).
The 2-second preflight ran against the attached `<device-serial>` device and
records it as nubia P0110 / pacific / Android 16 / SDK 36 with
`device_class=android_substitute`. It exited `2` as expected, wrote
`phase2-soak-readiness.json` with `result=blocked` and
`can_close_phase2_gate=false`, and did not start an eight-hour soak. Blockers
were the missing formal APK identity, non-tablet device class, missing Host PID,
and missing Host telemetry JSONL.

The same directory was checked with `phase2-tablet-preflight`; that verifier also
exited nonzero and wrote `phase2-tablet-preflight.json` with
`verdict=blocked`. The physical-tablet gate reason is: device class is
`android_substitute`, while Phase 2 tablet acceptance requires
`physical_8_9_inch_tablet`. No physical stylus, hardware-keyboard,
portrait/landscape tablet UI, recovery, thermal/power, or eight-hour soak gate
artifact was produced.

Current-base aggregate evidence is under
[`evidence/2026-08-28-phase2-tablet-current-base-owner`](evidence/2026-08-28-phase2-tablet-current-base-owner/README.md).
It consumes the new P0110 soak preflight plus retained device-environment,
current-base hardware-keyboard, and login/headless blocked summaries. The
report records
`source_baseline=origin/main b54ee0e929c53459e6ba7e060f2c9de0c846f408`,
`verdict=blocked`, and `can_close_readme_phase2_gates=false`; it also records
that Nubia P0110/pacific is substitute readiness only and must not be relabeled
as another device or 8-9 inch tablet evidence.

Validation performed for this update:

- `make phase2-tablet-soak-preflight EVIDENCE_SERIAL=<device-serial> ... PHASE2_SOAK_PREFLIGHT_DURATION=2s PHASE2_SOAK_INTERVAL=1s` (exit `2`, expected blocked readiness)
- `make phase2-tablet-preflight EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-phase2-soak-preflight-current-base` (exit `2`, expected blocked bundle verifier)
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-phase2-tablet-current-base-owner ...`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_soak tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `shasum -a 256 -c SHA256SUMS` in both new 2026-08-28 evidence directories

## 2026-08-29 P0110 tablet soak preflight current-base

Evidence is under
[`evidence/2026-08-29-nubia-p0110-phase2-soak-preflight-current-base`](evidence/2026-08-29-nubia-p0110-phase2-soak-preflight-current-base/README.md)
and
[`evidence/2026-08-29-phase2-tablet-current-base-owner`](evidence/2026-08-29-phase2-tablet-current-base-owner/README.md).
The run used the attached Nubia P0110/pacific Android 16 device as a general
Android phone substitute only. It is not Xiaomi/fuxi evidence and not physical
8-9 inch tablet evidence.

The soak preflight exited `2` and wrote `phase2-soak-readiness.json` with
`result=blocked` and `can_close_phase2_gate=false` because APK identity, Host
PID, Host telemetry JSONL, physical 8-9 inch tablet hardware, stand-mounted
tablet setup, controlled thermal-load recovery, and an eight-hour stream window
were not available. The bundle verifier also exited `2` and wrote
`phase2-tablet-preflight.json` with `verdict=blocked`.

The refreshed aggregate owner report consumes the 2026-08-29 P0110 manifest and
soak-readiness files plus the retained device-environment, hardware-keyboard,
and login/headless blocked summaries. It records
`source_baseline=origin/main b22b9b5f92249cb484bdf71fef22f8f479f575f3`,
`verdict=blocked`, and `can_close_readme_phase2_gates=false`.

Validation performed for this current-base refresh:

- `make phase2-tablet-soak-preflight ...` against `<device-serial>`: exit `2`,
  expected blocked readiness.
- `make phase2-tablet-preflight EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-phase2-soak-preflight-current-base`: exit `2`, expected blocked bundle verifier.
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-phase2-tablet-current-base-owner ...`: exit `0`, expected blocked aggregate owner report.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest tools.tests.test_phase2_tablet_soak tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_phase2_device_environment tools.tests.test_phase2_device_memory_gate tools.tests.test_phase2_tablet_gate tools.tests.test_phase2_tablet_manifest tools.tests.test_schemas -v`: 116 tests, `OK`.
- `shasum -a 256 -c SHA256SUMS` in both new 2026-08-29 evidence directories.
- `pgrep -x sfltool || true` before and after the refresh: no residual process output.

The Phase 2 tablet, stand-mounted charging, thermal/power, device-memory,
recovery, hardware-keyboard, login/headless, and eight-hour soak gates remain
open after this refresh.

## 2026-08-28 hardware-keyboard current-base refresh

This follow-up refreshed the Android-attached hardware-keyboard owner on current
`origin/main` (`20cd27b1d59dfcc66e28df41aba421e14b6171f4`) without claiming a
workflow pass. Evidence is under
[`evidence/2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base`](evidence/2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base/README.md).

The readiness collector used explicit ADB serial `<device-serial>`, redacted
it to `<device-serial>` in public artifacts, and recorded the device as nubia
P0110 / pacific / Android 16 / SDK 36. It produced `verdict=blocked` and
`can_close_hardware_keyboard_gate=false` because no external Android-attached
physical keyboard was visible in `dumpsys input`, and Host stable signed/TCC
readiness failed because the `Vibe Screen Dev` signing identity was unavailable.
A Host listener on TCP `54321` was present, but listener presence alone does not
close the Host path. The collector did not synthesize soft-keyboard or
`adb shell input keyevent` input.

The current-base aggregate owner evidence is under
[`evidence/2026-08-28-phase2-hardware-keyboard-current-base-owner`](evidence/2026-08-28-phase2-hardware-keyboard-current-base-owner/README.md).
It consumes the refreshed hardware-keyboard blocked summary and records
`verdict=blocked` with `can_close_readme_phase2_gates=false`; no README gate is
closed by this update.

Tooling was tightened so the shared macOS Host signing/TCC prerequisite report
uses neutral device-evidence wording instead of touch-specific wording, and the
Phase 2 aggregate owner report now derives `source_baseline` from the local
`origin/main` ref instead of a stale hard-coded SHA.

Validation performed for this update:

- `make hardware-keyboard-readiness EVIDENCE_SERIAL=<device-serial> EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base` (blocked readiness; summary records `verdict=blocked`)
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base` (expected non-pass for blocked evidence)
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-phase2-hardware-keyboard-current-base-owner PHASE2_TABLET_GATE=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json PHASE2_TABLET_MANIFEST=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json PHASE2_HARDWARE_KEYBOARD=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-28-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json PHASE2_DEVICE_MEMORY=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json PHASE2_DEVICE_ENVIRONMENT=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json PHASE2_SOAK_READINESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-nubia-p0110-phase2-soak-preflight-current-base-230933/phase2-soak-readiness.json PHASE2_LOGIN_HEADLESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/hardware_keyboard_readiness.py scripts/macos_dev_host.py`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest scripts.tests.test_hardware_keyboard_readiness scripts.tests.test_hardware_keyboard_readiness_redaction scripts.tests.test_macos_dev_host tools.tests.test_hardware_keyboard tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `make evidence-tools-test`
- `cd baseline/MacHost && swift build`
- `shasum -a 256 -c SHA256SUMS` in both new 2026-08-28 evidence directories
- `git diff --check`

## 2026-08-30 hardware-keyboard current-base refresh

This follow-up refreshes the Android-attached hardware-keyboard owner on current
`origin/main` (`8bdde8a2ab2ebd7255635ad5f22f79b37dd7bc25`) without claiming a
workflow pass. Evidence is under
[`evidence/2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base`](evidence/2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base/README.md).

The readiness collector used explicit ADB serial `<device-serial>`, redacted
it to `<device-serial>` in public artifacts, and recorded the device as nubia
P0110 / pacific / Android 16 / SDK 36. It produced `verdict=blocked` and
`can_close_hardware_keyboard_gate=false` because no external Android-attached
physical keyboard was visible in `dumpsys input`, no macOS Host listener on TCP
`54321` was observed during the refresh window, and Host stable signed/TCC
readiness failed because the `Vibe Screen Dev` signing identity was unavailable.
The collector did not synthesize soft-keyboard or `adb shell input keyevent`
input. This refresh remains substitute Android readiness only and is not
relabeled as Xiaomi/fuxi or physical 8-9 inch tablet evidence.

The current-base aggregate owner evidence is under
[`evidence/2026-08-30-phase2-hardware-keyboard-current-base-owner`](evidence/2026-08-30-phase2-hardware-keyboard-current-base-owner/README.md).
It consumes the refreshed hardware-keyboard blocked summary and records
`verdict=blocked` with `can_close_readme_phase2_gates=false`; no README gate is
closed by this update.

The Phase 2 tablet, stand-mounted charging, thermal/power, device-memory,
recovery, hardware-keyboard, login/headless, and eight-hour soak gates remain
open after this refresh.

Validation performed for this update:

- `make hardware-keyboard-readiness EVIDENCE_SERIAL='<device-serial>' EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base` (blocked readiness; summary records `verdict=blocked`)
- `make hardware-keyboard-gate EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base` (expected non-pass for blocked evidence)
- `make phase2-aggregate-owner EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-30-phase2-hardware-keyboard-current-base-owner PHASE2_TABLET_GATE=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-gate.json PHASE2_TABLET_MANIFEST=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-phase2-gate-readiness/phase2-tablet-manifest.json PHASE2_HARDWARE_KEYBOARD=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-pacific-hardware-keyboard-current-base/hardware-keyboard-summary.json PHASE2_DEVICE_MEMORY=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-21-device-memory-gate-blocked/soak-8h/phase2-device-memory-gate.json PHASE2_DEVICE_ENVIRONMENT=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-25-p0110-device-environment-readiness/soak-8h/phase2-device-environment-summary.json PHASE2_SOAK_READINESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-29-nubia-p0110-phase2-soak-preflight-current-base/phase2-soak-readiness.json PHASE2_LOGIN_HEADLESS=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/2026-08-27-macos-login-headless-current-base-blocked/macos-startup-recovery-gate.json`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/hardware_keyboard_readiness.py scripts/macos_dev_host.py`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest scripts.tests.test_hardware_keyboard_readiness scripts.tests.test_hardware_keyboard_readiness_redaction scripts.tests.test_macos_dev_host tools.tests.test_hardware_keyboard tools.tests.test_phase2_tablet_preflight tools.tests.test_phase2_aggregate_owner tools.tests.test_schemas -v`
- `shasum -a 256 -c SHA256SUMS` in the 2026-08-29 hardware-keyboard
  readiness and 2026-08-30 aggregate-owner evidence directories
- `git diff --check`
