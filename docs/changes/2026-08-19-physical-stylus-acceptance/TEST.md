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

The target Android serial was `EP0110PZ0B9110300B`, which was previously
identified in this change as nubia P0110 / pacific / Android 16 / SDK 36. This
run did not execute ADB capability collection because
`/tmp/vibe-screen-device-android.lock` already existed before the acceptance
script could start.

Evidence:

- `evidence/2026-08-19-nubia-p0110-pacific-stylus-blocked/`: existing device
  capability snapshot; P0110 exposes `goodix_stylus_input` with pressure and
  tilt axes, but no physical drawing was observed.
- `evidence/2026-08-20-nubia-p0110-pacific-stylus-lock-blocked/`: lock-blocked
  readiness record; no ADB commands were run and no physical stylus event was
  observed.

## Tooling change

`scripts/android_stylus_acceptance.py` now writes lock-blocked evidence with
`--write-blocked-on-lock`, and its passing path validates that the supplied Host
log contains a stylus injection plus contact, button, pressure, and signed tilt
fields. The Host `Stylus injected:` debug line now includes `tiltX` and `tiltY`
so the pass criteria can be checked from retained logs.

## Verification

```bash
python3 -m unittest scripts.tests.test_release_tools.AndroidStylusAcceptanceTests
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.StylusInputMapperTest \
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest.stylusRequiresNegotiationAndValidTerminalPressure
cd ../MacHost
swift build
cd ../..
git diff --check
```

Results:

- Android stylus evidence tool unit tests: 8 tests passed.
- Android focused stylus mapper/protocol tests: Gradle `BUILD SUCCESSFUL`.
- MacHost compile check: SwiftPM `Build complete`.
- Whitespace check: `git diff --check` passed.

No general docs verifier target was found in `Makefile`, `scripts`, `tools`, or
`.github`; the existing `evidence_privacy.py` verifier is scoped to Phase 3
Internet evidence and was not applicable to this stylus-readiness record.
