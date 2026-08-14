import Foundation
import IOKit.hid
import XCTest
@testable import Telemachus

final class GameControllerInputTests: XCTestCase {
    func testDescriptorAndSixteenByteReportEncodeCanonicalState() throws {
        XCTAssertEqual(GameControllerHIDReport.descriptor.first, 0x05)
        XCTAssertEqual(GameControllerHIDReport.descriptor.last, 0xC0)
        let state = GameControllerState(
            buttonMask: 0x1001,
            leftX: -1,
            leftY: 1,
            rightX: 0.5,
            rightY: -0.5,
            leftTrigger: 0,
            rightTrigger: 1,
            hatX: 1,
            hatY: -1
        )
        let report = [UInt8](try GameControllerHIDReport.encode(state))
        XCTAssertEqual(report.count, 16)
        XCTAssertEqual(Array(report[0...1]), [0x01, 0x10])
        XCTAssertEqual(report[2], UInt8(bitPattern: -127))
        XCTAssertEqual(report[3], 127)
        XCTAssertEqual(Array(report[6...7]), [0, 255])
        XCTAssertEqual(report[8], 1)
        XCTAssertEqual(Array(report[9...15]), Array(repeating: 0, count: 7))
        XCTAssertEqual(inputReportBitCount(in: GameControllerHIDReport.descriptor), 128)
        XCTAssertTrue(GameControllerHIDReport.descriptor.containsSubsequence([
            0x19, 0x01, 0x29, 0x0D,
        ]))
        XCTAssertTrue(GameControllerHIDReport.descriptor.containsSubsequence([
            0x09, 0x30, 0x09, 0x31, 0x09, 0x33, 0x09, 0x34,
        ]))
        XCTAssertTrue(GameControllerHIDReport.descriptor.containsSubsequence([
            0x09, 0x39, 0x15, 0x00, 0x25, 0x07,
        ]))
    }

    func testEncoderRejectsReservedButtonsAxesTriggersAndHat() {
        let invalid = [
            state(buttonMask: 1 << 13),
            state(leftX: 1.01),
            state(leftTrigger: -0.01),
            state(hatX: 2),
        ]
        for sample in invalid {
            XCTAssertThrowsError(try GameControllerHIDReport.encode(sample))
        }
    }

    func testStateMachineRequiresMonotonicInputAndAttachmentEpoch() throws {
        let machine = GameControllerStateMachine()
        try machine.accept(event(inputID: 1, epoch: 4, kind: .connected))
        try machine.accept(event(inputID: 2, epoch: 4, kind: .state, state: state(buttonMask: 1)))
        XCTAssertThrowsError(try machine.accept(event(inputID: 2, epoch: 4, kind: .state)))
        try machine.accept(event(inputID: 3, epoch: 4, kind: .disconnected))
        XCTAssertThrowsError(try machine.accept(event(inputID: 4, epoch: 4, kind: .connected)))
        try machine.accept(event(inputID: 5, epoch: 5, kind: .connected))
    }

    func testControllerIDAccepts128UTF8BytesAndRejects129() throws {
        let accepted = GameControllerStateMachine()
        try accepted.accept(event(
            inputID: 1,
            id: String(repeating: "a", count: 128),
            epoch: 1,
            kind: .connected
        ))
        let rejected = GameControllerStateMachine()
        XCTAssertThrowsError(try rejected.accept(event(
            inputID: 1,
            id: String(repeating: "a", count: 129),
            epoch: 1,
            kind: .connected
        )))
        XCTAssertThrowsError(try GameControllerStateMachine().accept(event(
            inputID: 1,
            id: String(repeating: "\u{754C}", count: 43),
            epoch: 1,
            kind: .connected
        )))
    }

    func testRuntimeProbeRequiresSignatureEntitlementAndSuccessfulDeviceProbe() {
        let unsigned = FakeVirtualGamepadFactory()
        XCTAssertNil(GameControllerRuntimeAvailability.probe(
            identitySigned: false,
            entitlementPresent: true,
            factory: unsigned
        ).factory)
        XCTAssertTrue(unsigned.devices.isEmpty)

        let missingEntitlement = FakeVirtualGamepadFactory()
        XCTAssertNil(GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: false,
            factory: missingEntitlement
        ).factory)
        XCTAssertTrue(missingEntitlement.devices.isEmpty)

        let available = FakeVirtualGamepadFactory()
        XCTAssertNotNil(GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: true,
            factory: available
        ).factory)
        XCTAssertEqual(available.devices.count, 1)
        XCTAssertEqual(available.devices[0].closeCount, 1)

        let failedProbe = GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: true,
            factory: FailingProbeVirtualGamepadFactory()
        )
        XCTAssertNil(failedProbe.factory)
        XCTAssertTrue(failedProbe.unavailableReason?.contains("runtime probe failed") == true)
    }

    func testIOShimCloseSubmitsNeutralThenCancelsExactlyOnce() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadFactory(provider: provider).makeDevice(
            controllerID: "pad",
            controllerEpoch: 1
        )
        try device.close()
        try device.close()
        XCTAssertFalse(
            (provider.properties?[kIOHIDSerialNumberKey] as? String)?.contains("pad") ?? true
        )
        XCTAssertEqual(provider.handle.operations, [
            .report(try GameControllerHIDReport.encode(.neutral)),
            .cancel,
        ])
        XCTAssertThrowsError(try IOKitVirtualGamepadFactory(
            provider: RejectingVirtualGamepadIOProvider()
        ).makeDevice(controllerID: "pad", controllerEpoch: 2))
    }

    func testInjectorSupportsFourControllersAndResetsOnGenerationChange() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        for index in 0..<4 {
            try injector.handle(
                event(inputID: UInt64(index + 1), id: "pad-\(index)", epoch: 1, kind: .connected),
                generation: 9
            )
        }
        XCTAssertThrowsError(try injector.handle(
            event(inputID: 5, id: "overflow", epoch: 1, kind: .connected),
            generation: 9
        ))
        try injector.handle(
            event(inputID: 6, id: "replacement", epoch: 1, kind: .connected),
            generation: 10
        )
        XCTAssertEqual(factory.devices.prefix(4).map(\.closeCount), [1, 1, 1, 1])
        XCTAssertEqual(factory.devices.last?.states, [.neutral])
    }

    func testDisconnectAndResetCloseExactlyOnce() throws {
        let factory = FakeVirtualGamepadFactory()
        let injector = GameControllerInjector(factory: factory)
        try injector.handle(event(inputID: 1, epoch: 1, kind: .connected), generation: 1)
        try injector.handle(
            event(inputID: 2, epoch: 1, kind: .state, state: state(buttonMask: 3)),
            generation: 1
        )
        try injector.handle(event(inputID: 3, epoch: 1, kind: .disconnected), generation: 1)
        try injector.reset()
        XCTAssertEqual(factory.devices[0].states, [.neutral, state(buttonMask: 3)])
        XCTAssertEqual(factory.devices[0].closeCount, 1)
    }

    private func state(
        buttonMask: UInt32 = 0,
        leftX: Double = 0,
        leftTrigger: Double = 0,
        hatX: Int32 = 0
    ) -> GameControllerState {
        GameControllerState(
            buttonMask: buttonMask,
            leftX: leftX,
            leftY: 0,
            rightX: 0,
            rightY: 0,
            leftTrigger: leftTrigger,
            rightTrigger: 0,
            hatX: hatX,
            hatY: 0
        )
    }

    private func event(
        inputID: UInt64,
        id: String = "pad",
        epoch: UInt64,
        kind: GameControllerEventKind,
        state: GameControllerState = .neutral
    ) -> GameControllerInputEvent {
        GameControllerInputEvent(
            inputID: inputID,
            controllerID: id,
            controllerEpoch: epoch,
            kind: kind,
            state: state
        )
    }

    private func inputReportBitCount(in descriptor: Data) -> Int {
        let bytes = [UInt8](descriptor)
        var index = 0
        var reportSize = 0
        var reportCount = 0
        var total = 0
        while index < bytes.count {
            let prefix = bytes[index]
            index += 1
            if prefix == 0xFE {
                guard index + 2 <= bytes.count else { return -1 }
                let length = Int(bytes[index])
                index += 2 + length
                continue
            }
            let encodedSize = Int(prefix & 0x03)
            let size = encodedSize == 3 ? 4 : encodedSize
            guard index + size <= bytes.count else { return -1 }
            let value = size == 0 ? 0 : Int(bytes[index])
            let type = (prefix >> 2) & 0x03
            let tag = (prefix >> 4) & 0x0F
            if type == 1, tag == 7 { reportSize = value }
            if type == 1, tag == 9 { reportCount = value }
            if type == 0, tag == 8 { total += reportSize * reportCount }
            index += size
        }
        return total
    }
}

private extension Data {
    func containsSubsequence(_ subsequence: [UInt8]) -> Bool {
        guard !subsequence.isEmpty, subsequence.count <= count else { return false }
        let bytes = [UInt8](self)
        return (0...(bytes.count - subsequence.count)).contains {
            Array(bytes[$0..<($0 + subsequence.count)]) == subsequence
        }
    }
}

private enum FakeVirtualGamepadIOOperation: Equatable {
    case report(Data)
    case cancel
}

private final class FakeVirtualGamepadIOHandle: VirtualGamepadIOHandle {
    private(set) var operations: [FakeVirtualGamepadIOOperation] = []

    func submit(report: Data) -> IOReturn {
        operations.append(.report(report))
        return kIOReturnSuccess
    }

    func cancel() { operations.append(.cancel) }
}

private final class FakeVirtualGamepadIOProvider: VirtualGamepadIOProvider {
    let handle = FakeVirtualGamepadIOHandle()
    private(set) var properties: [String: Any]?

    func create(properties: [String: Any], queue: DispatchQueue) -> VirtualGamepadIOHandle? {
        self.properties = properties
        return handle
    }
}

private struct RejectingVirtualGamepadIOProvider: VirtualGamepadIOProvider {
    func create(properties: [String: Any], queue: DispatchQueue) -> VirtualGamepadIOHandle? {
        nil
    }
}

private final class FakeVirtualGamepadFactory: VirtualGamepadFactory {
    private(set) var devices: [FakeVirtualGamepadDevice] = []

    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice {
        let device = FakeVirtualGamepadDevice()
        devices.append(device)
        return device
    }
}

private final class FakeVirtualGamepadDevice: VirtualGamepadDevice {
    private(set) var states: [GameControllerState] = []
    private(set) var closeCount = 0

    func submit(_ state: GameControllerState) throws { states.append(state) }
    func close() throws { closeCount += 1 }
}

private struct FailingProbeVirtualGamepadFactory: VirtualGamepadFactory {
    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice {
        FailingProbeVirtualGamepadDevice()
    }
}

private final class FailingProbeVirtualGamepadDevice: VirtualGamepadDevice {
    func submit(_ state: GameControllerState) throws {}
    func close() throws { throw GameControllerInputError.reportFailed(-1) }
}
