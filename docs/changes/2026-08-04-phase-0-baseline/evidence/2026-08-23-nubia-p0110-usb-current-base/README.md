# 2026-08-23 Nubia P0110 current-base USB attempt - INSUFFICIENT

This evidence record covers an attempted Android USB end-to-end current-base
verification on the connected Nubia P0110 (pacific) device, serial
`EP0110PZ0B9110300B`, running Android 16 / SDK 36. It is P0110/pacific evidence
only; it is not Xiaomi 13/fuxi evidence.

## Verdict

**INSUFFICIENT.** The repository HEAD matched `origin/main` at
`50694049096783466481f418c41a5eb50740e871`, the Android debug APK was installed
on the explicitly selected P0110 target, and `adb reverse tcp:54321 tcp:54321`
was present. The current-base Host did not provide a usable `54321` listener
for this run, and the available artifacts are not enough to isolate a single
root cause:

- `make baseline-macos-touch-preflight` failed because the local keychain did
  not contain the stable `Vibe Screen Dev` codesigning identity required by the
  documented TCC-stable local Host install/preflight path. This blocks that
  supported preflight path, but ad-hoc apps can still be started manually if
  their current code-signing identity has Screen Recording permission.
- The current-source `.app` built with ad-hoc signing did start as PID `91012`,
  but no `54321` listener was observed for that process. The retained artifacts
  do not prove whether the immediate cause was Screen Recording/TCC state, local
  port/process state, or another Host startup condition.
- The installed `/Applications/Vibe Screen.app` process was observed, but it was
  not used as current-base evidence because its binary hash did not match the
  current worktree artifacts.
- The final read-only `usb_live_smoke` helper returned `insufficient` because
  the Android package was not running, was not foregrounded, and current-process
  logcat contained no `stream_stats` or MediaCodec decoder output.

This attempt does not prove USB streaming, Protocol v1 interoperability,
decoder output, reconnect, or app lifecycle recovery for current-base commit
`50694049096783466481f418c41a5eb50740e871`. It only records the current blocker
conditions and the fail-closed evidence-tool result.

## Recorded Facts

- Branch: `codex/nubia-p0110-usb-current-base`.
- Repository commit and base: `50694049096783466481f418c41a5eb50740e871`
  (`origin/main`).
- Device: nubia P0110, codename/product pacific, Android 16, SDK 36,
  fingerprint
  `nubia/pacific/pacific:16/BQ2A.250705.001-BP2A.250605.031.A3/20260306.003030:userdebug/test-keys`.
- A second Android device was connected, so every recorded device command used
  `adb -s EP0110PZ0B9110300B` explicitly.
- Current-tree Host executable:
  `baseline/MacHost/.build/release/Vibe Screen`, SHA-256
  `93b91e1fa22f41f4531efd43d37b8cc431be06c3e67c5f0379e0ef0c8c4ff57f`.
- Current-tree ad-hoc Host app executable:
  `.build/current-usb-host-app/Vibe Screen.app/Contents/MacOS/Vibe Screen`,
  SHA-256
  `2c840bcd2cd91b7ca180b63aaa8b1387bf2adabf97d7d8cf0816a9f14dc30a30`.
- Current-tree Android debug APK:
  `baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk`, SHA-256
  `938127a75b82072b35d6e09cc123c9eda9635ee130fba3052fd8e11dddfc16b5`.
- APK install returned `Success` and ADB reverse listed
  `UsbFfs tcp:54321 tcp:54321`.
- Final `usb-live-smoke-final.json` verdict: `insufficient`.

## Files

- `acceptance.json` - machine-readable insufficient result and explicit non-claims.
- `device-info.json` - target Android identity and package metadata.
- `artifact-sha256.txt`, `artifact-ls.txt` - current Host/APK artifact identity.
- `host-preflight-console.txt`, `baseline-macos-touch-preflight.txt`,
  `baseline-macos-touch-preflight.exit` - stable Host signing preflight failure.
- `current-host-codesign.txt`, `current-app-codesign.txt` - Host executable and
  ad-hoc app signing details.
- `host-process*.txt`, `host-listener*.txt`, `current-app-process*.txt`,
  `current-app-listener*.txt` - Host process/listener observations.
- `adb-install.txt`, `adb-reverse.txt`, `adb-reverse-set.txt` - APK install and
  USB reverse state.
- `usb-live-smoke-final.json`, `usb-live-smoke-final.exit` - read-only helper
  result.
- `test-usb-live-smoke.txt`, `test-usb-live-smoke.exit` - parser/helper unit
  test output.
- `commands.txt` - command ledger for the active attempt.
- `device-lock-*.txt` - Android device lock ownership and release notes.

## Commands

Representative commands used for this evidence:

```bash
make evidence-device-info \
  EVIDENCE_SERIAL=EP0110PZ0B9110300B \
  EVIDENCE_DIR=docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-23-nubia-p0110-usb-current-base

make baseline-android-apk

cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest

adb -s EP0110PZ0B9110300B install -r -t \
  baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk

adb -s EP0110PZ0B9110300B reverse tcp:54321 tcp:54321

make baseline-macos-touch-preflight

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m unittest tools.tests.test_usb_live_smoke -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
  python3 -m vibescreen_evidence.usb_live_smoke \
  --serial EP0110PZ0B9110300B \
  --package dev.telemachus.display \
  --port 54321 \
  --allow-existing-device-lock \
  --output docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-23-nubia-p0110-usb-current-base/usb-live-smoke-final.json
```

The full command/output ledger is retained in `commands.txt` and the per-command
artifacts above.

## Boundaries

- This is an insufficient current-base attempt, not a successful USB stream.
- The record does not close USB stream, reconnect, decoder, app lifecycle,
  two-hour soak, Host RSS no-growth, native pointer HID, physical stylus,
  controller runtime, external-camera latency, input-latency, rotated
  host-display, login-startup, headless Mac, LAN, Internet, or AV1 gates.
- The P0110 result is recorded only as P0110/pacific evidence and must not be
  relabeled as Xiaomi 13/fuxi evidence.
- The final read-only helper did not install, launch, stop, clear logcat, create
  reverse mappings, probe the Host listener, or inject input.
