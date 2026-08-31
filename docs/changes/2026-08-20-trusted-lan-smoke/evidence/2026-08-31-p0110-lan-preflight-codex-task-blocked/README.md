# Nubia P0110 trusted-LAN Codex task preflight - BLOCKED

Date: 2026-08-31
Branch: `codex/trusted-lan-codex-task-20260831`
Head commit: `28b9d1a59ef026b45ada3cd7e665ef09ea9a7523`
Target device serial: `<device-serial>`
Device: Nubia P0110 / pacific / Android 16 / SDK 36

## Intended gate

This package refreshes the trusted-LAN stream/reconnect owner record from a
clean worktree created directly from the current `origin/main` revision. The
real-device preflight used the Nubia P0110 / pacific Android substitute with
explicit `adb -s <device-serial>` targeting.

The collector first ran `pgrep -x sfltool`, observed no process, and acquired
the private per-device coordination lock as `<android-device-lock>`. It did
not launch the Host, write a QR payload, write a pairing token, run
instrumentation, modify TCC, alter Keychain, or change Android Wi-Fi
credentials.

## Result

The run is blocked before a real trusted-LAN smoke can start. No real trusted-LAN stream was observed. Reconnect was not exercised.

Confirmed ready prerequisite:

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36.

Blocking prerequisites:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4
  address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4
  candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start. The `Vibe Screen Dev` codesign identity was not found
  in the keychain, the installed `/Applications/Vibe Screen.app` failed
  codesign resource inspection, no TCP `54321` listener was observed, and the
  installed Host did not prove source-bound stable signing or TCC readiness.

The shared Host readiness snapshot reports `can_start_trusted_lan_gate=false`.
It also records that Screen Recording and Accessibility TCC were not evaluated
because stable signing failed.

## Artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed trusted-LAN
  preflight from the current collector, with `repository.dirty=false`,
  `<redacted-ipv4>` network endpoints, and `<android-device-lock>` lock path.
- `host-readiness.json`: shared macOS Host prerequisite readiness snapshot
  with `can_start_trusted_lan_gate=false` and no retained listener output.
- `host-signing-and-permissions.txt`: human-readable Host signing/TCC
  readiness report.
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
- Rebuild/install a source-provenance Host with stable signing and expected
  Host permissions, then establish Host listener readiness for the real runbook.
