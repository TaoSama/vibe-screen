import Foundation
import XCTest
import IOKit
@testable import Telemachus

// MARK: - Fakes

final class FakeVirtualGamepadIOHandle: VirtualGamepadIOHandle {
    private(set) var submittedReports: [Data] = []
    var submitResult: IOReturn = kIOReturnSuccess
    private(set) var cancelCount = 0

    func submit(report: Data) -> IOReturn {
        submittedReports.append(report)
        return submitResult
    }

    func cancel() {
        cancelCount += 1
    }
}

final class FakeVirtualGamepadIOProvider: VirtualGamepadIOProvider {
    private(set) var createdHandle: FakeVirtualGamepadIOHandle?
    private(set) var lastProperties: [String: Any]?
    var shouldFailCreation = false

    func create(properties: [String: Any], queue: DispatchQueue) -> VirtualGamepadIOHandle? {
        if shouldFailCreation { return nil }
        let handle = FakeVirtualGamepadIOHandle()
        createdHandle = handle
        lastProperties = properties
        return handle
    }
}

final class FakeVirtualGamepadDevice: VirtualGamepadDevice {
    let controllerID: String
    let controllerEpoch: UInt64
    private(set) var submittedStates: [GameControllerState] = []
    var submitError: Error?
    private(set) var closeCount = 0
    var closeError: Error?

    init(controllerID: String, controllerEpoch: UInt64) {
        self.controllerID = controllerID
        self.controllerEpoch = controllerEpoch
    }

    func submit(_ state: GameControllerState) throws {
        if let submitError { throw submitError }
        submittedStates.append(state)
    }

    func close() throws {
        closeCount += 1
        if let closeError { throw closeError }
    }
}

final class FakeVirtualGamepadFactory: VirtualGamepadFactory {
    private(set) var devices: [FakeVirtualGamepadDevice] = []
    var makeError: Error?
    var submitError: Error?
    var closeError: Error?

    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice {
        if let makeError { throw makeError }
        let device = FakeVirtualGamepadDevice(controllerID: controllerID, controllerEpoch: controllerEpoch)
        device.submitError = submitError
        device.closeError = closeError
        devices.append(device)
        return device
    }
}

// MARK: - Shared event builder

extension GameControllerInputEvent {
    static func testEvent(
        inputID: UInt64 = 1,
        controllerID: String = "c1",
        controllerEpoch: UInt64 = 1,
        kind: GameControllerEventKind = .connected,
        state: GameControllerState = .neutral
    ) -> GameControllerInputEvent {
        GameControllerInputEvent(
            inputID: inputID,
            controllerID: controllerID,
            controllerEpoch: controllerEpoch,
            kind: kind,
            state: state
        )
    }
}
