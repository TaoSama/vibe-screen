# Nubia P0110 trusted-LAN current-main preflight - BLOCKED

Date: 2026-08-27
Base commit: `3b2ba11e832a3618eaedfc67f92414b161423a00`
Target device serial: `<device-serial>`
Device: nubia P0110 / pacific / Android 16 / SDK 36

## Intended gate

This run started after `git fetch origin --prune` with the local checkout at the
same revision as `origin/main`. The read-only trusted-LAN preflight was rerun
against a clean detached `origin/main` worktree so generated evidence files did
not make the repository provenance appear dirty.

The goal was to determine whether the real Nubia P0110 device and the macOS
Host were ready to start a trusted-LAN stream/reconnect acceptance pass. The
preflight stops before Host launch, QR/token admission, secure-record
negotiation, Protocol v1 LAN upgrade, decoder output, or reconnect exercise.

## Result

The run is blocked before a real trusted-LAN smoke can start. The device
identity was confirmed as nubia P0110 / pacific / Android 16 / SDK 36, but the
preflight JSON records these blockers:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4
  candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

The Mac firewall was disabled, but the only observed TCP `54321` listener was a
loopback listener on `127.0.0.1`, which is not LAN evidence. The Host readiness
record also reports `can_start_trusted_lan_gate=false`; Screen Recording and
Accessibility TCC could not be evaluated for a valid evidence-grade Host bundle
because the stable signing precondition failed.

Because the preflight returned `blocked`, no real trusted-LAN stream was
observed. No Host was launched for this evidence, no QR payload or pairing token
was written, no secure records were negotiated, no Protocol v1 LAN session was
admitted, no decoder output was observed, and reconnect was not exercised. This
package does not close the README trusted-LAN stream, reconnect, latency,
stability, or Host RSS gates.

## Captured artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed preflight result
  with clean `origin/main` repository provenance.
- `host-readiness.json` and `host-signing-and-permissions.txt`: shared Host
  readiness snapshot showing `can_start_trusted_lan_gate=false`.
- `preflight-command.txt` and `preflight-command.exit`: trusted-LAN preflight
  output and exit code (`2` means blocked while still writing JSON).
- `reconnect-timing-summary.json`: blocked reconnect timing summary with
  `can_close_timing_gate=false` and no required disruption exercised.
- `commands.txt`: command summary; every Android command used `adb -s
  <device-serial> ...`.
- `adb-*.txt`, `android-wifi-status.txt`, `android-wlan0.txt`, and
  `android-ip-route.txt`: device identity plus Wi-Fi, `wlan0`, and route
  diagnostics.
- `host-54321-listener.txt`, `macos-firewall.txt`, `macos-default-route.txt`,
  and `macos-ifconfig.txt`: Host port, firewall, and network diagnostics.
- `device-lock.txt`: `/tmp/vibe-screen-device-android.lock` acquisition record
  for this preflight.
- `SHA256SUMS`: hashes for retained artifacts.

Device and network command outputs are retained as sanitized stdout with
sensitive identifiers redacted.

No pairing token, QR payload, Wi-Fi credential, SSID, real Android serial,
operator home path, TCC database path, private key, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
