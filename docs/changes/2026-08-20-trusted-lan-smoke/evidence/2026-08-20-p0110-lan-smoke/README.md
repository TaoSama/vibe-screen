# Nubia P0110 trusted-LAN smoke - BLOCKED

Date: 2026-08-20
Source commit at preflight: `3ff86f22909f12ed81339a0ff7b8d518712e3655`
Branch: `codex/trusted-lan-smoke-evidence`
Target device serial: `<device-serial>`

## Intended gate

The intended run was the smallest useful current-worktree trusted-LAN smoke on
the connected Nubia P0110 / pacific / Android 16 device:

- Mac and Android on the same trusted private LAN;
- QR/token admission through `SSWA`/`SSWR`;
- trusted-LAN secure-record negotiation, not plaintext legacy fallback;
- Protocol v1 over `TRANSPORT_KIND_LAN`;
- short real display stream and decoder output;
- reconnect with the Host PID preserved.

## Blockers

The run stopped during LAN preflight before starting a Host listener or writing
any pairing token to the device. Two prerequisites were not met:

1. The Android device was reachable over USB and identified as Nubia P0110 /
   pacific / Android 16, but Wi-Fi was not associated. After `adb -s
   <device-serial> shell svc wifi enable`, `cmd wifi status` still reported
   `Wifi is not connected`, `wlan0` had no IPv4 address, and a ping to the Mac
   LAN candidate failed with `Network is unreachable`.
2. The local Mac has no valid codesigning identities, so
   `scripts/macos_dev_host.py preflight` cannot validate or install a
   current-source stable-signed Host bundle. The installed `/Applications/Vibe
   Screen.app` is signed with `Vibe Screen Dev`, but that identity is no longer
   present in the current keychain, and the installed binary hash differs from
   the current SwiftPM release binary.

Because of these blockers, no real trusted-LAN socket admission, secure-record
negotiation, ScreenCaptureKit frame delivery, Android MediaCodec output, or
reconnect was observed.

## Captured artifacts

- `device-info.txt`: device identity and basic display/battery state collected
  with `adb -s <device-serial>`.
- `android-network-blocker-sanitized.txt`: redacted Wi-Fi and route preflight
  showing no Wi-Fi association, no `wlan0` IPv4 address, and no route to the Mac
  LAN candidate.
- `android-app-state.txt`: installed package metadata and current debug APK
  SHA-256.
- `codesign-identities.txt`: `security find-identity -v -p codesigning` output
  showing `0 valid identities found`.
- `host-preflight-console.txt`: `scripts/macos_dev_host.py preflight` failure
  for the missing stable signing identity.
- `host-binary-identity.txt`: installed Host bundle codesign metadata plus the
  installed/current binary SHA-256 mismatch.

The raw Wi-Fi dump was not retained because it contained network identifiers.
No pairing token, QR payload, Wi-Fi credential, or private endpoint is
committed in this evidence package.

## Evidence status

This is blocker evidence only. It does not close the README trusted-LAN stream,
reconnect, latency, or stability gates. A later run must first connect the
Nubia P0110 to the same private LAN as the Mac and restore a stable Host signing
identity, then collect the non-legacy markers documented in
[`../../TEST.md`](../../TEST.md).
