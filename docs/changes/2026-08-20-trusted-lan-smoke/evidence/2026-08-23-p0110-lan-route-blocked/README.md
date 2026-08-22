# Nubia P0110 trusted-LAN route preflight - BLOCKED

Date: 2026-08-23
Source commit: `de2752e0033713ad48bb7f86960f9180d8e7342f` (`origin/main`)
Branch: `codex/trusted-lan-p0110-route-blocker-20260823`
Target device serial: `EP0110PZ0B9110300B`

## Intended gate

This recheck tried to remove the previous Nubia P0110 Wi-Fi/route precondition
blocker before attempting a current-base trusted-LAN smoke. It was deliberately
read-only for Android network state: no Wi-Fi credentials, saved networks, or
system network configuration were changed.

The intended smoke remains the same as the earlier trusted-LAN gate: a Nubia
P0110 / pacific / Android 16 device and the current macOS Host on the same
trusted private LAN, QR/token admission, non-legacy AES-256-GCM secure records,
Protocol v1 over `TRANSPORT_KIND_LAN`, decoder output, and a short reconnect
with the Host PID preserved.

## Result

The Wi-Fi/route blocker is not resolved. The device is reachable over USB and
its identity is Nubia P0110 / pacific / Android 16 / SDK 36, but `cmd wifi
status` reports `Wifi is not connected`. `wlan0` is `NO-CARRIER` and
`state DOWN`, has no IPv4 address, and `ip route` returns no route. A route
lookup and ping to the Mac LAN IPv4 candidate both fail with `Network is
unreachable`.

The Mac has an `en0` LAN IPv4 candidate, but no process is listening on TCP
`54321`. The stable Host preflight is also blocked because the current machine
has no valid `Vibe Screen Dev` codesigning identity; `scripts/macos_dev_host.py
preflight` exits `1` before TCC-backed device evidence can be trusted.

Because the LAN preconditions are still absent, no Host launch, QR/token
admission, trusted-LAN socket admission, secure-record negotiation, Protocol v1
LAN upgrade, decoder output, reconnect, latency, or stability evidence was
attempted or observed. This package does not close any README trusted-LAN gate.

## Captured artifacts

- `device-info.json`: standard Android identity/package snapshot from
  `make evidence-device-info`.
- `android-network-blocker-sanitized.txt`: read-only ADB Wi-Fi, IP, route, DNS,
  host reachability, and reverse-port state. Every ADB command uses
  `adb -s EP0110PZ0B9110300B`.
- `mac-lan-preflight.txt`: macOS version, Xcode selection, codesigning
  identities, sanitized LAN IP candidate, and TCP `54321` listener status.
- `host-preflight-console.txt` and `host-preflight.exit`: stable Host preflight
  failure for the missing `Vibe Screen Dev` signing identity.
- `device-lock.txt`: shared Android lock state before the recheck.
- `commands.txt`: command list for reproducing the preflight.
- `SHA256SUMS`: hashes for the retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-base real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
