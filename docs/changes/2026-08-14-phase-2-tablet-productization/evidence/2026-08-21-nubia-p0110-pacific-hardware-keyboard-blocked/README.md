# Phase 2 hardware-keyboard workflow blocked preflight

## Conclusion

- Status: blocked.
- Result: the hardware-keyboard workflow did not run and the Phase 2 gate stays
  open.

## Target device

- Requested serial for a future run: `<redacted-adb-serial>`.
- Required identity label when observed: nubia P0110 / pacific / Android 16.
- ADB was not run because `/tmp/vibe-screen-device-android.lock` already existed
  before this preflight could start.

## Blocking conditions

- `/tmp/vibe-screen-device-android.lock` was present and owned by another run.
- No macOS Host listener was observed on TCP `54321`.
- `security find-identity -v -p codesigning` reported `0 valid identities found`,
  so stable signed Host/TCC readiness could not be established.
- Physical keyboard attachment was not evaluated after those prerequisites
  failed.

## Evidence files

- `device-lock.txt`: lock state and owning run metadata; no ADB commands were
  executed.
- `host-listener.txt`: empty TCP `54321` listener check with exit code `1`.
- `codesign-identities.txt`: local code-signing identity check.
- `host-preflight-command.txt` and `host-signing-and-permissions.txt`: macOS Host
  preflight attempt and output.
- `hardware-keyboard-observations.json`: explicit observed/missing evidence
  inputs.
- `hardware-keyboard-summary.json`: generated gate summary; it records
  `verdict=blocked` and `can_close_hardware_keyboard_gate=false`.

## Next passing run requirements

A passing run needs the shared Android lock, a real attached hardware keyboard,
Nubia P0110/pacific/Android 16 identity evidence for `<redacted-adb-serial>`, an
active Protocol v1 session with keyboard and USB HID modifier-byte capabilities,
Android production forwarding logs, Host `Key injected:` CGEvent logs, paired
press/release and shortcut/modifier evidence, no modifier leak into a later plain
key, and a visible Mac-side result. ADB `input keyevent` may be retained as a
diagnostic but cannot satisfy the physical-keyboard gate.
