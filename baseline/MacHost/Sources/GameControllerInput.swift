import Foundation
import Darwin
import CryptoKit
import IOKit.hid
import Security

struct GameControllerState: Equatable {
    static let supportedButtonMask: UInt32 = (1 << 13) - 1
    static let neutral = GameControllerState(
        buttonMask: 0,
        leftX: 0,
        leftY: 0,
        rightX: 0,
        rightY: 0,
        leftTrigger: 0,
        rightTrigger: 0,
        hatX: 0,
        hatY: 0
    )

    let buttonMask: UInt32
    let leftX: Double
    let leftY: Double
    let rightX: Double
    let rightY: Double
    let leftTrigger: Double
    let rightTrigger: Double
    let hatX: Int32
    let hatY: Int32

    var isValid: Bool {
        buttonMask & ~Self.supportedButtonMask == 0
            && [leftX, leftY, rightX, rightY].allSatisfy { $0.isFinite && (-1...1).contains($0) }
            && [leftTrigger, rightTrigger].allSatisfy { $0.isFinite && (0...1).contains($0) }
            && (-1...1).contains(hatX)
            && (-1...1).contains(hatY)
    }
}

enum GameControllerHIDReport {
    static let byteCount = 16

    /// Standard game-pad collection: 13 buttons, two sticks, two triggers and
    /// one null-capable hat. Seven trailing bytes are constant padding so the
    /// wire-to-kernel report has a stable 16-byte ABI.
    static let descriptor = Data([
        0x05, 0x01,       // Usage Page (Generic Desktop)
        0x09, 0x05,       // Usage (Game Pad)
        0xA1, 0x01,       // Collection (Application)
        0x05, 0x09,       //   Usage Page (Button)
        0x19, 0x01,       //   Usage Minimum (Button 1)
        0x29, 0x0D,       //   Usage Maximum (Button 13)
        0x15, 0x00,       //   Logical Minimum (0)
        0x25, 0x01,       //   Logical Maximum (1)
        0x75, 0x01,       //   Report Size (1)
        0x95, 0x0D,       //   Report Count (13)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x75, 0x03,       //   Report Size (3)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x03,       //   Input (Constant)
        0x05, 0x01,       //   Usage Page (Generic Desktop)
        0x09, 0x30,       //   Usage (X)
        0x09, 0x31,       //   Usage (Y)
        0x09, 0x33,       //   Usage (Rx)
        0x09, 0x34,       //   Usage (Ry)
        0x15, 0x81,       //   Logical Minimum (-127)
        0x25, 0x7F,       //   Logical Maximum (127)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x04,       //   Report Count (4)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x09, 0x32,       //   Usage (Z / left trigger)
        0x09, 0x35,       //   Usage (Rz / right trigger)
        0x15, 0x00,       //   Logical Minimum (0)
        0x26, 0xFF, 0x00, //   Logical Maximum (255)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x02,       //   Report Count (2)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x09, 0x39,       //   Usage (Hat Switch)
        0x15, 0x00,       //   Logical Minimum (0)
        0x25, 0x07,       //   Logical Maximum (7)
        0x35, 0x00,       //   Physical Minimum (0)
        0x46, 0x3B, 0x01, //   Physical Maximum (315)
        0x65, 0x14,       //   Unit (Degrees)
        0x75, 0x04,       //   Report Size (4)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x42,       //   Input (Data, Variable, Absolute, Null State)
        0x65, 0x00,       //   Unit (None)
        0x75, 0x04,       //   Report Size (4)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x03,       //   Input (Constant)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x07,       //   Report Count (7)
        0x81, 0x03,       //   Input (Constant)
        0xC0,             // End Collection
    ])

    static func encode(_ state: GameControllerState) throws -> Data {
        guard state.isValid else { throw GameControllerInputError.invalidState }
        var bytes = [UInt8](repeating: 0, count: byteCount)
        bytes[0] = UInt8(truncatingIfNeeded: state.buttonMask)
        bytes[1] = UInt8(truncatingIfNeeded: state.buttonMask >> 8)
        bytes[2] = UInt8(bitPattern: signedAxis(state.leftX))
        bytes[3] = UInt8(bitPattern: signedAxis(state.leftY))
        bytes[4] = UInt8(bitPattern: signedAxis(state.rightX))
        bytes[5] = UInt8(bitPattern: signedAxis(state.rightY))
        bytes[6] = unsignedAxis(state.leftTrigger)
        bytes[7] = unsignedAxis(state.rightTrigger)
        bytes[8] = hatValue(x: state.hatX, y: state.hatY)
        return Data(bytes)
    }

    private static func signedAxis(_ value: Double) -> Int8 {
        Int8((value * 127).rounded().clamped(to: -127...127))
    }

    private static func unsignedAxis(_ value: Double) -> UInt8 {
        UInt8((value * 255).rounded().clamped(to: 0...255))
    }

    private static func hatValue(x: Int32, y: Int32) -> UInt8 {
        switch (x, y) {
        case (0, -1): return 0
        case (1, -1): return 1
        case (1, 0): return 2
        case (1, 1): return 3
        case (0, 1): return 4
        case (-1, 1): return 5
        case (-1, 0): return 6
        case (-1, -1): return 7
        default: return 8
        }
    }
}

private extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

enum GameControllerInputError: Error, Equatable, LocalizedError {
    case unavailable(String)
    case invalidIdentity
    case invalidEpoch
    case invalidState
    case invalidTransition
    case maximumControllersReached
    case deviceCreationFailed
    case reportFailed(Int32)

    var errorDescription: String? {
        switch self {
        case .unavailable(let reason): return "Virtual game controller unavailable: \(reason)"
        case .invalidIdentity: return "Controller input or device identity is missing, oversized, or stale."
        case .invalidEpoch: return "Controller attachment epoch is invalid."
        case .invalidState: return "Controller state is outside the Protocol v1 range."
        case .invalidTransition: return "Controller event violates the attachment state machine."
        case .maximumControllersReached: return "At most four controllers can be attached."
        case .deviceCreationFailed: return "IOHIDUserDevice creation failed."
        case .reportFailed(let result): return "IOHIDUserDevice report failed with IOReturn \(result)."
        }
    }
}

protocol VirtualGamepadDevice: AnyObject {
    func submit(_ state: GameControllerState) throws
    func close() throws
}

protocol VirtualGamepadFactory {
    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice
}

struct GameControllerRuntimeAvailability {
    static let entitlement = "com.apple.developer.hid.virtual.device" as CFString

    let factory: VirtualGamepadFactory?
    let unavailableReason: String?

    static func probe() -> GameControllerRuntimeAvailability {
        probe(
            identitySigned: hasNonAdHocSignature(),
            entitlementPresent: hasVirtualHIDEntitlement(),
            factory: IOKitVirtualGamepadFactory()
        )
    }

    static func probe(
        identitySigned: Bool,
        entitlementPresent: Bool,
        factory: VirtualGamepadFactory
    ) -> GameControllerRuntimeAvailability {
        guard identitySigned else {
            return .init(
                factory: nil,
                unavailableReason: "use an Apple identity-signed build with the approved virtual HID entitlement; unsigned and ad-hoc builds cannot create virtual controllers"
            )
        }
        guard entitlementPresent else {
            return .init(
                factory: nil,
                unavailableReason: "request Apple approval for com.apple.developer.hid.virtual.device and include it in the signed provisioning profile"
            )
        }
        do {
            let device = try factory.makeDevice(controllerID: "runtime-probe", controllerEpoch: 1)
            try device.close()
            return .init(factory: factory, unavailableReason: nil)
        } catch {
            return .init(
                factory: nil,
                unavailableReason: "IOHID runtime probe failed: \(error.localizedDescription) Verify the approved entitlement is present in the running app's signature and provisioning profile."
            )
        }
    }

    private static func hasVirtualHIDEntitlement() -> Bool {
        guard let task = SecTaskCreateFromSelf(kCFAllocatorDefault) else { return false }
        var error: Unmanaged<CFError>?
        let value = SecTaskCopyValueForEntitlement(task, entitlement, &error)
        return (value as? Bool) == true
    }

    private static func hasNonAdHocSignature() -> Bool {
        var code: SecCode?
        guard SecCodeCopySelf(SecCSFlags(rawValue: 0), &code) == errSecSuccess, let code else { return false }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, SecCSFlags(rawValue: 0), &staticCode) == errSecSuccess,
              let staticCode else { return false }
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let dictionary = information as? [CFString: Any],
              let teamIdentifier = dictionary[kSecCodeInfoTeamIdentifier] as? String else { return false }
        return !teamIdentifier.isEmpty
    }
}

final class IOKitVirtualGamepadFactory: VirtualGamepadFactory {
    private let provider: VirtualGamepadIOProvider

    init(provider: VirtualGamepadIOProvider = ProductionVirtualGamepadIOProvider()) {
        self.provider = provider
    }

    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice {
        try IOKitVirtualGamepadDevice(
            controllerID: controllerID,
            controllerEpoch: controllerEpoch,
            provider: provider
        )
    }
}

protocol VirtualGamepadIOHandle: AnyObject {
    func submit(report: Data) -> IOReturn
    func cancel()
}

protocol VirtualGamepadIOProvider {
    func create(properties: [String: Any], queue: DispatchQueue) -> VirtualGamepadIOHandle?
}

final class ProductionVirtualGamepadIOProvider: VirtualGamepadIOProvider {
    func create(properties: [String: Any], queue: DispatchQueue) -> VirtualGamepadIOHandle? {
        guard let device = IOHIDUserDeviceCreateWithProperties(
            kCFAllocatorDefault,
            properties as CFDictionary,
            0
        ) else { return nil }
        return ProductionVirtualGamepadIOHandle(device: device, queue: queue)
    }
}

final class ProductionVirtualGamepadIOHandle: VirtualGamepadIOHandle {
    private let device: IOHIDUserDevice

    init(device: IOHIDUserDevice, queue: DispatchQueue) {
        self.device = device
        IOHIDUserDeviceSetDispatchQueue(device, queue)
        IOHIDUserDeviceSetCancelHandler(device) { _ = device }
        IOHIDUserDeviceActivate(device)
    }

    func submit(report: Data) -> IOReturn {
        report.withUnsafeBytes { bytes in
            guard let base = bytes.baseAddress?.assumingMemoryBound(to: UInt8.self) else {
                return kIOReturnBadArgument
            }
            return IOHIDUserDeviceHandleReportWithTimeStamp(
                device,
                mach_absolute_time(),
                base,
                report.count
            )
        }
    }

    func cancel() { IOHIDUserDeviceCancel(device) }
}

final class IOKitVirtualGamepadDevice: VirtualGamepadDevice {
    private let queue: DispatchQueue
    private let handle: VirtualGamepadIOHandle
    private var closed = false

    init(
        controllerID: String,
        controllerEpoch: UInt64,
        provider: VirtualGamepadIOProvider
    ) throws {
        queue = DispatchQueue(label: "dev.vibescreen.virtual-gamepad.\(controllerEpoch)")
        let properties: [String: Any] = [
            kIOHIDReportDescriptorKey: GameControllerHIDReport.descriptor,
            kIOHIDVendorIDKey: 0x5653,
            kIOHIDProductIDKey: 0x0001,
            kIOHIDVersionNumberKey: 1,
            kIOHIDPrimaryUsagePageKey: kHIDPage_GenericDesktop,
            kIOHIDPrimaryUsageKey: kHIDUsage_GD_GamePad,
            kIOHIDProductKey: "Vibe Screen Controller",
            kIOHIDSerialNumberKey: Self.virtualSerialNumber(
                controllerID: controllerID,
                controllerEpoch: controllerEpoch
            ),
        ]
        guard let created = provider.create(properties: properties, queue: queue) else {
            throw GameControllerInputError.deviceCreationFailed
        }
        handle = created
    }

    private static func virtualSerialNumber(
        controllerID: String,
        controllerEpoch: UInt64
    ) -> String {
        var material = Data(controllerID.utf8)
        var epoch = controllerEpoch.bigEndian
        withUnsafeBytes(of: &epoch) { material.append(contentsOf: $0) }
        return SHA256.hash(data: material).prefix(16).map {
            String(format: "%02x", $0)
        }.joined()
    }

    func submit(_ state: GameControllerState) throws {
        let report = try GameControllerHIDReport.encode(state)
        try queue.sync {
            guard !closed else { throw GameControllerInputError.invalidTransition }
            try handle(report)
        }
    }

    func close() throws {
        try queue.sync {
            guard !closed else { return }
            closed = true
            var reportError: Error?
            do {
                try handle(try GameControllerHIDReport.encode(.neutral))
            } catch {
                reportError = error
            }
            handle.cancel()
            if let reportError { throw reportError }
        }
    }

    private func handle(_ report: Data) throws {
        let result = handle.submit(report: report)
        guard result == kIOReturnSuccess else {
            throw GameControllerInputError.reportFailed(result)
        }
    }
}

enum GameControllerEventKind: Equatable {
    case connected
    case state
    case disconnected
}

struct GameControllerInputEvent: Equatable {
    let inputID: UInt64
    let controllerID: String
    let controllerEpoch: UInt64
    let kind: GameControllerEventKind
    let state: GameControllerState
}

final class GameControllerStateMachine {
    static let maximumControllerIDBytes = 128
    private(set) var attachments: [String: UInt64] = [:]
    private var lastEpochs: [String: UInt64] = [:]
    private var lastInputID: UInt64 = 0
    let maximumControllers: Int

    init(maximumControllers: Int = 4) {
        self.maximumControllers = maximumControllers
    }

    func accept(_ event: GameControllerInputEvent) throws {
        guard event.inputID > lastInputID else { throw GameControllerInputError.invalidIdentity }
        guard !event.controllerID.isEmpty,
              event.controllerID.utf8.count <= Self.maximumControllerIDBytes else {
            throw GameControllerInputError.invalidIdentity
        }
        guard event.controllerEpoch > 0 else { throw GameControllerInputError.invalidEpoch }
        guard event.state.isValid else { throw GameControllerInputError.invalidState }

        switch event.kind {
        case .connected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == nil,
                  event.controllerEpoch > (lastEpochs[event.controllerID] ?? 0) else {
                throw GameControllerInputError.invalidTransition
            }
            guard attachments.count < maximumControllers else {
                throw GameControllerInputError.maximumControllersReached
            }
            attachments[event.controllerID] = event.controllerEpoch
            lastEpochs[event.controllerID] = event.controllerEpoch
        case .state:
            guard attachments[event.controllerID] == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
        case .disconnected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            attachments.removeValue(forKey: event.controllerID)
        }
        lastInputID = event.inputID
    }

    func reset() {
        attachments.removeAll()
        lastEpochs.removeAll()
        lastInputID = 0
    }
}

final class GameControllerInjector {
    private struct Attachment {
        let epoch: UInt64
        let device: VirtualGamepadDevice
    }

    private let factory: VirtualGamepadFactory
    private let maximumControllers: Int
    private var generation: UInt64?
    private var attachments: [String: Attachment] = [:]

    init(factory: VirtualGamepadFactory, maximumControllers: Int = 4) {
        self.factory = factory
        self.maximumControllers = maximumControllers
    }

    func handle(_ event: GameControllerInputEvent, generation: UInt64) throws {
        if self.generation != generation {
            try reset()
            self.generation = generation
        }
        switch event.kind {
        case .connected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == nil else {
                throw GameControllerInputError.invalidTransition
            }
            guard attachments.count < maximumControllers else {
                throw GameControllerInputError.maximumControllersReached
            }
            let device = try factory.makeDevice(
                controllerID: event.controllerID,
                controllerEpoch: event.controllerEpoch
            )
            do {
                try device.submit(.neutral)
                attachments[event.controllerID] = Attachment(
                    epoch: event.controllerEpoch,
                    device: device
                )
            } catch {
                try? device.close()
                throw error
            }
        case .state:
            guard let attachment = attachments[event.controllerID],
                  attachment.epoch == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            try attachment.device.submit(event.state)
        case .disconnected:
            guard event.state == .neutral,
                  let attachment = attachments[event.controllerID],
                  attachment.epoch == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            attachments.removeValue(forKey: event.controllerID)
            try attachment.device.close()
        }
    }

    func reset() throws {
        let devices = attachments.keys.sorted().compactMap { attachments[$0]?.device }
        attachments.removeAll()
        generation = nil
        var firstError: Error?
        for device in devices {
            do { try device.close() } catch { if firstError == nil { firstError = error } }
        }
        if let firstError { throw firstError }
    }
}
