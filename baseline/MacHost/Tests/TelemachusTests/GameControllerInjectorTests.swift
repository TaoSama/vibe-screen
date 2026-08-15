import Foundation
import XCTest
import IOKit
@testable import Telemachus

final class GameControllerInjectorTests: XCTestCase {
    func testConnectedCreatesDeviceAndSubmitsNeutral() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)

        try injector.handle(.testEvent(kind: .connected), generation: 1)

        XCTAssertEqual(factory.devices.count, 1)
        let device = factory.devices[0]
        XCTAssertEqual(device.controllerID, "c1")
        XCTAssertEqual(device.controllerEpoch, 1)
        XCTAssertEqual(device.submittedStates, [.neutral])
    }

    func testStateForwardsToDevice() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, kind: .connected), generation: 1)

        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        try injector.handle(.testEvent(inputID: 2, kind: .state, state: state), generation: 1)

        let device = factory.devices[0]
        XCTAssertEqual(device.submittedStates.count, 2)
        XCTAssertEqual(device.submittedStates[1], state)
    }

    func testDisconnectedClosesDevice() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, kind: .connected), generation: 1)
        try injector.handle(.testEvent(inputID: 2, kind: .disconnected), generation: 1)

        let device = factory.devices[0]
        XCTAssertEqual(device.closeCount, 1)
    }

    func testGenerationChangeResetsAndClosesExistingDevice() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, kind: .connected), generation: 1)
        let device = factory.devices[0]

        try injector.handle(.testEvent(inputID: 2, kind: .connected), generation: 2)

        XCTAssertEqual(device.closeCount, 1)
        XCTAssertEqual(factory.devices.count, 2)
    }

    func testResetClosesAllDevices() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, controllerID: "c1", kind: .connected), generation: 1)
        try injector.handle(.testEvent(inputID: 2, controllerID: "c2", kind: .connected), generation: 1)

        try injector.reset()

        XCTAssertEqual(factory.devices[0].closeCount, 1)
        XCTAssertEqual(factory.devices[1].closeCount, 1)
    }

    func testResetThrowsFirstCloseErrorButStillClosesAll() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, controllerID: "c1", kind: .connected), generation: 1)
        try injector.handle(.testEvent(inputID: 2, controllerID: "c2", kind: .connected), generation: 1)

        factory.devices[0].closeError = GameControllerInputError.reportFailed(kIOReturnBadArgument)

        XCTAssertThrowsError(try injector.reset()) { error in
            XCTAssertEqual(error as? GameControllerInputError, .reportFailed(kIOReturnBadArgument))
        }
        XCTAssertEqual(factory.devices[0].closeCount, 1)
        XCTAssertEqual(factory.devices[1].closeCount, 1)
    }

    func testConnectedWithNonNeutralStateThrowsAndCreatesNoDevice() {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try injector.handle(.testEvent(kind: .connected, state: state), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
        XCTAssertTrue(factory.devices.isEmpty)
    }

    func testStateForUnknownControllerThrowsInvalidTransition() {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        XCTAssertThrowsError(try injector.handle(.testEvent(kind: .state), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testStateWithWrongEpochThrowsInvalidTransition() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected), generation: 1)
        XCTAssertThrowsError(try injector.handle(.testEvent(inputID: 2, controllerEpoch: 2, kind: .state), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testMaximumControllersEnforced() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        for i in 0..<4 {
            try injector.handle(.testEvent(
                inputID: UInt64(i + 1),
                controllerID: "c\(i)",
                kind: .connected
            ), generation: 1)
        }
        XCTAssertThrowsError(try injector.handle(.testEvent(inputID: 5, controllerID: "c4", kind: .connected), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .maximumControllersReached)
        }
    }

    func testConnectedSubmitFailureClosesDeviceBeforeRethrowing() throws {
        let factory = FakeVirtualGamepadFactory()
        factory.submitError = GameControllerInputError.reportFailed(kIOReturnBadArgument)
        let injector = GameControllerInjector(factory: factory)

        XCTAssertThrowsError(try injector.handle(.testEvent(kind: .connected), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .reportFailed(kIOReturnBadArgument))
        }
        XCTAssertEqual(factory.devices.count, 1)
        XCTAssertEqual(factory.devices[0].closeCount, 1)
    }

    func testDisconnectedWithWrongEpochThrowsInvalidTransition() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(.testEvent(inputID: 1, controllerEpoch: 1, kind: .connected), generation: 1)
        XCTAssertThrowsError(try injector.handle(.testEvent(inputID: 2, controllerEpoch: 2, kind: .disconnected), generation: 1)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }
}
