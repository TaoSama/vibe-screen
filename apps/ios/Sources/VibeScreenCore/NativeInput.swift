import Foundation
import VibeScreenProtocol

public enum SessionClosureContext: Equatable, Sendable {
    case manualDisconnect
    case sessionFailure

    public var reportsEnqueueErrors: Bool { self != .manualDisconnect }
    public var clearsErrorOnCompletion: Bool { self == .manualDisconnect }

    public func errorOnCompletion(currentError: String?) -> String? {
        clearsErrorOnCompletion ? nil : currentError
    }

    public func errorAfterEnqueueFailure(
        currentError: String?,
        enqueueError: String
    ) -> String? {
        guard reportsEnqueueErrors else { return currentError }
        return currentError ?? enqueueError
    }

    public func shouldEnqueueDisconnectNotice(
        hasSession: Bool,
        allReleasesAdmitted _: Bool
    ) -> Bool {
        hasSession
    }
}

public struct NativeInputAvailability: Equatable, Sendable {
    public var keyboard: Bool
    public var pointer: Bool

    public init(keyboard: Bool, pointer: Bool) {
        self.keyboard = keyboard
        self.pointer = pointer
    }

    public var advertisedCapabilities: Set<VSCapability> {
        var capabilities: Set<VSCapability> = [.touch]
        if keyboard {
            capabilities.formUnion([.keyboard, .usbHidModifierByte])
        }
        if pointer { capabilities.insert(.pointer) }
        return capabilities
    }
}

public enum USBHIDKeyboardMapper {
    public static func usage(for character: Character) -> UInt32? {
        let scalars = String(character).lowercased().unicodeScalars
        guard scalars.count == 1, let value = scalars.first?.value else { return nil }
        switch value {
        case 0x61 ... 0x7A: return value - 0x61 + 0x04
        case 0x31 ... 0x39: return value - 0x31 + 0x1E
        case 0x30: return 0x27
        case 0x0D, 0x0A: return 0x28
        case 0x09: return 0x2B
        case 0x20: return 0x2C
        case 0x2D, 0x5F: return 0x2D
        case 0x3D, 0x2B: return 0x2E
        case 0x5B, 0x7B: return 0x2F
        case 0x5D, 0x7D: return 0x30
        case 0x5C, 0x7C: return 0x31
        case 0x3B, 0x3A: return 0x33
        case 0x27, 0x22: return 0x34
        case 0x60, 0x7E: return 0x35
        case 0x2C, 0x3C: return 0x36
        case 0x2E, 0x3E: return 0x37
        case 0x2F, 0x3F: return 0x38
        default: return nil
        }
    }
}

public enum NativeKeyCapturePolicy {
    public static func ignoresVoiceOverChord(
        standardModifierMask: UInt32,
        voiceOverRunning: Bool
    ) -> Bool {
        guard voiceOverRunning else { return false }
        let control = USBHIDModifierWire.leftControl | USBHIDModifierWire.rightControl
        let option = USBHIDModifierWire.leftOption | USBHIDModifierWire.rightOption
        return standardModifierMask & control != 0 && standardModifierMask & option != 0
    }

    public static func shouldIgnoreEvent(
        standardModifierMask: UInt32,
        voiceOverRunning: Bool,
        pressed: Bool,
        keyWasCaptured: Bool
    ) -> Bool {
        guard ignoresVoiceOverChord(
            standardModifierMask: standardModifierMask,
            voiceOverRunning: voiceOverRunning
        ) else { return false }
        return pressed || !keyWasCaptured
    }
}

public enum NativeKeyReleaseModifierPolicy {
    public static func wireMaskForExplicitRelease(
        standardModifierMask: UInt32,
        standardByteNegotiated: Bool
    ) -> UInt32? {
        USBHIDModifierWire.encode(
            standardMask: standardModifierMask,
            standardByteNegotiated: standardByteNegotiated
        )
    }

    public static var wireMaskForCleanupRelease: UInt32 { 0 }
}

public enum NativeInputTargetError: Error, Equatable, LocalizedError {
    case selectedStreamBindingMissing(UInt64)

    public var errorDescription: String? {
        switch self {
        case .selectedStreamBindingMissing(let streamID):
            "选中的视频流 \(streamID) 没有输入路由"
        }
    }
}

public enum NativeInputTargetResolver {
    public static func target(
        selectedStreamID: UInt64?,
        bindings: [DisplayStreamBinding]
    ) throws -> VSInputTarget? {
        guard let selectedStreamID else { return nil }
        guard let binding = bindings.first(where: { $0.streamID == selectedStreamID }) else {
            throw NativeInputTargetError.selectedStreamBindingMissing(selectedStreamID)
        }
        var target = VSInputTarget()
        target.displayID = binding.displayID
        target.streamID = binding.streamID
        return target
    }
}

public struct PressedKey: Equatable, Sendable {
    public let usbHIDUsage: UInt32
    public let wireModifierMask: UInt32
}

public struct PressedKeyboardInputState: Equatable, Sendable {
    private var keysByUsage: [UInt32: PressedKey] = [:]

    public init() {}

    public var pressedKeys: [PressedKey] {
        keysByUsage.values.sorted { $0.usbHIDUsage < $1.usbHIDUsage }
    }

    public func contains(usbHIDUsage: UInt32) -> Bool {
        keysByUsage[usbHIDUsage] != nil
    }

    public mutating func enqueuePress(
        usbHIDUsage: UInt32,
        wireModifierMask: UInt32,
        perform: () -> Bool
    ) -> Bool {
        guard usbHIDUsage > 0 else { return false }
        guard keysByUsage[usbHIDUsage] == nil else { return true }
        guard perform() else { return false }
        keysByUsage[usbHIDUsage] = PressedKey(
            usbHIDUsage: usbHIDUsage,
            wireModifierMask: wireModifierMask
        )
        return true
    }

    public mutating func enqueueRelease(
        usbHIDUsage: UInt32,
        perform: (PressedKey) -> Bool
    ) -> Bool {
        guard let pressedKey = keysByUsage[usbHIDUsage] else { return true }
        guard perform(pressedKey) else { return false }
        keysByUsage.removeValue(forKey: usbHIDUsage)
        return true
    }

    public mutating func reset() {
        keysByUsage.removeAll(keepingCapacity: true)
    }
}

public struct NormalizedInputPosition: Equatable, Sendable {
    public let x: Double
    public let y: Double

    public init(x: Double, y: Double) {
        self.x = min(max(x, 0), 1)
        self.y = min(max(y, 0), 1)
    }
}

public struct ContinuousInputState: Equatable, Sendable {
    public private(set) var activePosition: NormalizedInputPosition?

    public init() {}

    public var isActive: Bool { activePosition != nil }

    public mutating func enqueueUpdate(
        position: NormalizedInputPosition,
        perform: (VSInputPhase, NormalizedInputPosition) -> Bool
    ) -> Bool {
        let phase: VSInputPhase = isActive ? .changed : .began
        guard perform(phase, position) else { return false }
        activePosition = position
        return true
    }

    public mutating func enqueueTerminal(
        position: NormalizedInputPosition? = nil,
        perform: (NormalizedInputPosition) -> Bool
    ) -> Bool {
        guard let activePosition else { return true }
        guard perform(position ?? activePosition) else { return false }
        self.activePosition = nil
        return true
    }

    public mutating func reset() {
        activePosition = nil
    }
}
