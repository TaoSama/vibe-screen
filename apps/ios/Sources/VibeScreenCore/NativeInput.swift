import Foundation
import VibeScreenProtocol

public struct NativeInputAvailability: Equatable, Sendable {
    public var keyboard: Bool
    public var pointer: Bool
    public var stylus: Bool
    public var controller: Bool

    public init(
        keyboard: Bool,
        pointer: Bool,
        stylus: Bool,
        controller: Bool
    ) {
        self.keyboard = keyboard
        self.pointer = pointer
        self.stylus = stylus
        self.controller = controller
    }

    public var advertisedCapabilities: Set<VSCapability> {
        var capabilities: Set<VSCapability> = [.touch]
        if keyboard { capabilities.insert(.keyboard) }
        if pointer { capabilities.insert(.pointer) }
        if stylus {
            capabilities.insert(.stylus)
            capabilities.insert(.stylusExtended)
        }
        if controller { capabilities.insert(.controller) }
        return capabilities
    }
}

public enum USBHIDKeyboardMapper {
    public static func usage(for character: Character) -> UInt32? {
        let scalar = String(character).lowercased().unicodeScalars
        guard scalar.count == 1, let value = scalar.first?.value else { return nil }
        switch value {
        case 0x61...0x7A: return value - 0x61 + 0x04
        case 0x31...0x39: return value - 0x31 + 0x1E
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
