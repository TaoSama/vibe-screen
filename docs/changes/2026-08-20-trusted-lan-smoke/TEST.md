# Trusted LAN smoke verification

Status: blocked before LAN stream
Date: 2026-08-20
Target device: Nubia P0110 (`pacific`), Android 16, serial
`<device-serial>`

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
pacific / Android 16 device (`<device-serial>`). The device identity was
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

## 2026-08-22 fail-closed preflight

The current `origin/main` revision `a8346626f07de98a54508c2d05ba138d0c969ef0`
was checked with the new read-only trusted-LAN preflight on the same Nubia P0110
/ pacific / Android 16 device (`<device-serial>`). Wi-Fi was enabled with
`adb -s <device-serial> shell svc wifi enable`, but the device still reported
no Wi-Fi association, `wlan0` remained `NO-CARRIER` / `state DOWN` with no IPv4
address, and Android had no wlan0 route to the Mac LAN candidate. Host stable
signing was also blocked before TCC evaluation because the
`scripts/macos_dev_host.py preflight` command could not find the configured
`Vibe Screen Dev` codesigning identity.

The preflight stopped before Host launch, QR/token admission, secure-record
negotiation, Protocol v1 LAN upgrade, decoder output, reconnect, latency, or
soak evidence. The retained artifact bundle is
[`evidence/2026-08-22-p0110-lan-preflight-blocked/README.md`](evidence/2026-08-22-p0110-lan-preflight-blocked/README.md).

## 2026-08-23 main preflight recheck

After PR #261 merged the fail-closed trusted-LAN preflight to `origin/main`,
commit `392b86882869f9bf431cfd35be834f6cdc15fd37` was rechecked on the same
Nubia P0110 / pacific / Android 16 device (`<device-serial>`). The device
identity was confirmed, but the real LAN smoke remained blocked before Host
launch or pairing: Wi-Fi was enabled but not associated, `wlan0` remained
`NO-CARRIER` / `state DOWN` with no IPv4 address, Android had no `wlan0` route
to the Mac LAN candidate, and Host stable signing was blocked because the
`Vibe Screen Dev` codesigning identity was unavailable.

No trusted-LAN socket admission, secure-record negotiation, Protocol v1 LAN
upgrade, decoder output, reconnect, latency, or soak evidence was observed. The
retained artifact bundle is
[`evidence/2026-08-23-p0110-lan-preflight-main-blocked/README.md`](evidence/2026-08-23-p0110-lan-preflight-main-blocked/README.md).

## Fail-closed preflight

Use the shared Host readiness snapshot and the machine-readable trusted-LAN
preflight before starting the Host, generating a QR/token, or attempting
stream/reconnect evidence:

    make baseline-macos-host-readiness \
      EVIDENCE_DIR=<evidence-dir>

    make evidence-trusted-lan-preflight \
      EVIDENCE_SERIAL=<device-serial> \
      EVIDENCE_DIR=<evidence-dir>

`host-readiness.json` must show `can_start_trusted_lan_gate=true`, and the
trusted-LAN JSON result must be ready before the real smoke can proceed. If any
stage reports blocked, retain `host-readiness.json`,
`host-signing-and-permissions.txt`, and `trusted-lan-preflight.json`, keep the
downstream admission/secure-record/Protocol v1/decoder/reconnect/latency stages
as `not_run`, and do not describe the run as a trusted-LAN pass. The preflights
are read-only: they do not launch the Host, write a pairing token or QR payload,
modify TCC, alter Keychain, clear Android app data, or change saved Wi-Fi
credentials.

## Source-level checks

The current code path was still checked offline so the next device owner has a
clear pass/fail baseline for LAN record protection.

| Check | Result | Notes |
| --- | --- | --- |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Confirms Android token admission codec, secure-record negotiation, control/media record protection, replay/tamper failure, and that the default wireless Protocol v1 probe travels inside a secure LAN record. |
| `make baseline-macos-self-test` | PASS | Builds the release Host and passes host, transport, reliability, Protocol v1, and video encoder self-tests. |
| `cd baseline/MacHost && swift test --filter LANSecureRecordAdapterTests` | BLOCKED | The local developer directory is `/Library/Developer/CommandLineTools`; `xcodebuild` reports that full Xcode is not selected, and the test target fails at `import XCTest` with `no such module 'XCTest'`. |
| `python3 scripts/macos_dev_host.py preflight` | BLOCKED | No `Vibe Screen Dev` codesigning identity is available in the current keychain, so a current-source stable-signed Host bundle cannot be installed or verified for TCC-backed device evidence. |
| `adb -s <device-serial> shell svc wifi enable` followed by Wi-Fi/route probes | BLOCKED | Wi-Fi remained disconnected, `wlan0` had no IPv4 address, and the device could not route to the Mac LAN candidate. |

## Next real-device runbook

Run this only after `/tmp/vibe-screen-device-soak.lock` and
`/tmp/vibe-screen-device-android.lock` are absent and the current task has
atomically created `/tmp/vibe-screen-device-android.lock`. Always use the exact
serial `<device-serial>`.

1. Capture environment: `sw_vers`, `swift --version`, `xcodebuild -version`,
   `git rev-parse HEAD`, `ifconfig`, `lsof -nP -iTCP:54321 -sTCP:LISTEN`,
   and `adb -s <device-serial> devices -l`.
2. Record device identity from `getprop`: serial, manufacturer, model, device
   codename, Android release, SDK, build fingerprint, display size/density,
   battery, and boot state. Label the run only as Nubia P0110 / pacific.
3. Confirm the Android device has a `wlan0` IPv4 address and can route to the
   Mac LAN IPv4 from step 1 before starting the Host.
4. Verify `make baseline-macos-host-readiness EVIDENCE_DIR=<evidence-dir>`
   writes `host-readiness.json` with `can_start_trusted_lan_gate=true` for a
   current-source Host bundle installed at `/Applications/Vibe Screen.app`. If
   the `Vibe Screen Dev` signing identity, source-bound bundle, TCC grants, or
   TCP `54321` listener is missing, recreate/select/fix it before generating
   device acceptance evidence.
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
