# Nubia P0110 USB smoke preflight - BLOCKED

Date: 2026-08-21
Target device serial: `EP0110PZ0B9110300B`
Target identity: nubia / P0110 / pacific / Android 16

## Intended gate

This preflight checked whether the current worktree had an executable path for a
short USB end-to-end smoke on the connected Nubia P0110 Android substitute:
explicit device lease safety, exact ADB serial identity, ADB reverse on TCP
`54321`, foreground Android client, Mac Host listener on TCP `54321`, and the
stable-signed Host/TCC preflight.

## Result

The preflight result is `blocked`. No Host was launched, no ADB reverse mapping
was changed by the tool, no Android app state was modified by the tool, and no
TCC or Keychain state was changed.

Recorded device identity: `nubia / P0110 / pacific / Android 16`.
This is Nubia P0110/pacific evidence only; it is not Xiaomi 13/fuxi evidence.

## Blockers

- Mac Host is not listening on TCP 54321
- macOS Host stable-signing/TCC preflight failed: codesign identity 'Vibe Screen Dev' not found in the keychain. Create the documented stable Code Signing identity or set $VIBE_SCREEN_SIGN_IDENTITY to an existing codesigning identity. For local device reruns, do not use ad-hoc signing; create or select one stable Code Signing identity, then grant Screen Recording and Accessibility to /Applications/Vibe Screen.app.

ADB reverse was already configured as `UsbFfs tcp:54321 tcp:54321`, and the
Android app was running in the foreground as `dev.telemachus.display/.MainActivity`
with PID `11385`; those preconditions are no longer blockers for this run.

## Recovery steps

1. Create or select one stable `Vibe Screen Dev` Code Signing identity, or set
   `VIBE_SCREEN_SIGN_IDENTITY` to an existing stable codesigning identity. Do not
   use ad-hoc signing for device-rerun evidence.
2. Run `make baseline-macos-dev-install`.
3. Grant `/Applications/Vibe Screen.app` Screen Recording and Accessibility in
   System Settings, then relaunch the app.
4. Run `make baseline-macos-touch-preflight` and require it to pass.
5. Start the Host, keep `adb -s EP0110PZ0B9110300B reverse tcp:54321 tcp:54321`
   configured, keep `dev.telemachus.display/.MainActivity` in the foreground,
   then rerun `make evidence-usb-smoke-preflight` before collecting smoke
   evidence.

## Open gates

This blocked preflight does not prove USB streaming, reconnect, input, latency,
soak duration, host RSS no-growth, native pointer HID, physical stylus,
controller runtime, rotated host-display, login startup, or headless Mac
behavior.
