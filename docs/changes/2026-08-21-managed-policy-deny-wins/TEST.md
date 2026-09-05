# Managed policy deny-wins verification

Status: offline verification complete; real Apple MDM profile, iOS managed App
Configuration, and Android Enterprise app-restrictions delivery blocked
Date: 2026-08-21; Android no-host refresh 2026-09-05
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

2026-09-05 Android no-host focused refresh:

- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest
  --tests dev.telemachus.display.internet.InternetProductSessionTest
  --tests dev.telemachus.display.internet.InternetManagedPolicyTest
  --tests dev.telemachus.display.internet.InternetClipboardTest
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest
  --tests dev.telemachus.display.ManagedConfigurationProviderTest
  --tests dev.telemachus.display.ManagedPolicyUiAvailabilityPolicyTest
  --tests dev.telemachus.display.GestureHostActionPolicyTest
  --tests dev.telemachus.display.MainActivityTransferReadinessContractTest
  --tests dev.telemachus.display.StreamProtocolSideEffectOwnerTest
  --tests dev.telemachus.display.StreamProtocolSessionOwnerTest
  --tests dev.telemachus.display.WakeHostProductOwnerTest
  --tests dev.telemachus.display.StreamProtocolActionDispatcherTest:
  BUILD SUCCESSFUL in 5s.
- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest:
  BUILD SUCCESSFUL in 26s.

2026-09-05 Android no-host minimal refresh on current `origin/main`:

- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest
  --tests dev.telemachus.display.FileTransferProductOwnerTest
  --tests dev.telemachus.display.ManagedConfigurationProviderTest
  --tests dev.telemachus.display.ProductSessionCoordinatorTest
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest:
  BUILD SUCCESSFUL in 46s.
- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest
  --tests dev.telemachus.display.protocol.ProtocolV1SessionTest
  --tests dev.telemachus.display.protocol.FileTransferSessionTest
  --tests dev.telemachus.display.protocol.ProtocolV1ClipboardFailClosedTest
  --tests dev.telemachus.display.FileTransferProductOwnerTest
  --tests dev.telemachus.display.ManagedConfigurationProviderTest
  --tests dev.telemachus.display.ProductSessionCoordinatorTest
  --tests dev.telemachus.display.MainActivityControllerForwardingContractTest
  --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest
  --tests dev.telemachus.display.internet.InternetClipboardTest
  --tests dev.telemachus.display.internet.ProtocolV1ProductCodecTest:
  BUILD SUCCESSFUL in 14s.
- cd baseline/AndroidClient && ./gradlew --no-daemon :app:testDebugUnitTest:
  BUILD SUCCESSFUL in 24s.
- cd baseline/AndroidClient && ./gradlew --no-daemon :app:lintDebug:
  BUILD SUCCESSFUL in 29s.
- make baseline-android-check: BUILD SUCCESSFUL. This reran the transport
  boundary gate, Android JVM tests, lint, assembleDebug, and release dependency
  audit.
- make phase5-host-advanced-adapters-gate: pass; wrote
  .build/evidence/phase5-host-advanced-adapters-readiness.json with
  verdict=pass.
- PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest
  tools.tests.test_clipboard_e2e_gate
  tools.tests.test_file_transfer_android_smoke
  tools.tests.test_file_transfer_bulk_current_base_gate
  tools.tests.test_file_transfer_bulk_current_base_manifest -v:
  Ran 80 tests, OK.

2026-09-06 Android no-host device-policy smoke on current `origin/main`:

- cd baseline/AndroidClient && ./gradlew --no-daemon :app:connectedDebugAndroidTest
  -Pandroid.testInstrumentationRunnerArguments.class=dev.telemachus.display.ManagedConfigurationProviderInstrumentedTest,dev.telemachus.display.CodecAdmissionInstrumentedTest:
  BUILD SUCCESSFUL in 16s; 2 tests ran on Nubia P0110 / pacific / Android 16 /
  SDK 36. The managed-policy test used a real Android `Context` and
  `RestrictionsManager.applicationRestrictions`, asserted the Bundle was empty,
  and verified `ManagedConfigurationProvider(context).loadPolicy()` returned
  `UNMANAGED`. No MDM permission, system restriction mutation, Host startup, or
  `adb reverse` was used.

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
- Android reads a local policy snapshot from
  RestrictionsManager.applicationRestrictions for USB/LAN StreamClient
  creation, keeps local CustomGesturesAllowed and HostActionsAllowed in the UI
  deny-wins path, and preserves host fail-closed behavior when a managed status
  is restored with incomplete restriction_results.
- A current-source no-Host instrumentation smoke covers the real Android
  `Context`/`RestrictionsManager.applicationRestrictions` empty path and keeps
  that unmanaged state mapped to `UNMANAGED`.
- Managed peers must send a complete nine-entry restriction_results set.
- Missing, duplicate, empty-explanation, or mismatched restriction results are
  rejected before the session proceeds.
- WakeHost request creation, incoming wake requests, pending wake
  managed_policy_denied completion/cleanup, and stale wake results are guarded
  by the effective managed policy.
- Internet audio removes CAPABILITY_AUDIO and stops active playback when a
  dynamic managed policy update denies audio; post-deny audio records do not
  fall through to the raw callback path.
- Local parse errors produce failClosed / local_parse_error policy.
- Android waits in AWAITING_MANAGED_POLICY before requesting displays when
  managed configuration is negotiated.
- Effective policy denies host actions, clipboard, file transfer, and peer host
  identity as soon as the merged policy says they are not allowed.
- Remote clipboard denial removes clipboard from the effective negotiated
  surface and suppresses outgoing Android clipboard offer/request envelopes.
- Local Android managed `MaximumFileBytes` bounds USB/LAN ClientHello resource
  limits and the negotiated file-transfer policy even when the Host peer does
  not negotiate managed configuration.

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

The 2026-09-05 records are JVM/source-only and ran no device command. The
2026-09-06 Android smoke is device evidence only for the unmanaged empty
`RestrictionsManager.applicationRestrictions` path on Nubia P0110 / pacific /
Android 16 / SDK 36.

No real Apple MDM profile, iOS managed App Configuration injection, or Android
Enterprise app-restrictions delivery with a non-empty payload was available in
this workspace. The repository therefore does not claim that a profile-delivered
com.apple.configuration.managed payload has been accepted by macOS or iOS, or
that an enterprise-delivered Android restrictions Bundle has reached the app on
a device. The blocked evidence is recorded under
evidence/2026-08-21-mdm-profile-blocked/.
