# Nubia P0110 trusted-LAN smoke recheck - BLOCKED

Date: 2026-08-21
Source commit at preflight: `cc26a84c829016fa61c721f73a128284fdf64f92`
Branch: `codex/lan-trusted-p0110-smoke`
Target device serial: `EP0110PZ0B9110300B`

## Intended gate

This recheck attempted the smallest safe current-worktree trusted-LAN smoke
preflight for the connected Nubia P0110 / pacific / Android 16 device:

- Mac and Android on the same trusted private LAN;
- QR/token admission through the wireless pairing path;
- trusted-LAN secure-record negotiation, not plaintext legacy fallback;
- Protocol v1 over `TRANSPORT_KIND_LAN`;
- short real display stream and decoder output;
- reconnect with the Host PID preserved.

## Result

The smoke remained blocked before any Host launch, QR/token exchange, or LAN
socket admission. The device was reachable over USB and identified as Nubia
P0110 / pacific / Android 16, but it had no Wi-Fi association. `wlan0` reported
`NO-CARRIER` and `state DOWN`, `cmd wifi status` reported `Wifi is not
connected`, and `ip route` returned no route. The Mac had an active `en0` LAN
address but no process was listening on TCP `54321`.

The macOS Host evidence preflight also remained blocked because the local
keychain did not contain the stable `Vibe Screen Dev` signing identity required
by `scripts/macos_dev_host.py preflight`.

Because of these blockers, this run observed no real trusted-LAN stream, no
secure-record negotiation, no Android decoder output, no reconnect, and no LAN
latency or stability evidence. It does not close any README trusted-LAN gate.

## Captured artifacts

- `commands.txt`: commands used for this recheck. Every ADB command targets
  `EP0110PZ0B9110300B` explicitly with `-s`.
- `device-info.txt`: device identity, Android version, display, battery, and boot
  state.
- `android-network-blocker-sanitized.txt`: Wi-Fi and route preflight showing no
  associated `wlan0` connection and no route.
- `mac-lan-preflight.txt`: Mac `en0` network candidate and empty TCP `54321`
  listener check.
- `host-preflight-console.txt`: stable Host preflight failure for the missing
  `Vibe Screen Dev` signing identity.
- `android-lan-security-tests.txt`: Android JVM LAN admission and secure-record
  tests, which passed.
- `make-protocol.txt` and `make-protocol.exit`: Protocol v1 schema, fixture, and
  security contract checks, which passed with exit code `0`.
- `protocol-fixture-check.txt` and `protocol-fixture-check.exit`: focused
  protocol fixture check rerun, which passed with exit code `0`.
- `SHA256SUMS`: hashes for the retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
