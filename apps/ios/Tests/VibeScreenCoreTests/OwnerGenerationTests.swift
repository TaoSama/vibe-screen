import XCTest
@testable import VibeScreenCore

final class OwnerGenerationTests: XCTestCase {
    func testLateControlMediaAndErrorDeliveriesCannotCrossConnectionRotation() {
        let oldConnection = ConnectionOwner()
        let currentConnection = ConnectionOwner()
        var gate = OwnedDeliveryGate(owner: oldConnection)

        let lateControl = OwnedDelivery(owner: oldConnection, payload: "control")
        let lateMedia = OwnedDelivery(owner: oldConnection, payload: Data([0x01]))
        let lateError = OwnedDelivery(owner: oldConnection, payload: "closed")
        gate.reset(to: currentConnection)

        XCTAssertFalse(gate.accepts(lateControl))
        XCTAssertFalse(gate.accepts(lateMedia))
        XCTAssertFalse(gate.accepts(lateError))
        XCTAssertTrue(gate.accepts(OwnedDelivery(owner: currentConnection, payload: "current")))
    }

    func testLatePixelCannotCrossSessionOrDecoderRotation() {
        let connection = ConnectionOwner()
        let oldSession = SessionOwner(connectionOwner: connection)
        let currentSession = SessionOwner(connectionOwner: connection)
        let oldDecoder = DecoderOwner(sessionOwner: oldSession, streamID: 9, configEpoch: 3)
        let currentDecoder = DecoderOwner(sessionOwner: currentSession, streamID: 9, configEpoch: 3)

        XCTAssertFalse(DecoderDeliveryGate.accepts(
            owner: oldDecoder,
            activeOwner: currentDecoder,
            sessionOwner: currentSession,
            selectedStreamID: 9
        ))
        XCTAssertTrue(DecoderDeliveryGate.accepts(
            owner: currentDecoder,
            activeOwner: currentDecoder,
            sessionOwner: currentSession,
            selectedStreamID: 9
        ))

        let reconfigured = DecoderOwner(sessionOwner: currentSession, streamID: 9, configEpoch: 4)
        XCTAssertFalse(DecoderDeliveryGate.accepts(
            owner: currentDecoder,
            activeOwner: reconfigured,
            sessionOwner: currentSession,
            selectedStreamID: 9
        ))
        XCTAssertTrue(DecoderDeliveryGate.accepts(
            owner: reconfigured,
            activeOwner: reconfigured,
            sessionOwner: currentSession,
            selectedStreamID: 9
        ))
    }
}
