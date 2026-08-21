# File Transfer E2E Verification

## Scope

This change hardens the existing Protocol v1 single-file transfer path between
the macOS Host and Android client. The Android client now has a negotiated
control-bar entry point, Storage Access Framework picker for sending files, and
receiver approval dialog for incoming offers. Received files remain in
app-private staging; this change does not add a user-selected save/export flow
for completed incoming files, and it does not claim real-device, TCC, signed
Host, public Internet, or WebRTC bulk DataChannel acceptance.

## Verified locally

- Android loopback socket E2E covers a host `FileOffer` accepted by the client,
  a bulk file chunk, progress, completion, SHA-256 verification, and the
  completed app-private staging file.
- Android loopback socket E2E covers `StreamClient.offerFile(...)`, the emitted
  `FileOffer`, accepted transfer, bulk chunk bytes, final chunk SHA-256, and
  completion callback.
- Android loopback socket E2E verifies `offerFile(...)` returns false and emits
  no wire message when `CAPABILITY_FILE_TRANSFER` was not negotiated.
- Android unit tests cover the file-transfer control availability and control
  bar layout sizing, including the additional file-transfer button.
- Android `assembleDebug` verifies the app resources, data binding, and new SAF
  picker/approval UI wiring compile locally.
- macOS Host source now fail-closes bulk handling unless the active Protocol v1
  session still has file transfer negotiated, avoids retaining outgoing offers
  when file transfer is unavailable, and cancels active transfers when remote
  managed policy disables file transfer or the Host stops.

## Commands

Android targeted file-transfer socket E2E:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.hostFileOfferAcceptsBulkChunksAndCompletesStagedFile" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.clientFileOfferSendsBulkChunksAndReportsCompletion" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.fileOfferReturnsFalseWhenCapabilityNotNegotiatedWithoutWireMessage"

Result: passed locally on 2026-08-21.

Android full StreamClient Protocol v1 integration class:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests dev.telemachus.display.StreamClientProtocolV1IntegrationTest

Result: the three new file-transfer cases passed, but the existing
`decoderRejectionFlushesBeforeTermination` timing test failed waiting for its
manual termination executor. This failure is outside the file-transfer path.

Android targeted protocol, file-transfer, session, and control-bar tests:

    cd baseline/AndroidClient
    ./gradlew testDebugUnitTest --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.hostFileOfferAcceptsBulkChunksAndCompletesStagedFile" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.clientFileOfferSendsBulkChunksAndReportsCompletion" --tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.fileOfferReturnsFalseWhenCapabilityNotNegotiatedWithoutWireMessage" --tests dev.telemachus.display.protocol.FileTransferSessionTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.ClientInputDispatchTest --tests dev.telemachus.display.SessionStateTest --tests dev.telemachus.display.ClientExperienceTest --tests dev.telemachus.display.DisplayCapsulePolicyTest

Result: passed locally on 2026-08-21.

Android debug build:

    cd baseline/AndroidClient
    ./gradlew assembleDebug

Result: passed locally on 2026-08-21.

Protocol contract tests:

    make protocol-tests

Result: passed locally on 2026-08-21; 36 tests ran, 0 failures.

MacHost source build:

    cd baseline/MacHost
    swift build

Result: passed locally on 2026-08-21.

MacHost XCTest attempt:

    cd baseline/MacHost
    swift test --filter StreamingServerClipboardTests

Result: blocked locally before executing tests because the active toolchain is
Command Line Tools only and cannot import `XCTest` (`no such module 'XCTest'`).
The MacHost package sources compiled before the test target failed to build.

## Open gates

- Android real-device UI file send/receive acceptance remains open.
- Android user-selected save/export for completed incoming files remains open;
  completed incoming files currently stay in app-private staging.
- macOS signed Host, TCC permissions, and real Android-device file transfer
  acceptance remain open.
- Public Internet/WebRTC bulk DataChannel file-transfer acceptance remains open.
