# Phase 5 advanced gates current-base audit

Date: 2026-08-27
Base: origin/main 3b2ba11e832a3618eaedfc67f92414b161423a00

## Result

Status: blocked readiness. No advanced gate is newly closed by this audit.

This package audits the current-base status of three Phase 5 advanced gates:
WakeHost / Wake-on-LAN, single-file transfer over Protocol v1, and deny-wins
managed configuration. The audit confirms that each area has offline source,
protocol, and unit/self-test coverage on the current base, while preserving the
README boundary that real hardware, real file-flow, and real managed-profile
evidence are still required before product acceptance can be claimed.

## Gate findings

| Gate | Current-base coverage | Open evidence |
| --- | --- | --- |
| WakeHost / Wake-on-LAN | baseline/MacHost/Sources/WakeHost.swift, baseline/AndroidClient/app/src/main/java/dev/telemachus/display/WakeHost.kt, and focused tests cover HMAC authorization, replay rejection, policy denial, target validation, and 102-byte magic-packet construction. The refreshed machine summary is in docs/changes/2026-08-23-wake-host-current-base/evidence/2026-08-27-current-base-blocked/. | Real sleeping-Mac wake, WOL-capable router or directed broadcast delivery, NIC wake settings, packet capture or router logs, post-wake Host availability, and retained negative hardware-run attempts. |
| Single-file transfer over Protocol v1 | contracts/proto/vibescreen/protocol/v1/advanced.proto, baseline/MacHost/Sources/ProtocolV1FileTransfer.swift, baseline/AndroidClient/app/src/main/java/dev/telemachus/display/protocol/FileTransferSession.kt, and app iOS core code cover safe basenames, explicit receiver approval, ordered bulk chunks, SHA-256 validation, session-epoch checks, progress-driven backpressure, cancel/disconnect cleanup, and deny-wins policy limits. | Real Android USB/LAN file send and receive with UI file selection, receiver approval, saved destination files, progress/cancel behavior, and source/destination SHA-256 equality. Public-Internet WebRTC bulk product flow remains a separate Phase 3 advanced DataChannel gate. |
| Deny-wins managed configuration | docs/changes/2026-08-21-managed-policy-deny-wins/ plus Host, Android, and iOS policy code cover complete restriction_results, parse-error fail closed, boolean AND, minimum file-byte limits, allowlist intersection, and DeniedHosts over AllowedHosts. | Real Apple MDM or managed App Configuration delivery, Android managed configuration interop on device, and retained mid-session revocation behavior under a live product session. |

## Corrections made during audit

The older file-transfer blocked evidence package contained a raw Android serial
in public files. This audit redacts that serial while keeping the device identity
as nubia P0110 / pacific / Android 16 / SDK 36.

The audit also found that current-base MacHost release builds were broken by the
new Protocol v1 multi-client routing self-test references landing without the
matching Host routing boundary. The fix adds the missing fail-closed route owner
and keeps the default production limit at one client and one video stream, so it
restores build/self-test coverage without closing any Phase 5 advanced gate.

## Verification notes

swift build -c release, the release binary's --protocol-v1-self-test, the
focused Android JVM WakeHost/FileTransfer/ProtocolV1Session tests, Protocol v1
fixture tests, and the WakeHost blocked-gate generator all pass on this audit
worktree. swift test --filter ProtocolV1SessionTests remains locally blocked
because this host is using Command Line Tools only and xcrun --find xctest does
not resolve XCTest.

## Files

- commands.txt - verification commands and expected blocked-gate command.
- advanced-gates-current-base-audit.json - machine-readable audit summary.
