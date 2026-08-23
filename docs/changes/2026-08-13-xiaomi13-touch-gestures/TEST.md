# Xiaomi 13 touch-gesture end-to-end verification

Date: 2026-08-13

## Scope and identity

This record exercises the real Android `MainActivity` input view through the
active Protocol v1 USB session and observes the resulting macOS CGEvents. It is
not physical-finger evidence: an opt-in instrumentation test constructs standard
touchscreen `MotionEvent` sequences inside the installed application, and the
production client mapping, transport, host gesture recognizer, Accessibility
gate, and CGEvent posting remain in the path.

- Source base: `244c5a290fe0a4e6eb9b2ca2899571bd850375e1`
- Device: Xiaomi 13, model `2211133C`, codename `fuxi`, Android 16 / API 36
- Device endpoint: private ADB-over-network endpoint, intentionally omitted
- Display state: physical `1080x2400`, density `420`
- Debug APK SHA-256: `74e599cf670ff99c88341ab233d4153e5e488be82c969df1f81f70f58f2d255c`
- Test APK SHA-256: `23d6533ad68e0c416ef016ad9f28eec379f8a921fa21807dccf7460115909a05`
- Original authorized Host binary SHA-256:
  `6f862d16b901580e5db0475a449c59f16453f964a74bdcb5dec4b519458b17bf`

The test is fail-safe by default. It is skipped unless the runner receives
`-e vibeScreenTouchE2E true`; ordinary CI and full instrumentation runs cannot
inject gestures into a user's Mac accidentally.

## Reproduction and finding

The opt-in acceptance driver passed twice (`OK (1 test)`, 5.722 seconds and
5.627 seconds), confirming that the connected production input view accepted
the following sequence in order:

1. tap: left mouse down/up;
2. long press: right mouse down/up;
3. long press followed by motion: left down/drag/up;
4. two-finger parallel motion: plain scroll event;
5. two-finger distance change: Command-modified scroll event for zoom.

The driver's return value is not a Host acknowledgement. Synchronized Host
observations supply the end-to-end evidence: the Host log independently
recorded `right click injected`, `drag began`,
`drag ended`, `two-finger scroll began`, and `pinch began` in both runs while
the pipeline returned to 60 FPS with zero reported drops. A listen-only macOS
event tap observed event types `1/2` (left down/up), `3/4` (right down/up), `6`
(left drag), and `22` (scroll). The plain two-finger scroll carried no Command
modifier in the first run; the zoom scroll did.

The repeat run exposed a production defect: after the first run's pinch, the
shared `CGEventSource` retained the Command flag. The next run's ordinary click,
right click, and drag arrived with Command set. This could turn the next user
gesture into an application shortcut after pinch-to-zoom.

## Fix and verification boundary

Pinch zoom now uses a private CGEvent source for its synthetic Command-scroll,
while ordinary touch and native pointer events retain the system-state source
and its legitimate physical modifiers. `Phase1HostCapabilityTests` covers the
source isolation and event flags, and the focused test plus a complete debug
build pass.

The final fixed Host binary SHA-256 is
`065a35aa3a299f4f704855e0e18a7246a1ba32bbe12faebc84646ac638dff70a`.
An earlier permission probe used intermediate fixed binary
`a96edf6d615026e771842481df932fde7e0b5a9f3a6bcfbeb1ac0a1a093080fc`.
The fixed bundle was tried both from its new build directory and copied to the
previous Host path. macOS rejected Screen Recording for the new ad-hoc binary in
both cases (`Screen recording permission not granted yet`). The original bundle
was restored byte-for-byte and resumed the stream. Therefore this record proves
the original end-to-end gesture paths, reproduces the modifier leak, and provides
offline coverage for the fix; it does **not** claim a fixed-binary device pass.
A fixed-binary pass remains gated on granting Screen Recording and Accessibility
to that exact binary or configuring the documented stable signing identity.

The formal native HID mouse confirmation and physical-finger/manual UX pass also
remain separate gates.

## Fixed stable-signed binary rerun

The 2026-08-16 Xiaomi 13 rerun built the then-current `main` source with the
stable `Vibe Screen Dev` identity and reached Protocol v1 streaming, but the
read-only TCC check showed Screen Recording authorized and Accessibility not
authorized for the Host. Because the production touch path rejects input when
`AXIsProcessTrusted()` is false, the opt-in gesture driver was not run and all
five gestures, including the post-pinch modifier-isolation check, remain
blocked. See the
[blocked rerun evidence](evidence/2026-08-16-xiaomi13-fuxi-fixed-binary-blocked/README.md).

The 2026-08-20 rerun on the Nubia P0110/pacific Android substitute started from
`origin/main` commit `b9d768e55c75f03cd3cb5d20939576bc8d24ff27` and used the
currently installed stable-signed Host binary with SHA-256
`c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`. The
read-only preflight reported `ready`: the installed Host hash matched the
expected value, Screen Recording and Accessibility were both authorized for
`dev.telemachus.display`, and the explicit Android identity was recorded as
nubia P0110 / `pacific` / Android 16 / API 36 / serial
`EP0110PZ0B9110300B`. The opt-in gesture driver passed three times, including
the final synchronized event-tap run (`OK (1 test)`, 51.539 seconds). Host logs
recorded Protocol v1 with `touch=on`, `right click injected`, `drag began`,
`drag ended`, `two-finger scroll began`, and `pinch began`; the listen-only
macOS event tap observed left down/up, right down/up, left drag, plain scroll
with `command=false`, and pinch zoom scroll with `command=true`. The first
plain click in that final run also recorded `command=false` after the previous
completed pinch run, covering the fixed-binary modifier-isolation regression.
See the
[P0110 rerun evidence](evidence/2026-08-20-p0110-pacific-fixed-binary-rerun/README.md).

This closes the fixed stable-signed binary rerun for a general Android
substitute device. It does not replace or relabel Xiaomi 13/fuxi evidence, and
the formal native HID mouse confirmation plus physical-finger/manual UX pass
remain separate gates.

Before any future short rerun, collect a read-only preflight so a blocked state
is recorded without launching the Host, running instrumentation, resetting TCC
or Keychain state, clearing Android app data, or starting a soak:

```bash
make evidence-touch-rerun-preflight \
  EVIDENCE_SERIAL=<adb-serial> \
  EVIDENCE_DIR=docs/changes/2026-08-13-xiaomi13-touch-gestures/evidence/<date-device-fixed-binary-preflight> \
  TOUCH_RERUN_EXPECTED_HOST_SHA256=<fixed-host-binary-sha256>
```

The preflight reads both the current-user and system TCC databases by default,
because modern macOS releases may store Screen Recording and Accessibility rows
outside the user database. The output records which database supplied each row.

Proceed to the opt-in gesture driver only when the preflight result is `ready`:
the installed Host binary hash matches the expected fixed binary, Screen
Recording and Accessibility are both authorized for `dev.telemachus.display`,
and the explicit Android device identity is recorded. If any precondition is
missing, keep the result as blocked evidence. A Nubia P0110/pacific may be used
as a general Android substitute, but the evidence title, device table, and
claims must name Nubia P0110/pacific rather than Xiaomi 13/fuxi.

## Gesture-to-action mapping current-base offline slice

Date: 2026-08-23
Source base: `origin/main` commit `d75758fbb3e21d0ac91af82692d5e5233699e900`

This slice wires Android-side three-finger vertical swipe shortcuts to the
existing Protocol v1 HostAction path without changing the MacHost action
catalog. The Android settings dialog persists independent three-finger swipe-up
and swipe-down choices, defaults both choices to the existing touch behavior,
and exposes only the current known Host actions: `move-window` and
`return-windows`. Unknown HostAction catalog entries are filtered out of the
menu and denied by the gesture policy even if a malformed profile advertises
them.

The production touch path remains fail-closed. A default profile does not
intercept three-finger input. Once a non-default shortcut is selected, the
Android client treats the sequence as a shortcut candidate, caches touch samples
until the swipe direction is known, resolves the gesture against negotiated
HostAction capability, the latest managed policy, and the filtered catalog, and
only cancels the original touch stream when the resolved decision denies or
invokes a HostAction. If the resolved direction is still default, the cached
touch samples are replayed and the rest of the sequence follows the ordinary
touch path. Internet sessions are deliberately excluded from this shortcut path
for the current USB/LAN slice.

Offline verification for this slice:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests 'dev.telemachus.display.GestureHostActionPolicyTest' \
  --tests 'dev.telemachus.display.HostActionMenuPolicyTest' \
  --tests 'dev.telemachus.display.SessionStateTest' \
  --tests 'dev.telemachus.display.ClientInputDispatchTest' \
  --tests 'dev.telemachus.display.MainActivityControllerForwardingContractTest'
```

Result: `BUILD SUCCESSFUL` on 2026-08-23. The focused tests cover default
non-interception, saved choice to HostAction ID mapping, unknown-action
fail-closed behavior, filtered HostAction availability, managed-policy update
plumbing, and source-level ordering that resolves custom gestures before
ordinary touch forwarding.

Android device-side settings verification also ran on nubia P0110 / `pacific`
/ Android 16 / SDK 36 / serial `EP0110PZ0B9110300B` with an emulator also
connected, so installation and execution used the explicit P0110 serial:

```bash
cd baseline/AndroidClient
./gradlew --no-daemon assembleDebugAndroidTest
adb -s EP0110PZ0B9110300B install -r app/build/outputs/apk/debug/app-debug.apk
adb -s EP0110PZ0B9110300B install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s EP0110PZ0B9110300B shell am instrument -w -r \
  -e class dev.telemachus.display.SettingsDialogLayoutInstrumentedTest,dev.telemachus.display.GestureShortcutPreferencesInstrumentedTest \
  dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner
```

Result: `OK (8 tests)` on 2026-08-23. This validates the settings dialog
responsive layout and SharedPreferences round trip for the new shortcut choices
on the named Android device only; it is not Host-action execution evidence.

This does not close the real-device gesture-to-action gate. No 2026-08-23 run
captured a physical or opt-in instrumentation three-finger swipe on nubia P0110
/ `pacific` / Android 16 / SDK 36 invoking a visible Mac window action through
the Host. A future evidence package must record the real Android device
identity, installed Android and Host build hashes, Host Screen Recording and
Accessibility state, Protocol v1 HostAction catalog and managed-policy state,
the explicit shortcut settings used, HostActionResult acceptance, and visible
Mac-side `move-window` or `return-windows` output before this gate can be
reported as passed.
