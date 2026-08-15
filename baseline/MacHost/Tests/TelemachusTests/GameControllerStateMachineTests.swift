import Foundation
import XCTest
@testable import Telemachus

final class GameControllerStateMachineTests: XCTestCase {
    func testConnectedWithNeutralStateSucceeds() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 1)
    }

    func testConnectedWithNonNeutralStateThrowsInvalidTransition() {
        let sm = GameControllerStateMachine()
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try sm.accept(.testEvent(kind: .connected, state: state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testStateEventForAttachedControllerSucceeds() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        try sm.accept(.testEvent(inputID: 2, kind: .state, state: state))
    }

    func testStateEventForUnattachedControllerThrowsInvalidTransition() {
        let sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 1, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testStateEventWithWrongEpochThrowsInvalidTransition() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, controllerEpoch: 2, kind: .state))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testDisconnectedWithNeutralStateRemovesAttachment() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        XCTAssertNil(sm.attachments["c1"])
    }

    func testDisconnectedWithNonNeutralStateThrowsInvalidTransition() throws {
        let sm = GameControllerStateMachine()
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
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 2, controllerEpoch: 2, kind: .disconnected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testDisconnectedForUnattachedControllerThrowsInvalidTransition() {
        let sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 1, kind: .disconnected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testInputIDMustBeStrictlyIncreasing() throws {
        let sm = GameControllerStateMachine()
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
        let sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerID: ""))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
    }

    func testControllerIDOver128UTF8BytesThrowsInvalidIdentity() {
        let sm = GameControllerStateMachine()
        let longID = String(repeating: "a", count: 129)
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerID: longID))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidIdentity)
        }
    }

    func testControllerIDExactly128UTF8BytesSucceeds() throws {
        let sm = GameControllerStateMachine()
        let id = String(repeating: "a", count: 128)
        try sm.accept(.testEvent(controllerID: id))
        XCTAssertEqual(sm.attachments[id], 1)
    }

    func testControllerIDWithMultibyteUTF8CountsBytesNotCharacters() throws {
        let sm = GameControllerStateMachine()
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
        let sm = GameControllerStateMachine()
        XCTAssertThrowsError(try sm.accept(.testEvent(controllerEpoch: 0))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidEpoch)
        }
    }

    func testReconnectWithSameEpochThrowsInvalidTransition() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 3, controllerEpoch: 1, kind: .connected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testReconnectWithHigherEpochSucceeds() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        try sm.accept(.testEvent(inputID: 2, kind: .disconnected))
        try sm.accept(.testEvent(inputID: 3, controllerEpoch: 2, kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 2)
    }

    func testMaximumControllersIsFour() throws {
        let sm = GameControllerStateMachine()
        for i in 0..<4 {
            try sm.accept(.testEvent(
                inputID: UInt64(i + 1),
                controllerID: "c\(i)",
                kind: .connected
            ))
        }
        XCTAssertEqual(sm.attachments.count, 4)
        XCTAssertThrowsError(try sm.accept(.testEvent(inputID: 5, controllerID: "c4", kind: .connected))) { error in
            XCTAssertEqual(error as? GameControllerInputError, .maximumControllersReached)
        }
    }

    func testResetClearsAttachmentsAndAllowsReconnectWithSameEpoch() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        sm.reset()
        XCTAssertTrue(sm.attachments.isEmpty)
        try sm.accept(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected))
        XCTAssertEqual(sm.attachments["c1"], 1)
    }

    func testResetResetsInputIDMonotonicCounter() throws {
        let sm = GameControllerStateMachine()
        try sm.accept(.testEvent(inputID: 100, kind: .connected))
        sm.reset()
        try sm.accept(.testEvent(inputID: 1, kind: .connected))
    }

    func testInvalidStateThrowsBeforeTransitionChecks() {
        let sm = GameControllerStateMachine()
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
