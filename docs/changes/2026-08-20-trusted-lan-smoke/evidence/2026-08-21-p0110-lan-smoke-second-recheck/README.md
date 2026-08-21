# Nubia P0110 trusted-LAN smoke second recheck - BLOCKED

Date: 2026-08-21
Source commit at preflight: `c5add121d4ebebaa0083db64551a81ec7899696e`
Branch: `codex/trusted-lan-p0110-smoke`
Target device serial: `EP0110PZ0B9110300B`

## Intended gate

This run rechecked the current `origin/main` baseline for the smallest useful
trusted-LAN smoke on the connected Nubia P0110 / pacific / Android 16 device:

- Mac and Android on the same trusted private LAN;
- QR/token admission through `SSWA`/`SSWR`;
- trusted-LAN secure-record negotiation, not plaintext legacy fallback;
- Protocol v1 over `TRANSPORT_KIND_LAN`;
- short real HEVC display stream and Android decoder output;
- basic reconnect with the Host PID preserved.

## Result

The smoke is still blocked before Host launch, QR/token exchange, or LAN socket
admission. The device is reachable over USB and identifies as Nubia P0110 /
pacific / Android 16, but it is not associated with Wi-Fi: `wlan0` reports
`NO-CARRIER` and `state DOWN`, `cmd wifi status` reports `Wifi is not
connected`, `ip route` is empty, and pinging the Mac LAN candidate returns
`Network is unreachable`. The Mac has an active `en0` private LAN candidate, but
no process is listening on TCP `54321`.

The macOS Host evidence preflight is also blocked because the local keychain has
`0 valid identities found`; `scripts/macos_dev_host.py preflight` fails for the
missing stable `Vibe Screen Dev` signing identity. The installed `/Applications/Vibe
Screen.app` is not proven to be a current-source, stable-signed Host bundle for
this worktree.

Because of these blockers, this run observed no real trusted-LAN stream, no
secure-record negotiation, no Android decoder output, no reconnect, and no LAN
latency or stability evidence. It does not close any README trusted-LAN gate.

## Captured artifacts

- `commands.txt`: commands used for this recheck. Every ADB command targets
  `EP0110PZ0B9110300B` explicitly with `-s`.
- `device-info.txt`: device identity, Android version, display, battery, and boot
  state.
- `android-network-blocker-sanitized.txt`: Wi-Fi and route preflight showing no
  associated `wlan0` connection and no route to the Mac LAN candidate.
- `mac-lan-preflight.txt`: Mac OS/toolchain, `en0` network candidate, and empty
  TCP `54321` listener check.
- `codesign-identities.txt`: `security find-identity -v -p codesigning` output
  showing `0 valid identities found`.
- `host-preflight-console.txt`: stable Host preflight failure for the missing
  `Vibe Screen Dev` signing identity.
- `tcc-permissions.txt`: read-only TCC row query for `dev.telemachus.display`;
  the preflight stopped before these rows could authorize a current-source Host
  because signing identity validation failed first.
- `host-binary-identity.txt`: installed Host bundle codesign metadata and the
  current worktree Host binary state.
- `android-app-state.txt`: installed Android package metadata and current debug
  APK state.
- `android-lan-security-tests.txt`: Android JVM LAN admission and secure-record
  tests.
- `make-protocol.txt`: Protocol v1 schema, fixture, and security contract checks.
- `trusted-lan-verifier-tests.txt`: focused tests for the trusted-LAN evidence
  checker.
- `trusted-lan-smoke-evidence-check.txt`: command output from validating this
  evidence package as a blocked trusted-LAN smoke record.
- `trusted-lan-smoke-verdict.json`: machine-readable verifier result for this
  blocked evidence package.
- `*.exit`: retained exit codes for the corresponding verification commands.
- `SHA256SUMS`: hashes for the retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
