import Foundation
import Darwin
import CryptoKit
import IOKit.hid
import Security

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
                unavailableReason: "request Apple approval for the com.apple.developer.hid.virtual.device entitlement and include it in the signed provisioning profile"
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
        error?.release()
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
    private let cancellationLock = NSLock()
    private var cancelled = false

    init(device: IOHIDUserDevice, queue: DispatchQueue) {
        self.device = device
        IOHIDUserDeviceSetDispatchQueue(device, queue)
        // Cancellation is asynchronous. Keep one unmanaged retain until IOKit
        // runs the handler so releasing this Swift handle cannot deallocate the
        // device while the kernel is still tearing it down. The handler stores
        // only an unmanaged token, avoiding a device -> block -> device cycle.
        let cancellationRetain = Unmanaged.passRetained(device)
        IOHIDUserDeviceSetCancelHandler(device) {
            cancellationRetain.release()
        }
        IOHIDUserDeviceActivate(device)
    }

    func submit(report: Data) -> IOReturn {
        cancellationLock.lock()
        defer { cancellationLock.unlock() }
        guard !cancelled else { return kIOReturnNotReady }

        return report.withUnsafeBytes { bytes in
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

    func cancel() {
        cancellationLock.lock()
        guard !cancelled else {
            cancellationLock.unlock()
            return
        }
        cancelled = true
        cancellationLock.unlock()
        IOHIDUserDeviceCancel(device)
    }

    deinit {
        cancel()
    }
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
            kIOHIDPrimaryUsagePageKey: Int(kHIDPage_GenericDesktop),
            kIOHIDPrimaryUsageKey: Int(kHIDUsage_GD_GamePad),
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
            try submitReport(report)
        }
    }

    func close() throws {
        try queue.sync {
            guard !closed else { return }
            closed = true
            var reportError: Error?
            do {
                try submitReport(try GameControllerHIDReport.encode(.neutral))
            } catch {
                reportError = error
            }
            handle.cancel()
            if let reportError { throw reportError }
        }
    }

    deinit {
        guard !closed else { return }
        // A caller that still owns the device must use close(), which reports
        // neutralization failures. Deinit is only the non-blocking last resort:
        // preserve report-before-cancel ordering without synchronously hopping
        // onto a queue that may currently be releasing this object.
        let handle = handle
        let neutralReport = try? GameControllerHIDReport.encode(.neutral)
        queue.async {
            if let neutralReport { _ = handle.submit(report: neutralReport) }
            handle.cancel()
        }
    }

    private func submitReport(_ report: Data) throws {
        let result = handle.submit(report: report)
        guard result == kIOReturnSuccess else {
            throw GameControllerInputError.reportFailed(result)
        }
    }
}
