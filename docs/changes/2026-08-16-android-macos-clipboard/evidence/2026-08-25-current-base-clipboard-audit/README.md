# Protocol v1 Clipboard Current-Base Audit

## Scope

This record audits current `origin/main` for Android <-> macOS Protocol v1
clipboard status after the README matrix showed an E2E gap. It was refreshed
against the 2026-08-27 base before updating PR #231. It is a source and
offline-verification record only. It does not close the real Android
ClipboardManager <-> macOS NSPasteboard USB/LAN E2E device gate.

## Repository State

- Branch: `codex/clipboard-protocol-v1-e2e`
- Refresh base `origin/main`: `a33ccc82a4602037de1b2bf52bbce4dd57dc5a28`
- Final PR head: use the GitHub PR checks/status for the latest pushed head;
  this audit does not hard-code the moving PR branch tip.
- Open related PR: [#157](https://github.com/TaoSama/vibe-screen/pull/157)
  remains a draft runbook/evidence PR and should not be treated as a completed
  implementation or E2E pass.

## Implementation Audit

The implementation is already present on main. No protocol or product code was
added for this audit.

Protocol contract:

- `contracts/proto/vibescreen/protocol/v1/session.proto` defines
  `CAPABILITY_CLIPBOARD = 14`.
- `contracts/proto/vibescreen/protocol/v1/advanced.proto` defines
  `ResourceLimits.maximum_clipboard_bytes`, `ClipboardOffer`,
  `ClipboardRequest`, `ClipboardContent`, and `ManagedPolicyStatus` clipboard
  policy fields.
- `contracts/proto/vibescreen/protocol/v1/envelope.proto` carries
  `clipboard_offer`, `clipboard_request`, and `clipboard_content` envelopes.
- Protocol fixtures cover offer, request, and content messages.

Android implementation:

- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/protocol/ProtocolV1Session.kt`
  implements `offerClipboard`, `requestClipboard`, request expiry, and inbound
  offer/request/content validation.
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/ClipboardTransfer.kt`
  owns generation-bound approval state for offers and direct content.
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/StreamClient.kt`
  exposes the clipboard API to the product session.
- `baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt`
  reads `ClipboardManager` only after explicit send, writes only after explicit
  get/overwrite approval, and shows trusted-LAN warnings before body transfer.

MacHost implementation:

- `baseline/MacHost/Sources/ClipboardCore.swift` enforces the session state
  machine, size limit, MIME, strict UTF-8, origin, SHA-256, loopback, and
  solicited/direct separation.
- `baseline/MacHost/Sources/ClipboardPasteboard.swift` is the `NSPasteboard`
  boundary and is constrained to `@MainActor` / main queue access.
- `baseline/MacHost/Sources/ClipboardUIController.swift` owns menu actions,
  explicit approval, trusted-LAN warnings, direct content confirmation, and
  request timeout behavior.
- `baseline/MacHost/Sources/ProtocolV1Session.swift` and
  `baseline/MacHost/Sources/StreamingServer.swift` wire clipboard actions into
  the Protocol v1 session and server callbacks.

## Verification Run

Commands were run from this worktree on 2026-08-27 after rebasing onto current
`origin/main`.

```bash
cd baseline/AndroidClient
./gradlew --no-daemon testDebugUnitTest \
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardTest \
  --tests dev.telemachus.display.ClipboardApprovalStateTest
```

Result: `BUILD SUCCESSFUL`.

```bash
mkdir -p .tmp
TMPDIR="$PWD/.tmp" PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  contracts.tests.test_protocol_fixtures -v
```

Result: `Ran 16 tests ... OK`, including
`test_clipboard_fixtures_cover_offer_request_and_content`.

```bash
cd baseline/MacHost
swift build -c release
.build/release/Vibe\ Screen --protocol-v1-self-test
```

Result: release build completed, and Protocol v1 self-test reported `PASS`.

```bash
xcode-select -p
xcrun --find xcodebuild
cd baseline/MacHost
swift test --filter Clipboard
```

Result: blocked before test execution because this host is using
`/Library/Developer/CommandLineTools`, `xcrun --find xcodebuild` exits 72, and
test compilation fails with `error: no such module 'XCTest'`. This is an
environment gate, not a clipboard XCTest assertion failure.

## E2E Status

No Android device lock was taken, no target-device test was run, and no
clipboard E2E was attempted. A preflight check found no local code-signing
identity, so a signed Host/device run was not available in this environment.
Therefore this evidence does not prove:

- Android `ClipboardManager` -> macOS `NSPasteboard` transfer.
- macOS `NSPasteboard` -> Android `ClipboardManager` transfer.
- USB or trusted-LAN same-session clipboard capability negotiation on a real
  device.
- TalkBack behavior, trusted-LAN warning behavior, or long-session clipboard
  state stability.
- Public Internet/WebRTC clipboard transfer.

## Gate Decision

The README may state that Android/macOS Protocol v1 clipboard forwarding is
implemented and offline-tested on current main. The README must keep the real
Android ClipboardManager <-> macOS NSPasteboard USB/LAN E2E gate open until a
signed Host/device run records both directions with raw host, device, and
system pasteboard evidence.
