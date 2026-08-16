import Foundation
import XCTest
import IOKit
@testable import Telemachus

// MARK: - Fakes

final class FakeVirtualGamepadIOHandle: VirtualGamepadIOHandle {
    private let lock = NSLock()
    private var reports: [Data] = []
    private var cancellations = 0
    private var result: IOReturn = kIOReturnSuccess
    private var cancelCallback: (() -> Void)?

    var submitResult: IOReturn {
        get {
            lock.lock()
            defer { lock.unlock() }
            return result
        }
        set {
            lock.lock()
            result = newValue
            lock.unlock()
        }
    }

    func setOnCancel(_ callback: @escaping () -> Void) {
        lock.lock()
        cancelCallback = callback
        lock.unlock()
    }

    var submittedReports: [Data] {
        lock.lock()
        defer { lock.unlock() }
        return reports
    }

    var cancelCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return cancellations
    }

    func submit(report: Data) -> IOReturn {
        lock.lock()
        reports.append(report)
        let currentResult = result
        lock.unlock()
        return currentResult
    }

    func cancel() {
        lock.lock()
        cancellations += 1
        let callback = cancelCallback
        lock.unlock()
        callback?()
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
