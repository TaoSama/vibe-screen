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
