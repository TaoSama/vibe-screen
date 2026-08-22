# Phase 2 hardware-keyboard workflow blocked preflight

## Conclusion

- Status: blocked.
- Result: the hardware-keyboard workflow did not run and the Phase 2 gate stays
  open.

## Target device

- Serial: `EP0110PZ0B9110300B`.
- Observed identity: nubia P0110 / codename pacific / Android 16 (SDK 36).
- The device identity matches the required label and must not be relabeled as
  Xiaomi 13/fuxi or as tablet hardware.

## Observed preconditions

- The shared Android device lock
  (`/tmp/vibe-screen-device-android.lock`) was acquired for this run.
- `dumpsys input` lists only built-in key devices (`gpio-keys`, `pmic_pwrkey`,
  `pmic_resin`, `qbt_key_input`, `goodix_stylus_input`, `gdix_input_agent`,
  `sun-qrd-sku2-snd-card Button Jack`) and the virtual keyboard. No external
  hardware keyboard is attached.
- A macOS Host listener is present on TCP `54321`.
- `security find-identity -v -p codesigning` reports `0 valid identities
  found`, so a stable signed Host with Screen Recording and Accessibility TCC
  grants cannot be established.

## Blocking conditions

- No physical keyboard is attached to the Android device. ADB `input keyevent`
  may be retained as a diagnostic but cannot satisfy the physical-keyboard gate.
- The local keychain has no valid code-signing identity, so the Host cannot be
  stable-signed and Screen Recording / Accessibility TCC grants cannot be
  reliably confirmed.

Because both blocking prerequisites failed, Protocol v1 keyboard and USB HID
modifier-byte capability negotiation, Android production keyboard forwarding,
Host `Key injected:` CGEvent logs, paired press/release and shortcut/modifier
evidence, modifier-release cleanup, and the visible Mac-side result were not
collected.

## Evidence files

- `device-lock.txt`: lock state and owning run metadata.
- `device-identity.txt`: observed manufacturer, model, codename, OS release,
  and SDK for `EP0110PZ0B9110300B`.
- `dumpsys-input.txt`: Android input device snapshot; no external keyboard
  source is present.
- `host-listener.txt`: TCP `54321` listener check.
- `codesign-identities.txt`: local code-signing identity check.
- `host-preflight-command.txt` and `host-signing-and-permissions.txt`: macOS
  Host preflight attempt and output.
- `hardware-keyboard-observations.json`: explicit observed/missing evidence
  inputs.
- `hardware-keyboard-summary.json`: generated gate summary; it records
  `verdict=blocked` and `can_close_hardware_keyboard_gate=false`.

## Next passing run requirements

A passing run needs:

1. a real external hardware keyboard attached to the Android device and named
   in `dumpsys input`;
2. the shared Android device lock;
3. nubia P0110/pacific/Android 16 identity evidence for
   `EP0110PZ0B9110300B`;
4. an active Protocol v1 session with keyboard and USB HID modifier-byte
   capabilities negotiated;
5. Android production forwarding logs from `MainActivity`/`StreamClient`;
6. a stable signed macOS Host with Screen Recording and Accessibility
   permission ready;
7. Host `Key injected: hid=<usage> pressed=<true|false> modifiers=<mask>`
   CGEvent logs covering paired press/release events;
8. at least one shortcut/modifier combination reaching the Host;
9. proof that modifiers clear after shortcut release and do not leak into a
   later plain key;
10. a visible Mac-side result captured by screenshot, screen recording, or a
    retained app log.

ADB `input keyevent` may be retained as a diagnostic but cannot close the
physical-keyboard gate.
