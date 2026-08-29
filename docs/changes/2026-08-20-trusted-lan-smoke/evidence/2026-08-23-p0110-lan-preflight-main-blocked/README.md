# Nubia P0110 trusted-LAN main preflight - BLOCKED

Date: 2026-08-23
Target branch: `codex/trusted-lan-p0110-evidence`
Base commit: `392b86882869f9bf431cfd35be834f6cdc15fd37`
Target device serial: `<device-serial>`

## Intended gate

This recheck ran after PR #261 merged the fail-closed trusted-LAN preflight into
`origin/main`. It attempted to determine whether the current machine and the
explicit Nubia P0110 / pacific / Android 16 device were ready to start a real
trusted-LAN smoke and reconnect run. The preflight is read-only and stops before
Host launch, QR/token admission, secure-record negotiation, stream startup,
reconnect, latency, or soak collection unless every prerequisite is ready.

## Result

The run is blocked. The device identity was confirmed as nubia P0110 / pacific /
Android 16 / SDK 36, but the preflight could not proceed to a real LAN smoke.
The JSON records these blockers:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4 candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

Because the preflight returned `blocked`, no Host was launched, no QR payload or
pairing token was written, no secure records were negotiated, no real LAN stream
started, and reconnect was not exercised. This evidence package does not close
the README trusted-LAN stream, reconnect, latency, or stability gates.

## Captured artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed preflight result.
- `commands.txt`: command summary; every Android command used `adb -s
  <device-serial> ...`.
- `device-lock.txt`: local Android device lock acquisition and release record.
- `SHA256SUMS`: hashes for retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
