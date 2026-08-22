# Nubia P0110 trusted-LAN preflight - BLOCKED

Date: 2026-08-22
Initial target baseline: `a8346626f07de98a54508c2d05ba138d0c969ef0`; the
retained JSON records the exact repository revision and dirty state at the
latest sanitized capture.
Target device serial: `EP0110PZ0B9110300B`
Repository status: the captured JSON reports a dirty worktree because this
branch adds the trusted-LAN preflight tool and this evidence package.

## Intended gate

This preflight checked whether the current worktree could start the real Nubia
P0110 / pacific / Android 16 trusted-LAN smoke: Wi-Fi association, wlan0 IPv4,
route to the Mac LAN address, stable Host signing/TCC, and a clear distinction
between loopback USB listeners and LAN listeners.

## Result

The run is blocked before Host launch, QR/token admission, secure-record
negotiation, Protocol v1 LAN upgrade, decoder output, reconnect, latency, or
soak evidence. The preflight JSON reports these blockers:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: wlan0 is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no wlan0 route to any Mac LAN IPv4 candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

The Android device identity was confirmed as nubia P0110 / pacific / Android 16
/ SDK 36. Wi-Fi was enabled but not associated; wlan0 still had `NO-CARRIER`,
`state DOWN`, no IPv4 address, and no route to the Mac LAN candidate. The Mac had
a redacted CGNAT LAN candidate; TCP 54321 had only a loopback listener, which is
not LAN evidence. Host preflight failed because the `Vibe Screen Dev` signing
identity was not available, so TCC was not evaluated.

No real trusted-LAN stream, non-legacy secure-record marker, Android decoder
output, Host PID preserved reconnect, LAN latency, or stability result was
observed. This package cannot close the trusted-LAN stream or reconnect gate.

## Captured artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed preflight result.
- `device-lock.txt`: local Android device lock acquisition record.
- `commands.txt`: command summary. Every ADB command used `-s
  EP0110PZ0B9110300B`.
- `SHA256SUMS`: hashes for retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
