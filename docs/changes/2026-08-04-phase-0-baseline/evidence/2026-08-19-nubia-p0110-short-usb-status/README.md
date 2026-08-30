# 2026-08-19 Nubia P0110 Short USB Status - BLOCKED

This minimal evidence record covers only the 2026-08-19 short USB E2E attempt
for device serial `<redacted-adb-serial>`. The device is Nubia `P0110`, codename
`pacific`, running Android 16. It is not Xiaomi 13 or `fuxi` evidence.

## Verdict

**BLOCKED.** The target device had the expected ADB reverse mapping for
`54321`, but the current Host identity failed Screen Recording
`CGPreflight`/TCC checks about every two seconds. The Host auto-start policy did
not open a listener on `54321`, so the client could not complete a current-tree
short USB E2E session.

Historical streams or earlier device runs do not substitute for this current
tree result. This record does not claim a successful stream, Protocol v1
interoperability, input forwarding, reconnect, latency, memory stability, or any
other passing gate.

## Recorded Facts

- Local evidence date: `2026-08-19` in `Asia/Shanghai` (`UTC+08:00`).
- Device: Nubia `P0110` / `pacific` / Android `16`.
- Device serial: `<redacted-adb-serial>`.
- Android APK: package `dev.telemachus.display`, `versionCode 100000`,
  `versionName 0.0.0`, `lastUpdate 2026-08-19 00:07:12` local time.
- ADB reverse: `UsbFfs tcp:54321 tcp:54321` was present for the target serial.
- Host binary: `/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen`.
- Host binary SHA-256:
  `c06424f8580de669db86b7e2efc19adb922d14414ef2cde749fae5ad20ec3996`.
- Host defaults originally pointed at `<redacted-xiaomi-adb-serial>`; during the attempt they were
  temporarily changed to `P0110` and then restored.
- Screen Recording remained blocked for the current Host identity; TCC was not
  reset.

## Boundaries

- No TCC reset was performed.
- Accessibility and input forwarding were not verified.
- The blocked Host listener means no current-tree stream was established.
- The P0110 result is recorded only as P0110/pacific evidence, not as fuxi
  evidence.

## Files

- `acceptance.json` - machine-readable blocked result.
- `commands.txt` - non-destructive command ledger and explicit non-actions.
- `SHA256SUMS` - hashes for the tracked files in this evidence directory.
