# Wake Host Request verification

## Local checks

- python3 -m unittest contracts.tests.test_security_contract
  - PASS: 13 tests; WakeHostRequest auth fields and envelope ids are pinned.
- cd baseline/MacHost && swift build
  - PASS: debug MacHost target builds.
- cd baseline/MacHost && swift build -c release && .build/release/Vibe\ Screen --protocol-v1-self-test
  - PASS: release build; Protocol v1 self-test includes wake request proof-field gating and session-bound context forwarding.
- cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest --tests dev.telemachus.display.protocol.ProtocolV1SessionTest --tests dev.telemachus.display.WakeHostTest
  - PASS: 87 Android unit tests; wake request API requires proof, carries proof fields, and rejects inbound requests without proof fields.
- cd baseline/MacHost && swift test --filter WakeHostTests
  - BLOCKED locally: Command Line Tools cannot import XCTest in this environment (no such module XCTest). The source target compiles with swift build; XCTest remains a full-Xcode/CI gate.

## Coverage

- Host authorization tests cover signed paired proof acceptance, unpaired-device
  rejection, expired proof rejection, nonce replay rejection, signature reuse
  across another session id rejection, and short-nonce rejection.
- Protocol state tests cover capability gating, streaming-state gating, host id
  matching, required proof fields, and forwarding of session id/epoch into the
  Host wake context.
- Android tests cover fail-closed request generation without proof, proof-field
  propagation, bounded pending request tracking, and transcript signing that
  fails when replayed against another session id.

No real sleeping Mac, BIOS/firmware WOL, router broadcast, TCC prompt, or
identity-signed installed Host acceptance was run for this change. The real
Wake-on-LAN gate remains open.
