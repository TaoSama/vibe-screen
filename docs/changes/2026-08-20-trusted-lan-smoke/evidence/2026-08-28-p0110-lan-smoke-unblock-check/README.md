# Nubia P0110 trusted-LAN unblock readiness check - BLOCKED

Date: 2026-08-28
Branch: `codex/lan-smoke-unblock-check`
Base commit: `27d2b0e493e807ae439fbd43b06b4c2f0ce9c503`
Target device serial: `<device-serial>`

Device: nubia P0110 / pacific / Android 16 / SDK 36.

## Scope

This package is a read-only unblock readiness check for the trusted-LAN smoke
gate on the Nubia P0110 / pacific / Android 16 device. It started from the
current `origin/main` commit in a clean worktree. The preflight evidence records
`repository.dirty=false` and the same source revision as `origin/main`.

The Android device was accessed only through the explicit serial
`adb -s <device-serial>` while holding
`/tmp/vibe-screen-android-<device-serial>.lock`. No Host launch, QR payload,
pairing token, instrumentation, reconnect exercise, latency capture, TCC write,
Keychain mutation, Wi-Fi credential change, or long stream was attempted. The
mandatory `pgrep -x sfltool || true` precheck produced no process ID, and no
`sfltool dumpbtm` or sfltool opt-in command was run.

## Result

The readiness check is blocked before a trusted-LAN smoke can start. No real trusted-LAN stream was observed.

Confirmed ready prerequisite:

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36.

Blocking prerequisites:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4
  candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

The separate Host readiness snapshot also reports
`can_start_trusted_lan_gate=false`. Its blockers include the missing
`Vibe Screen Dev` codesigning identity, missing installed Host source
provenance, unreadable TCC databases during read-only verification, no TCP
`54321` Host listener, missing virtual HID entitlement, and unverified
login/headless readiness.

## Artifacts

- `trusted-lan-preflight.json`: machine-readable read-only preflight result.
- `trusted-lan-preflight-tool-verification.json`: dirty-state rerun proving the
  updated collector records the `pgrep -x sfltool` precheck and serial-specific
  Android device lock before ADB; it is tool-behavior evidence and does not
  replace the clean-base readiness result.
- `host-readiness.json`: shared macOS Host prerequisite readiness snapshot.
- `host-signing-and-permissions.txt`: human-readable Host signing/TCC details.
- `preflight-command.txt` and `preflight-command.exit`: trusted-LAN preflight
  command output and exit code. Exit code `2` means blocked evidence was written.
- `tool-verification-preflight-command.txt` and
  `tool-verification-preflight-command.exit`: updated collector command output
  and exit code for the dirty-state tool verification rerun.
- `host-readiness-command.txt` and `host-readiness-command.exit`: Host readiness
  command output and exit code. Exit code `2` means blocked readiness.
- `device-lock.txt`: local lock acquisition record for the device serial.
- `commands.txt`: command and validation summary.
- `SHA256SUMS`: artifact hashes.

## Gate impact

This record does not close the trusted-LAN README gate. The JSON claims remain
fail-closed: `can_start_trusted_lan_smoke=false`, `real_lan_stream=false`,
`trusted_lan_encrypted=false`, `reconnect=false`, `latency=false`, and
`stability=false`.

Remaining blockers before a real LAN smoke may start:

- Associate the Nubia P0110/pacific device to Wi-Fi and confirm `wlan0` IPv4.
- Confirm Android routes to a Mac LAN IPv4 candidate over `wlan0`.
- Rebuild/install a source-provenance Host with stable signing and the expected
  Host permissions, then establish Host listener readiness as required by the
  real runbook.
