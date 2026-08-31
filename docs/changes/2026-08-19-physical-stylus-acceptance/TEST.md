# Physical Stylus Acceptance Readiness

## Gate status

The README physical-stylus drawing-app confirmation gate remains open. A passing
run still requires all of the following from the same named device session:

- an active Protocol v1 USB, LAN, or Internet session;
- a real physical stylus contacting the Android device;
- Host `Stylus injected:` log lines that include contact state, buttons,
  pressure, and signed `tiltX` / `tiltY`;
- visible macOS drawing-app output from that stylus stroke.

Device capability snapshots and offline protocol tests are useful readiness
evidence, but they do not close the gate.

## 2026-08-20 readiness result

The target Android serial was `<device-serial>`, which was previously
identified in this change as nubia P0110 / pacific / Android 16 / SDK 36. This
run did not execute ADB capability collection because
`/tmp/vibe-screen-device-android.lock` already existed before the acceptance
script could start.

Evidence: none; ADB collection was blocked before an evidence bundle could be
written for this attempt.

## 2026-08-27 P0110 PR-head refresh

After merging `origin/main` commit `32b05030cf4cff54029d9bffd4c9dd0cb7e1d6e3`
into `codex/p0110-peripheral-runtime-gates`, PR-head commit
`7e06483becdc1b63f0de74dfed56342eed2d0aba` was checked again. Android
commands used `adb -s <device-serial>` and the connected device was recorded as
nubia P0110 / pacific / Android 16 / SDK 36. The input snapshot still exposes a
pass-eligible `goodix_stylus_input` candidate with pressure, orientation, tilt,
X, and Y axes. No physical stylus drawing observation was performed, no
same-session Android `Stylus forwarded:` samples appeared, no Host
`Stylus injected:` excerpt was captured, and no visible macOS drawing-app output
was recorded. The README physical-stylus drawing-app gate remains open.

Evidence:

- [2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483/stylus-summary.json](evidence/2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483/stylus-summary.json)
- [2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483/stylus-evidence.json](evidence/2026-08-27-nubia-p0110-pacific-stylus-current-pr-blocked-7e06483/stylus-evidence.json)

- `evidence/2026-08-19-nubia-p0110-pacific-stylus-blocked/`: existing device
  capability snapshot; P0110 exposes `goodix_stylus_input` with pressure and
  tilt axes, but no physical drawing was observed.
- `evidence/2026-08-20-nubia-p0110-pacific-stylus-lock-blocked/`: lock-blocked
  readiness record; no ADB commands were run and no physical stylus event was
  observed.

## 2026-08-21 P0110 preflight result

The target Android device was rechecked with explicit `adb -s DEVICE_SERIAL ...`
commands under the short device lock
`/tmp/vibe-screen-device-android.lock`. The device identified as nubia P0110 /
pacific / Android 16 / SDK 36. The read-only `dumpsys input` snapshot exposes
`goodix_stylus_input`; one candidate has pressure/tilt axes but no parsed
source, and one candidate is pass-eligible for capability preflight because it
declares `KEYBOARD | TOUCHSCREEN | STYLUS` plus pressure, orientation, tilt, X,
and Y axes. No physical stylus drawing was performed, no Host stylus injection
log was supplied, and the app diagnostic log contains no same-session
`Stylus forwarded:` samples, so the drawing-app gate remains blocked.

Evidence:
- `evidence/2026-08-21-nubia-p0110-pacific-stylus-preflight-failclosed/`:
  current fail-closed script output; status is
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate but no physical drawing observation.
- `evidence/2026-08-21-200005-nubia-p0110-pacific-stylus-preflight/`:
  refreshed read-only preflight after rebasing onto `origin/main` at
  `55a78526`; the device was online as nubia P0110 / pacific / Android 16 /
  SDK 36, `adb reverse` listed `tcp:54321`, the Vibe Screen Activity was
  `RESUMED`, and the script again reported
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate. No physical stylus drawing, Host stylus injection excerpt, or
  visible drawing-app screenshot was captured, so the README gate remains open.

## 2026-08-22 P0110 drawing-app closure attempt

The latest `origin/main` snapshot at `ebd2e3a2` was rechecked on the same target
serial with explicit `adb -s <device-serial> ...` commands. The device again
identified as nubia P0110 / pacific / Android 16 / SDK 36, with no active
device coordination lock. `dumpsys input` still exposes a pass-eligible
`goodix_stylus_input` candidate declaring `KEYBOARD | TOUCHSCREEN | STYLUS` plus
pressure, orientation, tilt, X, and Y axes. The run did not start a physical
drawing observation window and did not supply a Host log path, so the acceptance
script wrote fail-closed evidence with no same-window Host `Stylus injected:`
excerpt, no same-session `Stylus forwarded:` sample, and no visible macOS
drawing-app output. The README drawing-app gate therefore remains open.

Evidence:

- `evidence/2026-08-22-nubia-p0110-pacific-stylus-drawing-blocked/`: refreshed
  fail-closed closure attempt on current `origin/main`; status is
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate, no physical drawing observation, no Host stylus log, and no
  drawing-app screenshot.

## 2026-08-28 P0110 capability snapshot

The gate owner was rechecked from a clean `origin/main` worktree at `27d2b0e49`
on branch `codex/stylus-nubia-capability-snapshot`. The required
`pgrep -x sfltool || true` preflight had no output, and no
`/usr/bin/sfltool dumpbtm` command was executed. The target device operation
used the serial-specific lock
`/tmp/vibe-screen-android-<device-serial>.lock`; an empty stale lock from an
aborted local command construction attempt was removed before any ADB command
ran, then the same lock was acquired and released around the read-only ADB
snapshot.

The device identified as nubia P0110 / pacific / Android 16 / SDK 36. The raw
`adb -s <device-serial> shell getevent -lp` snapshot records
`/dev/input/event7` named `goodix_stylus_input` with `BTN_TOUCH`,
`BTN_STYLUS`, `BTN_STYLUS2`, `ABS_PRESSURE`, and signed `ABS_TILT_X` /
`ABS_TILT_Y`. `ABS_DISTANCE` appears on `/dev/input/event6`, named
`STM VL53L1 proximity sensor`, so it is not counted as a Goodix stylus
capability. The raw snapshot did not expose `BTN_TOOL_PEN` or
`BTN_TOOL_RUBBER`, so eraser runtime support was not observed.
The collector still found one pass-eligible Android candidate declaring
`KEYBOARD | TOUCHSCREEN | STYLUS` plus pressure and tilt axes. No physical
stylus was available for drawing, no Host stylus-injection excerpt was supplied,
and no visible macOS drawing-app output was captured. The README drawing-app
gate therefore remains blocked.

Evidence:

- `evidence/2026-08-28-nubia-p0110-pacific-stylus-capability-snapshot/`: current
  capability-only snapshot; status is `blocked_physical_stylus_not_observed`,
  `stylus-summary.json` has `verdict=blocked` and
  `can_close_physical_stylus_gate=false`, and the record must remain labeled as
  Nubia P0110/pacific evidence rather than Xiaomi 13/fuxi evidence.

## 2026-08-29 P0110 current-base fail-closed refresh

The device collection snapshot at `757e5cc` was rechecked with one online
Android device and explicit `adb -s DEVICE_SERIAL ...` collector calls. The PR
branch was later rebased onto `origin/main` at `6fe5b9c`; that rebase did not
add a new physical-stylus drawing attempt. The device identified as nubia P0110
/ pacific / Android 16 / SDK 36. No device coordination lock was present. The
collector again found one pass-eligible `goodix_stylus_input` candidate
declaring `KEYBOARD | TOUCHSCREEN | STYLUS` plus pressure, orientation, tilt, X,
and Y axes. No physical stylus drawing was performed, no stable
signed/TCC-ready Host preflight was supplied, no Host `Stylus injected:`
observation window was retained, and no visible macOS drawing-app output was
captured. The generated `stylus-summary.json` reports `verdict=blocked` and
`can_close_physical_stylus_gate=false`, so the README drawing-app gate remains
open. The refreshed collector also redacts raw Android window tokens, IPv4
addresses, and URL-style secrets before writing evidence artifacts.

Evidence:

- `evidence/2026-08-29-nubia-p0110-pacific-stylus-current-base-blocked/`:
  current-base fail-closed refresh; status is
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate, no physical drawing observation, no stable signed/TCC-ready Host
  evidence, no Host stylus log, and no drawing-app screenshot.

## 2026-08-30 P0110 current-base blocked refresh

The physical-stylus drawing-app confirmation was rechecked on branch
`codex/stylus-drawing-p0110-20260830` from `origin/main` at
`87e16d8bea4446c1ca449045678f1bafc7fd6cb2`. The connected Android device
identified as nubia P0110 / pacific / Android 16 / API 36. No device
coordination lock was present, and `pgrep -x sfltool || true` returned no
output at start and end. No `/usr/bin/sfltool dumpbtm` command was executed.

`scripts/macos_dev_host.py readiness` reported `status=blocked`,
`signing_tcc_status=blocked`, and `can_start_stylus_gate=false`. Retained
blockers include the missing stable `Vibe Screen Dev` codesigning identity,
failed codesign inspection of the installed Host, no listener on TCP port
`54321`, missing virtual HID entitlement, and unverified Screen Recording and
Accessibility grants.

`scripts/android_stylus_acceptance.py` with the explicit current-base evidence
directory again found one pass-eligible `goodix_stylus_input` candidate
declaring `KEYBOARD | TOUCHSCREEN | STYLUS` plus pressure, orientation, tilt,
X, and Y axes. No physical stylus drawing was performed, no same-session
Android `Stylus forwarded:` samples from a drawing attempt appeared, no Host
`Stylus injected:` excerpt was supplied, and no visible macOS drawing-app
output was captured. The generated `stylus-summary.json` reports
`verdict=blocked` and `can_close_physical_stylus_gate=false`, so the README
physical-stylus drawing-app gate remains open.

Evidence:

- `evidence/2026-08-30-nubia-p0110-pacific-stylus-current-base-blocked/`:
  current-base blocked refresh; status is
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate, no physical drawing observation, no stable signed/TCC-ready Host,
  no Host stylus log, and no drawing-app screenshot. The package retains the
  Nubia P0110/pacific identity, Host readiness blockers, start/end sfltool
  process check, and no `/usr/bin/sfltool dumpbtm` execution.

## 2026-08-31 P0110 current-base blocked refresh

The physical-stylus drawing-app confirmation was rechecked on branch
`codex/stylus-drawing-codex-task-20260831` from `origin/main` at
`28b9d1a59ef026b45ada3cd7e665ef09ea9a7523`. The connected Android device
identified as nubia P0110 / pacific / Android 16 / API 36. `pgrep -x sfltool ||
true` returned no output at start and end. No `/usr/bin/sfltool dumpbtm` command
was executed, and the Host readiness command did not opt in to login-item
diagnostics.

`scripts/macos_dev_host.py readiness` reported `status=blocked`,
`signing_tcc_status=blocked`, and `can_start_stylus_gate=false` while recording
`current_source_dirty=false` for the `28b9d1a59` source snapshot. Retained
blockers include the missing stable `Vibe Screen Dev` codesigning identity,
failed installed-Host codesign inspection for missing WebRTC.framework sealed
resources, no listener on TCP port `54321`, missing virtual HID entitlement,
and unverified Screen Recording and Accessibility grants.

`scripts/android_stylus_acceptance.py` again found one pass-eligible
`goodix_stylus_input` candidate declaring `KEYBOARD | TOUCHSCREEN | STYLUS` plus
pressure, orientation, tilt, X, and Y axes. No physical stylus drawing was
performed, no same-session Android `Stylus forwarded:` samples from a drawing
attempt appeared, no Host `Stylus injected:` excerpt was supplied, and no
visible macOS drawing-app output was captured. The generated
`stylus-summary.json` reports `verdict=blocked` and
`can_close_physical_stylus_gate=false`, so the README physical-stylus
drawing-app gate remains open.

Evidence:

- `evidence/2026-08-31-nubia-p0110-pacific-stylus-current-base-blocked/`:
  current-base blocked refresh; status is
  `blocked_physical_stylus_not_observed` with one pass-eligible capability
  candidate, no physical drawing observation, no stable signed/TCC-ready Host,
  no Host stylus log, and no drawing-app screenshot. The package retains the
  Nubia P0110/pacific identity, Host readiness blockers, clean source
  provenance, start/end sfltool process check, and no `/usr/bin/sfltool dumpbtm`
  execution.

## Tooling change

`scripts/android_stylus_acceptance.py` now writes lock-blocked evidence with
`--write-blocked-on-lock`, and its passing path validates only Host log bytes
appended during the drawing observation window. The appended Host line must
contain a stylus injection plus non-terminal phase, contact, tool, button,
pressure, and signed tilt fields. It also requires a pass-eligible Android
input-device candidate with the
`STYLUS` source and pressure/tilt axes, plus app diagnostic log entries showing
same-session `Stylus forwarded:` samples with sample count, extended-stylus
state, phase, contact state, tool kind, buttons, pressure, and signed tilt. The
Host `Stylus injected:` debug line already includes `tiltX` and `tiltY`, and
the Android stream and Internet forwarding paths now emit matching diagnostic
summaries only after outbound stylus samples are admitted. `dumpsys input`
artifacts now normalize line-ending whitespace so checked-in snapshots remain
compatible with `git diff --check`, while runtime log excerpts keep their
captured bytes.

The collector now also writes `stylus-summary.json`, and
`make physical-stylus-gate` can re-derive it from an existing
`stylus-evidence.json`. The summary is schema-backed and owns the README gate
decision: only `verdict=pass` and `can_close_physical_stylus_gate=true` may
close the physical-stylus drawing-app gate. Capability-only, lock-blocked,
synthetic ADB stylus, missing Host log, missing Android diagnostic log, or
missing stable signed/TCC-ready Host preflight evidence remains blocked;
mislabelled Xiaomi/fuxi identity evidence remains insufficient.

## Verification

```bash
python3 -m unittest scripts.tests.test_release_tools.AndroidStylusAcceptanceTests
PYTHONPATH=tools python3 -m unittest tools.tests.test_stylus
python3 scripts/android_stylus_acceptance.py \
  --serial DEVICE_SERIAL \
  --output-dir docs/changes/2026-08-19-physical-stylus-acceptance/evidence/2026-08-21-nubia-p0110-pacific-stylus-preflight-failclosed \
  --allow-existing-device-lock
make physical-stylus-gate EVIDENCE_DIR=docs/changes/2026-08-19-physical-stylus-acceptance/evidence/<run-dir>
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.StreamInputDispatcherTest \
  --tests dev.telemachus.display.StylusInputMapperTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest.stylusRequiresNegotiationAndValidTerminalPressure
cd ../MacHost
swift build
swift test --filter StylusEventFactoryTests
cd ../..
git diff --check
```

Results:

- Android stylus evidence tool unit tests: 20 tests passed after the 2026-08-21
  fail-closed tightening, hover-only pass rejection coverage, Host phase
  requirement coverage, and `dumpsys input` artifact whitespace normalization.
- P0110 read-only preflight: `blocked_physical_stylus_not_observed` on nubia
  P0110 / pacific / Android 16 / SDK 36, with one pass-eligible
  `goodix_stylus_input` capability candidate but no physical drawing
  observation, no Host stylus log, and no same-session `Stylus forwarded:`
  samples.
- 2026-08-22 P0110 closure attempt: `blocked_physical_stylus_not_observed`
  again on nubia P0110 / pacific / Android 16 / SDK 36, with no device lock,
  one pass-eligible `goodix_stylus_input` candidate, no physical drawing
  observation, no Host stylus log, and no same-session `Stylus forwarded:`
  samples.
- 2026-08-29 P0110 current-base refresh: `blocked_physical_stylus_not_observed`
  again on nubia P0110 / pacific / Android 16 / SDK 36, with no device lock,
  one pass-eligible `goodix_stylus_input` candidate, no physical drawing
  observation, no stable signed/TCC-ready Host evidence, no Host stylus log,
  no same-session `Stylus forwarded:` samples, and no visible drawing-app
  output. The gate summary reports `verdict=blocked` and
  `can_close_physical_stylus_gate=false`.
- 2026-08-30 P0110 current-base blocked refresh:
  `blocked_physical_stylus_not_observed` on nubia P0110 / pacific / Android 16 /
  API 36, with no device lock, one pass-eligible `goodix_stylus_input`
  candidate, `scripts/macos_dev_host.py readiness` blocked on stable signing/
  TCC/listener prerequisites, no physical drawing observation, no Host stylus
  log, no same-session `Stylus forwarded:` samples, and no visible drawing-app
  output. The gate summary reports `verdict=blocked` and
  `can_close_physical_stylus_gate=false`, and `make physical-stylus-gate`
  returned nonzero as expected.
- 2026-08-31 P0110 current-base blocked refresh:
  `blocked_physical_stylus_not_observed` on nubia P0110 / pacific / Android 16 /
  API 36, with one pass-eligible `goodix_stylus_input` candidate, clean
  `origin/main` source provenance at `28b9d1a59`, `scripts/macos_dev_host.py
  readiness` blocked on stable signing/TCC/listener prerequisites, no physical
  drawing observation, no Host stylus log, no same-session `Stylus forwarded:`
  samples, and no visible drawing-app output. The gate summary reports
  `verdict=blocked` and `can_close_physical_stylus_gate=false`, and
  `make physical-stylus-gate` returned nonzero as expected.
- Android focused stylus dispatcher/mapper/protocol tests: Gradle
  `BUILD SUCCESSFUL`.
- MacHost compile check: SwiftPM `Build complete`.
- MacHost focused XCTest command was attempted, but this local toolchain cannot
  compile the test target because `XCTest` is unavailable (`no such module
  'XCTest'` before `StylusEventFactoryTests` executed).
- Whitespace check: `git diff --check` passed.

No general docs verifier target was found in `Makefile`, `scripts`, `tools`, or
`.github`; the existing `evidence_privacy.py` verifier is scoped to Phase 3
Internet evidence and was not applicable to this stylus-readiness record.

## 2026-08-27 P0110 current-base refresh

The latest `origin/main` snapshot at
`3b2ba11e832a3618eaedfc67f92414b161423a00` was rechecked from a clean detached
worktree. Android commands used `adb -s <device-serial>` and the connected
device was recorded as nubia P0110 / pacific / Android 16 / SDK 36. The input
snapshot still exposes `goodix_stylus_input`, including one pass-eligible
candidate with `KEYBOARD | TOUCHSCREEN | STYLUS` plus pressure, orientation,
tilt, X, and Y axes. No physical stylus drawing observation was performed, no
same-session Android `Stylus forwarded:` samples appeared, no Host
`Stylus injected:` excerpt was captured, and no visible macOS drawing-app output
was recorded. The README physical-stylus drawing-app gate remains open.

Evidence:

- [2026-08-27-nubia-p0110-pacific-stylus-current-base-blocked-3b2ba11/stylus-summary.json](evidence/2026-08-27-nubia-p0110-pacific-stylus-current-base-blocked-3b2ba11/stylus-summary.json)
- [2026-08-27-nubia-p0110-pacific-stylus-current-base-blocked-3b2ba11/stylus-evidence.json](evidence/2026-08-27-nubia-p0110-pacific-stylus-current-base-blocked-3b2ba11/stylus-evidence.json)
