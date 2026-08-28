# Nubia P0110 trusted-LAN preflight recheck - BLOCKED

Date: 2026-08-22
Target branch: `codex/trusted-lan-preflight`
Target PR: #261
Target commit before preflight: `ab4926f08940b5ef82246ce7c2264e697c0eb007`
Target device serial: `<redacted-adb-serial>`

## Intended gate

This recheck attempted to advance the current-worktree trusted-LAN gate after
the Android device lock was released. The preflight is intentionally read-only
and stops before Host launch, QR/token admission, secure-record negotiation,
stream startup, reconnect, latency, or soak collection unless the environment is
ready.

## Result

The run is blocked. The Android device identity was confirmed as nubia P0110 /
pacific / Android 16 / SDK 36, but the preflight could not proceed to a real LAN
smoke because the device was not associated with Wi-Fi and the Host did not pass
stable-signing readiness. The JSON records these blockers:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: wlan0 is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no wlan0 route to any Mac LAN IPv4 candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

Because the preflight returned `blocked`, no Host was launched, no QR payload or
pairing token was written, no secure records were negotiated, no real LAN stream
started, and reconnect was not exercised. This package does not close the
trusted-LAN stream or reconnect gate.

## Captured artifacts

- `adb-*.txt`: explicit-serial ADB identity checks for `<redacted-adb-serial>`.
- `trusted-lan-preflight.json`: machine-readable fail-closed preflight result.
- `commands.txt`: command summary; every Android command used `adb -s
  <redacted-adb-serial> ...`.
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
