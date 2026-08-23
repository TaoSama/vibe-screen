# Peripheral Input Framework Gate

Date: 2026-08-23
Base: origin/main at aaea0d595f66bb25bb226ba2b61152dcb40bd174
Status: offline readiness passed; concrete peripheral hardware gates remain open

## Scope

This change adds the shared Protocol v1 peripheral-input admission boundary. It
is deliberately capability-gated and fail-closed: peers can negotiate the generic
framework and exchange a bounded `PeripheralEvent`, but the current Host rejects
every concrete kind with `InputAck(accepted=false,
rejection_reason="unsupported_peripheral_kind")` before native injection.

This is not evidence for native HID mouse move/click, physical stylus drawing,
controller runtime acceptance, or any other concrete peripheral. Each concrete
hardware path still needs its own named-device run with Android input-source
logs, negotiated capability evidence, Host native-handler logs, visible macOS
output, and disconnect-neutralization evidence.

## Verification

- `make protocol`
  - Result: passed. Buf format/lint/build/breaking checks and 37 protocol
    contract tests passed, including the additive `PeripheralEvent` and
    capability `30` assertions.
- `diff -qr apps/ios/Sources/VibeScreenProtocol baseline/MacHost/Protocol/Sources/VibeScreenProtocol`
  - Result: passed. The checked-in iOS and MacHost Swift protobuf bindings are
    byte-identical after regeneration.
- `apps/ios/Scripts/verify-generated-protocol.sh`
  - Result: passed after this diff was committed locally. Regeneration produced
    no additional iOS binding diff, and iOS/MacHost generated bindings matched.
- `cd baseline/AndroidClient && ./gradlew testDebugUnitTest --tests dev.telemachus.display.StreamInputDispatcherTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.ClientInputDispatchTest --tests dev.telemachus.display.SessionStateTest --tests dev.telemachus.display.StreamInputBoundaryContractTest --tests dev.telemachus.display.MainActivityControllerForwardingContractTest`
  - Result: passed. Android capability advertisement remains explicit, session
    routing rejects unnegotiated peripheral input, invalid kind/payload fields
    stay off the outbound queue, and the MainActivity binding contract includes
    the negotiated framework flag.
- `cd apps/harmony && pnpm test`
  - Result: passed. Harmony knows capability `30` but does not advertise it.
- `make baseline-macos-self-test`
  - Result: passed. The MacHost release build and host, transport, reliability,
    Protocol v1, and video-encoder executable self-tests passed.
- `swift run --package-path apps/ios vibescreen-ios-selftest`
  - Result: passed. The iOS core self-test compiles the regenerated Swift
    bindings and pins capability `30`.
- `git diff --check`
  - Result: passed.

## Local Blockers

- `cd baseline/MacHost && swift test --filter ProtocolV1SessionTests`
  - Result: blocked before test execution. This machine has only Command Line
    Tools selected (`xcode-select -p` -> `/Library/Developer/CommandLineTools`)
    and `xcrun --find xcodebuild` fails, so SwiftPM cannot import `XCTest`
    (`error: no such module 'XCTest'`). The MacHost product target compiled
    and executable self-tests passed; full XCTest remains a full-Xcode CI gate.
