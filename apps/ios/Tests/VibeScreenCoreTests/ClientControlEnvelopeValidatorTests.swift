import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class ClientControlEnvelopeValidatorTests: XCTestCase {
    private let sessionID = Data([0xAA, 0xBB, 0xCC, 0xDD])
    private let sessionEpoch: UInt64 = 7

    private func makeActiveValidator() throws -> ClientControlEnvelopeValidator {
        var validator = ClientControlEnvelopeValidator()

        var hostHello = VSEnvelope()
        hostHello.protocolVersion = SessionState.protocolVersion
        hostHello.messageID = 1
        hostHello.hostHello.selectedProtocol = SessionState.protocolVersion
        try validator.validate(hostHello)

        var accepted = VSSessionAccepted()
        accepted.sessionID = sessionID
        accepted.sessionEpoch = sessionEpoch
        var acceptedEnvelope = VSEnvelope()
        acceptedEnvelope.protocolVersion = SessionState.protocolVersion
        acceptedEnvelope.messageID = 2
        acceptedEnvelope.sessionID = sessionID
        acceptedEnvelope.sessionEpoch = sessionEpoch
        acceptedEnvelope.sessionAccepted = accepted
        try validator.validate(acceptedEnvelope)

        return validator
    }

    func testActiveSessionAcceptsControllerEvent() throws {
        var validator = try makeActiveValidator()

        var controllerEvent = VSControllerEvent()
        controllerEvent.inputID = 1
        controllerEvent.controllerID = "controller-1"
        controllerEvent.controllerEpoch = 1
        controllerEvent.kind = .state

        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = 3
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.controllerEvent = controllerEvent

        XCTAssertNoThrow(try validator.validate(envelope))
    }

    func testControllerEventDoesNotBreakSubsequentMessageIDAndSessionValidation() throws {
        var validator = try makeActiveValidator()

        var controllerEvent = VSControllerEvent()
        controllerEvent.inputID = 1
        controllerEvent.controllerID = "controller-1"
        controllerEvent.controllerEpoch = 1
        controllerEvent.kind = .state

        var controllerEnvelope = VSEnvelope()
        controllerEnvelope.protocolVersion = SessionState.protocolVersion
        controllerEnvelope.messageID = 3
        controllerEnvelope.sessionID = sessionID
        controllerEnvelope.sessionEpoch = sessionEpoch
        controllerEnvelope.controllerEvent = controllerEvent
        try validator.validate(controllerEnvelope)

        // A subsequent message with a strictly greater message ID and the
        // correct session identity must still be accepted.
        var ping = VSEnvelope()
        ping.protocolVersion = SessionState.protocolVersion
        ping.messageID = 4
        ping.sessionID = sessionID
        ping.sessionEpoch = sessionEpoch
        ping.ping.sequence = 1
        XCTAssertNoThrow(try validator.validate(ping))

        // A duplicate message ID must be rejected as non-monotonic.
        var duplicate = ping
        duplicate.messageID = 4
        XCTAssertThrowsError(try validator.validate(duplicate)) { error in
            XCTAssertEqual(
                error as? ClientControlEnvelopeError,
                .nonMonotonicMessageID(received: 4, previous: 4)
            )
        }

        // A message with the wrong session epoch must be rejected.
        var wrongEpoch = ping
        wrongEpoch.messageID = 5
        wrongEpoch.sessionEpoch = sessionEpoch - 1
        XCTAssertThrowsError(try validator.validate(wrongEpoch)) { error in
            XCTAssertEqual(error as? ClientControlEnvelopeError, .invalidSession)
        }

        // A message with the wrong session ID must be rejected.
        var wrongSession = ping
        wrongSession.messageID = 5
        wrongSession.sessionID = Data([0xFF])
        XCTAssertThrowsError(try validator.validate(wrongSession)) { error in
            XCTAssertEqual(error as? ClientControlEnvelopeError, .invalidSession)
        }

        // A valid message after the rejected ones is still accepted, proving
        // the validator did not advance its last-message-ID state for rejects.
        var validPong = VSEnvelope()
        validPong.protocolVersion = SessionState.protocolVersion
        validPong.messageID = 5
        validPong.sessionID = sessionID
        validPong.sessionEpoch = sessionEpoch
        validPong.pong.sequence = 2
        validPong.correlationID = 1
        XCTAssertNoThrow(try validator.validate(validPong))
    }

    func testControllerEventWithUnknownFieldsIsForwardCompatible() throws {
        var validator = try makeActiveValidator()

        var controllerEvent = VSControllerEvent()
        controllerEvent.inputID = 1
        controllerEvent.controllerID = "controller-1"
        controllerEvent.controllerEpoch = 1
        controllerEvent.kind = .state

        // Serialize the controller event with an unknown trailing field so the
        // validator proves it tolerates future payload extensions without
        // claiming any controller implementation behavior.
        var bytes = try controllerEvent.serializedData()
        bytes.append(contentsOf: [0xF8, 0x01, 0x01])
        let decodedEvent = try VSControllerEvent(serializedBytes: bytes)
        XCTAssertFalse(decodedEvent.unknownFields.data.isEmpty)

        var envelope = VSEnvelope()
        envelope.protocolVersion = SessionState.protocolVersion
        envelope.messageID = 3
        envelope.sessionID = sessionID
        envelope.sessionEpoch = sessionEpoch
        envelope.controllerEvent = decodedEvent

        XCTAssertNoThrow(try validator.validate(envelope))
    }
}
