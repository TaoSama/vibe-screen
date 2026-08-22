# Trusted LAN smoke verification

Status: blocked before LAN stream
Date: 2026-08-20
Target device: Nubia P0110 (`pacific`), Android 16, serial
`EP0110PZ0B9110300B`

## Goal

Collect a minimal real-device trusted-LAN smoke record for the current
macOS/Android TCP path: QR/token admission, Protocol v1 over LAN,
per-session AES-256-GCM application records, a short real stream, and reconnect.

## Result

The Android device lease was acquired and the Nubia P0110 identity was recorded,
but the LAN smoke could not start because the device had no Wi-Fi association,
no `wlan0` IPv4 address, and no route to the Mac LAN address candidate. The
current Mac environment also cannot install a current-source, stable-signed Host
bundle for evidence-grade device acceptance because the required `Vibe Screen
Dev` codesigning identity is absent.

No real trusted-LAN stream, secure-record negotiation, decoder output, or
reconnect was observed. This blocked record does not close any README
trusted-LAN stream, reconnect, latency, or stability gate.

Evidence: [`evidence/2026-08-20-p0110-lan-smoke/README.md`](evidence/2026-08-20-p0110-lan-smoke/README.md).

## 2026-08-21 recheck

The current `origin/main` worktree was rechecked on the same Nubia P0110 /
pacific / Android 16 device (`EP0110PZ0B9110300B`). The device identity was
confirmed, but a real LAN smoke remained blocked before Host launch or pairing:
`wlan0` reported `NO-CARRIER` and `state DOWN`, `cmd wifi status` reported
`Wifi is not connected`, `ip route` returned no route, TCP `54321` had no Mac
listener, and `scripts/macos_dev_host.py preflight` still failed because the
`Vibe Screen Dev` codesigning identity was absent from the local keychain.

No trusted-LAN socket admission, secure-record negotiation, decoder output,
reconnect, or latency evidence was observed. The retained artifact bundle is
[`evidence/2026-08-21-p0110-lan-smoke-recheck/README.md`](evidence/2026-08-21-p0110-lan-smoke-recheck/README.md).

Additional current-source checks for this recheck:

| Check | Result | Notes |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Output retained in the 2026-08-21 evidence bundle; covers Android token admission, secure-record negotiation, protected control/media records, and LAN Protocol v1 probe protection. |
| `make protocol` | PASS | Output retained in the 2026-08-21 evidence bundle; covers Protocol v1 schemas, fixtures, and security contract checks. |
| `python3 scripts/macos_dev_host.py preflight` | BLOCKED | Stable Host bundle validation cannot proceed without the configured `Vibe Screen Dev` signing identity. |

## 2026-08-23 route preflight

The latest `origin/main` commit
`de2752e0033713ad48bb7f86960f9180d8e7342f` was rechecked on the same Nubia
P0110 / pacific / Android 16 / SDK 36 device (`EP0110PZ0B9110300B`) using only
read-only Android network queries. The device was available over USB and Wi-Fi
was enabled, but the precondition blocker was unchanged: `cmd wifi status`
reported `Wifi is not connected`, `wlan0` reported `NO-CARRIER` and
`state DOWN`, `wlan0` had no IPv4 address, `ip route` returned no route, and
route lookup plus ping to the Mac LAN IPv4 candidate failed with
`Network is unreachable`. ADB reverse still mapped `tcp:54321` for USB, and the
Mac had no TCP `54321` listener.

The Host evidence preflight also remained blocked: local `xcodebuild` resolves
to Command Line Tools instead of full Xcode, `security find-identity -v -p
codesigning` reports `0 valid identities found`, and
`scripts/macos_dev_host.py preflight` exits `1` because `Vibe Screen Dev` is
not available.

No Host launch, QR/token admission, trusted-LAN socket admission, secure-record
negotiation, Protocol v1 LAN upgrade, decoder output, reconnect, latency, or
stability evidence was attempted or observed. This remains a fail-closed
blocked record and does not close any README trusted-LAN gate. Evidence:
[`evidence/2026-08-23-p0110-lan-route-blocked/README.md`](evidence/2026-08-23-p0110-lan-route-blocked/README.md).

## Source-level checks

The current code path was still checked offline so the next device owner has a
clear pass/fail baseline for LAN record protection.

| Check | Result | Notes |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Confirms Android token admission codec, secure-record negotiation, control/media record protection, replay/tamper failure, and that the default wireless Protocol v1 probe travels inside a secure LAN record. |
| `make baseline-macos-self-test` | PASS | Builds the release Host and passes host, transport, reliability, Protocol v1, and video encoder self-tests. |
| `cd baseline/MacHost && swift test --filter LANSecureRecordAdapterTests` | BLOCKED | The local developer directory is `/Library/Developer/CommandLineTools`; `xcodebuild` reports that full Xcode is not selected, and the test target fails at `import XCTest` with `no such module 'XCTest'`. |
| `python3 scripts/macos_dev_host.py preflight` | BLOCKED | No `Vibe Screen Dev` codesigning identity is available in the current keychain, so a current-source stable-signed Host bundle cannot be installed or verified for TCC-backed device evidence. |
| `adb -s EP0110PZ0B9110300B shell svc wifi enable` followed by Wi-Fi/route probes | BLOCKED | Wi-Fi remained disconnected, `wlan0` had no IPv4 address, and the device could not route to the Mac LAN candidate. |

## Next real-device runbook

Run this only after `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` are absent and the current task has
atomically created `/tmp/vibe-screen-device-android.lock`. Always use the exact
serial `EP0110PZ0B9110300B`.

1. Capture environment: `sw_vers`, `swift --version`, `xcodebuild -version`,
   `git rev-parse HEAD`, `ifconfig`, `lsof -nP -iTCP:54321 -sTCP:LISTEN`,
   and `adb -s EP0110PZ0B9110300B devices -l`.
2. Record device identity from `getprop`: serial, manufacturer, model, device
   codename, Android release, SDK, build fingerprint, display size/density,
   battery, and boot state. Label the run only as Nubia P0110 / pacific.
3. Confirm the Android device has a `wlan0` IPv4 address and can route to the
   Mac LAN IPv4 from step 1 before starting the Host.
4. Verify `scripts/macos_dev_host.py preflight` passes for a current-source Host
   bundle installed at `/Applications/Vibe Screen.app`. If the `Vibe Screen Dev`
   signing identity is missing, recreate/select it before generating device
   acceptance evidence.
5. Build/install the matching Android debug APK if needed. Do not clear app data
   unless the run explicitly records why the previous pairing state was invalid.
6. Start the macOS Host in Wireless mode on a trusted private LAN. Retain
   `~/Library/Logs/Telemachus/telemachus.log` and any `VIBE_SCREEN_TELEMETRY_PATH`
   JSONL.
7. Pair with the Host QR URL or an equivalent captured `telemachus://host:54321`
   URL using the actual Mac LAN IPv4 from step 1. Do not commit the 32-byte
   token or QR payload.
8. Require these non-legacy LAN markers before treating the run as encrypted:
   Host log `Trusted LAN secure records negotiated`; Android diag
   `Wireless connected ... (trusted LAN encrypted records)`; Android telemetry
   `trusted_lan_encrypted=true` and `trusted_lan_legacy_plaintext=false`;
   Protocol v1 upgrade accepted with transport `TRANSPORT_KIND_LAN`.
9. Record first output frame, continuing frame counters, decoder name, no fatal
   codec error, Host PID, and a short disconnect/reconnect sequence with the
   Host PID preserved.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Any long soak or host RSS no-growth claim.
