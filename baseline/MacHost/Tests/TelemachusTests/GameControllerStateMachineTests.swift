import Foundation
import XCTest
@testable import Telemachus

final class GameControllerStateMachineTests: XCTestCase {
    func testConnectedWithNeutralStateSucceeds() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 1)
    }

    func testConnectedWithNonNeutralStateThrowsInvalidTransition() {
        var sm = GameControllerStateMachine()
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try sm.accept(.testEvent(kind: .connected, state: state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testStateEventForAttachedControllerSucceeds() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        try sm.accept(.testEvent(inputID: 2, kind: .state, state: state))
    }

    func testStateEventForUnattachedControllerThrowsInvalidTransition() {
        var sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 1, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testStateEventWithWrongEpochThrowsInvalidTransition() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, controllerEpoch: 2, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testDisconnectedWithNeutralStateRemovesAttachment() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        XCTAssertNil(sm.attachments["c1"])
    }

    func testDisconnectedWithNonNeutralStateThrowsInvalidTransition() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, kind: .disconnected, state: state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testDisconnectedWithWrongEpochThrowsInvalidTransition() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, controllerEpoch: 2, kind: .disconnected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testDisconnectedForUnattachedControllerThrowsInvalidTransition() {
        var sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 1, kind: .disconnected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testInputIDMustBeStrictlyIncreasing() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 5, kind: .connected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 5, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 4, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
        try sm.accept(.testEvent(inputID: 6, kind: .state))
    }

    func testEmptyControllerIDThrowsInvalidIdentity() {
        var sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerID: ""))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
    }

    func testControllerIDOver128UTF8BytesThrowsInvalidIdentity() {
        var sm = GameControllerStateMachine()
        let longID = String(repeating: "a", count: 129)
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerID: longID))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
    }

    func testControllerIDExactly128UTF8BytesSucceeds() throws {
        var sm = GameControllerStateMachine()
        let id = String(repeating: "a", count: 128)
        try sm.accept(.testEvent(controllerID: id))
        XCTAssertEqual(sm.attachments[id], 1)
    }

    func testControllerIDWithMultibyteUTF8CountsBytesNotCharacters() throws {
        var sm = GameControllerStateMachine()
        let id128 = String(repeating: "🎮", count: 32)
        XCTAssertEqual(id128.utf8.count, 128)
        try sm.accept(.testEvent(controllerID: id128))
        XCTAssertEqual(sm.attachments[id128], 1)

        let id132 = String(repeating: "🎮", count: 33)
        XCTAssertEqual(id132.utf8.count, 132)
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, controllerID: id132))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
    }

    func testEpochMustBePositive() {
        var sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerEpoch: 0))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidEpoch)
        }
    }

    func testReconnectWithSameEpochThrowsInvalidTransition() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 3, controllerEpoch: 1, kind: .connected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testReconnectWithHigherEpochSucceeds() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        try sm.accept(.testEvent(inputID: 3, controllerEpoch: 2, kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 2)
    }

    func testMaximumControllersIsFour() throws {
        var sm = GameControllerStateMachine()
        for i in 0..<4 {
            let result = try sm.accept(.testEvent(
                inputID: UInt64(i + 1),
                controllerID: "c\(i)",
                kind: .connected
            ))
            XCTAssertEqual(result, .accepted)
        }
        XCTAssertEqual(sm.attachments.count, 4)
        let result = try sm.accept(.testEvent(inputID: 5, controllerID: "c4", kind: .connected))
        XCTAssertEqual(result, .rejectedMaximumActiveControllers)
    }

    func testFifthConnectedSoftRejectConsumesInputIDAndLeavesFirstFourUnchanged() throws {
        var sm = GameControllerStateMachine()
        for i in 0..<4 {
            try sm.accept(.testEvent(
                inputID: UInt64(i + 1),
                controllerID: "c\(i)",
                kind: .connected
            ))
        }

        // The fifth CONNECTED must be soft-rejected: the first four admitted
        // controllers stay attached, and the rejected event's input_id is
        // consumed so the monotonic counter advances.
        let rejectResult = try sm.accept(.testEvent(inputID: 5, controllerID: "c4", kind: .connected))
        XCTAssertEqual(rejectResult, .rejectedMaximumActiveControllers)

        XCTAssertEqual(sm.attachments.count, 4)
        for i in 0..<4 {
            XCTAssertEqual(sm.attachments["c\(i)"], 1, "controller c\(i) must remain attached")
        }

        // A duplicate input_id must now be rejected as invalidIdentity, proving
        // the soft-rejected input_id was consumed by the state machine.
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 5, controllerID: "c5", kind: .connected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }

        // The next strictly-greater input_id is still processed normally.
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        try sm.accept(.testEvent(inputID: 6, controllerID: "c0", kind: .state, state: state))
    }

    func testCopyMutationsDoNotLeakAcrossStateMachineValues() throws {
        var original = GameControllerStateMachine()
        try original.accept(.testEvent(inputID: 1, kind: .connected))
        var copy = original

        try copy.accept(.testEvent(inputID: 2, kind: .disconnected))

        XCTAssertEqual(original.attachments["c1"], 1)
        XCTAssertNil(copy.attachments["c1"])
    }

    func testResetClearsAttachmentsAndAllowsReconnectWithSameEpoch() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        sm.reset()
        XCTAssertTrue(sm.attachments.isEmpty)
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 1)
    }

    func testResetResetsInputIDMonotonicCounter() throws {
        var sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 100, kind: .connected))
        sm.reset()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
    }

    func testInvalidStateThrowsBeforeTransitionChecks() {
        var sm = GameControllerStateMachine()
        let state = GameControllerState(
            buttonMask: 1 << 13,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try sm.accept(.testEvent(kind: .connected, state: state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }
}
