# Managed policy deny-wins verification

Status: offline verification complete; real Apple MDM profile injection blocked
Date: 2026-08-21
Host: macOS local development environment

## Passed local gates

- cd baseline/MacHost && swift build: Build complete.
- cd baseline/MacHost && swift run "Vibe Screen" --protocol-v1-self-test:
  Protocol v1 self-test PASS.
- cd apps/ios && swift build: Build complete.
- cd apps/ios && swift run vibescreen-ios-selftest: PASS for Phase 5A-5D core
  and trusted-LAN Protocol v1 startup.
- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest: BUILD SUCCESSFUL.
- cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest: BUILD
  SUCCESSFUL.

The iOS generated-protocol verifier was also run after regenerating the Swift
bindings. Before the regenerated files were staged, it correctly reported the
tracked binding diff as not current; after staging those generated files for the
PR, rerunning it passed with macOS and iOS Protocol v1 bindings current.

## Covered behavior

- Host and iOS parse Apple managed configuration keys and treat missing boolean
  keys as denied.
- Host and iOS normalize AllowedHosts and DeniedHosts, serialize them over
  Protocol v1, and reject hosts present in the denylist even when allowlisted.
- Android applies local/remote deny-wins semantics for booleans, maximum file
  bytes, allowlist intersection, and denylist union.
- Managed peers must send a complete nine-entry restriction_results set.
- Missing, duplicate, empty-explanation, or mismatched restriction results are
  rejected before the session proceeds.
- Local parse errors produce failClosed / local_parse_error policy.
- Android waits in AWAITING_MANAGED_POLICY before requesting displays when
  managed configuration is negotiated.
- Effective policy denies host actions, clipboard, file transfer, and peer host
  identity as soon as the merged policy says they are not allowed.

## Blocked local gates

The local SwiftPM environment uses Command Line Tools without a usable XCTest
module, so focused Swift XCTest commands fail before executing test assertions:

- cd baseline/MacHost && swift test --filter ManagedPolicyTests
- cd apps/ios && swift test --filter ManagedPolicyTests

Observed failure class: error: no such module XCTest. This is an environment
gate, not a failing managed-policy assertion. Full Xcode or CI must run these
test targets before they can be claimed as passed.

The iOS app target is Xcode-project based. Local `xcodebuild` is also blocked
because the active developer directory is Command Line Tools rather than full
Xcode, so app-target compilation and VibeScreenAppTests are not claimed in this
local record.

## Evidence boundary

No device command was run for this record. In particular, no command was run
against Android serial EP0110PZ0B9110300B and no result here is Android device
evidence.

No real Apple MDM profile or local managed App Configuration injection was
available in this workspace. The repository therefore does not claim that a
profile-delivered com.apple.configuration.managed payload has been accepted by
macOS or iOS. The blocked evidence is recorded under
evidence/2026-08-21-mdm-profile-blocked/.
