# Hardware Keyboard Workflow Acceptance

This runbook owns only the Phase 2 Android-attached hardware keyboard workflow.
It does not close the generic peripheral framework, native pointer, stylus,
controller, physical-tablet, or eight-hour soak gates.

## Scope

A pass requires a real USB, Bluetooth, or pogo-pin Android hardware keyboard
that Android reports as an external, non-virtual keyboard on the recorded device
while a production Protocol v1 session is actively streaming the selected Mac
display. Synthetic input such as `adb shell input keyevent`, JVM mapper tests,
emulator input, or hand-written Protocol v1 envelopes can prove readiness only.
Built-in Android key devices such as `gpio-keys` are not accepted for this
workflow unless Android reports them as external, non-virtual input devices.

For the shared Nubia phone, every Android command must use the explicit local
ADB serial, but public artifacts should write it as `<device-serial>`:

```bash
adb -s <device-serial> ...
```

Evidence from that device must be labeled as nubia P0110 / pacific / Android 16
/ SDK 36, never as another device or as physical 8-9 inch tablet evidence.

## Preconditions

Before touching ADB, confirm no shared Android lease is active:

```bash
test ! -e /tmp/vibe-screen-device-soak.lock
test ! -e /tmp/vibe-screen-device-android.lock
```

If another task owns a lock, write a blocked readiness bundle with
`--write-blocked-on-lock` instead of probing the device. If the lock is clear,
the readiness collector will acquire `/tmp/vibe-screen-device-android.lock` and
release it after collection.

The pass environment must include all of these: a named physical Android
keyboard, installed Android client identity, a stable signed macOS Host bundle
at `/Applications/Vibe Screen.app` with bundle id `dev.telemachus.display`, the
pinned signing leaf SHA-1
`9AAE572BF6D764E3436A6109197D345B5A87998C`, clean source provenance
(`VibeScreenSourceDirty=false` with matching source commit/tree), Screen
Recording, Accessibility, and Microphone permissions for that exact app
identity, a Host listener on the transport under test, an active selected
display stream, and Protocol v1 keyboard plus USB HID modifier-byte capability
negotiation.

## Readiness Bundle

Collect current-base readiness before the physical workflow attempt:

```bash
make hardware-keyboard-readiness \
  EVIDENCE_SERIAL=<device-serial> \
  EVIDENCE_DIR=docs/changes/2026-08-14-phase-2-tablet-productization/evidence/YYYY-MM-DD-nubia-p0110-pacific-hardware-keyboard-readiness
```

The collector records device identity, APK identity, `dumpsys input`, Host
listener state, signing identities, and Host permission preflight. It does not
press keys or prove acceptance. A nonzero blocked or insufficient exit is
expected when hardware or Host prerequisites are missing.

## Passing Evidence

A passing `hardware-keyboard-observations.json` must set every observation in
`tools/schemas/hardware-keyboard.schema.json` to `true`. Retain at least these
artifacts in the same evidence directory:

- `device-info.json`, `adb-devices.txt`, and `dumpsys-input.txt` with the exact
  Android device and keyboard identity.
- Android production logs showing `MainActivity` / `StreamClient` keyboard
  forwarding from real Android `KeyEvent` input while the Activity is focused.
- Evidence that IME composition, background Activity state, or Android system
  keys did not masquerade as accepted forwarded keyboard events.
- Protocol v1 logs showing keyboard and USB HID modifier-byte capabilities.
- Active selected-display or stream evidence from the same session window.
- Host listener and stable signed/TCC preflight records for the exact Host
  binary under test.
- Host-side `Key injected:` lines or acknowledgement/CGEvent logs for the
  claimed key-down, key-up, modifier, and shortcut events.
- A visible Mac result, screenshot, recording, or written observation from a
  non-sensitive focused Mac target proving text insertion or shortcut behavior.

Exercise at minimum: a plain key press/release pair, a modifier press/release
pair, one shortcut combination, and a later plain key proving modifier cleanup.
Run the summary gate afterward:

```bash
make hardware-keyboard-gate EVIDENCE_DIR="$RUN_DIR"
```

Only `verdict=pass` with `can_close_hardware_keyboard_gate=true` can close the
Phase 2 hardware-keyboard workflow. `blocked` and `insufficient` summaries are
valid retained evidence that the gate remains open.
