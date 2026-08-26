# Nubia P0110 trusted-LAN main preflight recheck - BLOCKED

Date: 2026-08-24
Target branch: `codex/trusted-lan-p0110-preflight-20260824`
Base commit: `34b75ac7d945dfa6697ff311fd0a821fb75532ef`
Target device serial: `<device-serial>`

## Intended gate

This recheck started from the latest `origin/main` after `git fetch origin
--prune` and audited the still-open trusted-LAN work in PR #286, PR #246, and
PR #191. Those PRs contain blocker records and older fail-closed checker work,
but none contains current `origin/main` real-device LAN stream/reconnect pass
evidence. This package therefore uses the merged read-only trusted-LAN
preflight as the authoritative current-base check before Host launch or pairing.
The preflight JSON records repository state from a clean detached copy of that
same `origin/main` commit so generated evidence files do not make the source
baseline appear dirty.

## Result

The run is blocked before a real LAN smoke can start. The device identity was
confirmed as nubia P0110 / pacific / Android 16 / SDK 36, and Wi-Fi was enabled
with `adb -s <device-serial> shell svc wifi enable`, but the preflight JSON
records these blockers:

- `android_wifi_association`: Wi-Fi is not associated.
- `android_wlan_ipv4`: `wlan0` is down, has no carrier, or has no IPv4 address.
- `route_to_mac_lan`: Android has no `wlan0` route to any Mac LAN IPv4
  candidate.
- `host_stable_signing`: Host stable signing is blocked before trusted-LAN
  evidence can start.

The Mac also had no TCP `54321` LAN listener, which was expected for this
pre-launch preflight and is not LAN pass evidence. The Host preflight failed
because the `Vibe Screen Dev` codesigning identity is not present in the local
keychain; Screen Recording and Accessibility TCC were therefore not evaluated.

Because the preflight returned `blocked`, no Host was launched, no QR payload or
pairing token was written, no secure records were negotiated, no Protocol v1 LAN
session was admitted, no decoder output was observed, and reconnect was not
exercised. This evidence package does not close the README trusted-LAN stream,
reconnect, latency, or stability gates.

## Captured artifacts

- `trusted-lan-preflight.json`: machine-readable fail-closed preflight result.
- `preflight-command.txt` and `preflight-command.exit`: make target output and
  exit code (`2` means blocked while still writing JSON).
- `reconnect-timing-summary.json`: machine-readable reconnect timing blocked
  record with `can_close_timing_gate=false` for the LAN-relevant
  `client-kill` and `lan-network-interrupt` disruptions.
- `commands.txt`: command summary; every Android command used `adb -s
  <device-serial> ...`.
- `adb-*.txt`: device selection and exact identity probes.
- `device-lock.txt`: local device lock observation for this preflight.
- `SHA256SUMS`: hashes for retained artifacts.

No pairing token, QR payload, Wi-Fi credential, SSID, public address, or private
screen content is retained in this evidence package.

## Open gates

- Current-worktree real macOS/Android trusted-LAN stream on Nubia P0110/pacific.
- Non-legacy trusted-LAN secure-record markers on both Host and Android.
- Trusted-LAN reconnect with preserved Host PID.
- LAN glass-to-glass latency with external-camera evidence.
- Sustained LAN stream, memory, thermal, and host RSS no-growth evidence.
