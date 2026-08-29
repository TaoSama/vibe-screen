# Nubia P0110 trusted-LAN current-base preflight - BLOCKED

Date: 2026-08-29
Branch: `codex/trusted-lan-current-base-evidence`
Head commit: `2da3f86e24cf51c6966dcea7848f55623cb67a40`
Target device serial: `<device-serial>`
Device: nubia P0110 / pacific / Android 16 / SDK 36

## Intended gate

This package refreshes the current-base trusted-LAN stream/reconnect owner
record after hardening the readiness tooling redaction. The real-device
preflight ran against the Nubia P0110 / pacific Android substitute over explicit
`adb -s <device-serial>` targeting.

The collector first ran `pgrep -x sfltool`, observed no process, and acquired
the private per-device coordination lock as `<android-device-lock>`. It did not
run a login-item diagnostic, launch the Host, write a QR payload, write a
pairing token, run instrumentation, modify TCC, alter Keychain, or change
Android Wi-Fi credentials.

## Result

The run is blocked before a real trusted-LAN smoke can start. No real trusted-LAN stream was observed. Reconnect was not exercised.

Confirmed ready prerequisite:

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36.

Blocking prerequisites:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4
  candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

The shared Host readiness snapshot reports `can_start_trusted_lan_gate=false`.
It also records that Screen Recording and Accessibility TCC were not evaluated
because stable signing failed. The only observed TCP `54321` listener was
loopback-only and is not LAN listener evidence.

## Artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed trusted-LAN
  preflight from the updated collector, with `repository.dirty=false`,
  `<redacted-ipv4>` network endpoints, and `<android-device-lock>` lock path.
- `host-readiness.json`: shared macOS Host prerequisite readiness snapshot with
  `can_start_trusted_lan_gate=false` and redacted listener output.
- `host-signing-and-permissions.txt`: human-readable Host signing/TCC readiness
  report.
- `reconnect-timing-summary.json`: blocked reconnect timing summary with
  `can_close_timing_gate=false` and no disruption exercised.
- `commands.txt`: command summary; every Android command used
  `adb -s <device-serial> ...`.
- `*.exit`: captured exit codes. Exit code `2` means trusted-LAN or Host
  readiness was blocked; exit code `3` means reconnect timing was blocked.
- `SHA256SUMS`: hashes for retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, raw IPv4 address, real
Android serial, operator home path, TCC database path, private key, SSH user, or
secret is retained in this evidence package.

## Gate impact

This record does not close the README trusted-LAN stream/reconnect gate. The
preflight claims remain fail-closed: `can_start_trusted_lan_smoke=false`,
`real_lan_stream=false`, `trusted_lan_encrypted=false`, `reconnect=false`,
`latency=false`, and `stability=false`.

Remaining blockers before a real LAN smoke may start:

- Associate the Nubia P0110/pacific device to Wi-Fi and confirm `wlan0` IPv4.
- Confirm Android routes to a Mac LAN IPv4 candidate over `wlan0`.
- Rebuild/install a source-provenance Host with stable signing and the expected
  Host permissions, then establish Host listener readiness for the real runbook.
