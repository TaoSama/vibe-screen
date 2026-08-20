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
