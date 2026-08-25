# Nubia P0110 current-base trusted-LAN smoke - BLOCKED

Date: 2026-08-22
Source commit: `79ef30ac7d3b50d3e0129f88823e7be238417bc0`
Branch: `codex/trusted-lan-p0110-current-base-successor`
Device: Nubia P0110 / pacific / Android 16 / SDK 36, serial `<device-serial>`

## Result

The current-base successor rechecked the Trusted LAN preconditions on the real
Nubia P0110/pacific Android substitute device without installing, force-stopping,
or reconnecting the app. The device was USB-reachable and its identity was
recorded, but the real trusted-LAN stream could not start because the device was
not associated to Wi-Fi: `cmd wifi status` reported `Wifi is not connected`,
`wlan0` reported `NO-CARRIER` and `state DOWN`, `ip route` returned no route,
and pinging the redacted Mac LAN candidate failed with `Network is unreachable`.

Host acceptance was also blocked before pairing. A local Vibe Screen listener was
present only on loopback TCP 54321, while `scripts/macos_dev_host.py preflight`
failed because the required stable `Vibe Screen Dev` codesign identity was not
available in the keychain. This environment therefore cannot install or verify a
current-source stable-signed Host bundle for evidence-grade Screen Recording and
Accessibility/TCC-backed device acceptance.

No real trusted-LAN stream was observed. No LAN socket admission, secure-record
negotiation, decoder output, reconnect, latency, long-soak, or Host RSS no-growth
claim is made by this record.

## Retained artifacts

| Artifact | Purpose |
| --- | --- |
| `commands.txt` | Timestamp, current source commit, explicit lock check, lock acquisition, and lock release. |
| `device-info.txt` | `adb -s <device-serial>` device list and Nubia P0110/pacific Android identity. |
| `android-network-blocker-sanitized.txt` | Wi-Fi status, `wlan0`, route, Mac LAN candidate, and failed reachability probe. |
| `mac-lan-preflight.txt` | macOS version/toolchain, host network interfaces, and TCP 54321 listener snapshot. |
| `codesign-identities.txt` | Local codesigning identity list used to diagnose the missing stable Host identity. |
| `host-binary-identity.txt` | Installed `/Applications/Vibe Screen.app` signing and bundle snapshot. |
| `host-preflight-console.txt` | `scripts/macos_dev_host.py preflight` blocker output. |
| `android-app-state.txt` | Non-destructive foreground/activity snapshot. |
| `trusted-lan-smoke-verdict.json` | Fail-closed evidence checker verdict for this blocked package. |
| `make-protocol.txt` / `make-protocol.exit` | Current-source Protocol v1 contract and fixture verification. |
| `android-lan-security-tests.txt` / `android-lan-security-tests.exit` | Focused Android LAN token/admission/secure-record unit tests. |
| `SHA256SUMS` | Artifact checksums. |

## Source-level checks

| Check | Result | Notes |
| --- | --- | --- |
| `make protocol` | PASS | Protocol format, lint, build, breaking check, and 36 protocol fixture/security tests passed. |
| `cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.LanSecureRecordAdapterTest --tests dev.telemachus.display.StreamClientWirelessSecurityTest --tests dev.telemachus.display.AuthHandshakeTest` | PASS | Android LAN secure-record and admission focused tests passed. |
| `make trusted-lan-smoke-evidence-check EVIDENCE_DIR=docs/changes/2026-08-20-trusted-lan-smoke/evidence/2026-08-22-p0110-current-base-successor` | PASS as `blocked` | The package is valid blocked evidence and cannot close the trusted-LAN stream or reconnect gates. |

## Boundary

This evidence keeps the real device identity as Nubia P0110/pacific/Android 16.
It must not be relabeled as Xiaomi 13/fuxi evidence. The current-worktree
trusted-LAN stream and reconnect gates remain open until a later run records the
required non-legacy encrypted LAN markers, HEVC output frames, and Host-PID-
preserving reconnect on a reachable trusted LAN with a stable-signed Host.
