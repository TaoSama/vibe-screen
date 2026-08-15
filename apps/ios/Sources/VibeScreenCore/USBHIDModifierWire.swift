import Foundation

public enum USBHIDModifierWire {
    public static let leftControl: UInt32 = 0x01
    public static let leftShift: UInt32 = 0x02
    public static let leftOption: UInt32 = 0x04
    public static let leftCommand: UInt32 = 0x08
    public static let rightControl: UInt32 = 0x10
    public static let rightShift: UInt32 = 0x20
    public static let rightOption: UInt32 = 0x40
    public static let rightCommand: UInt32 = 0x80
    public static let byteMask: UInt32 = 0xFF

    public static func encode(
        standardMask: UInt32,
        standardByteNegotiated: Bool
    ) -> UInt32? {
        guard standardMask & ~byteMask == 0 else { return nil }
        guard !standardByteNegotiated else { return standardMask }

        // Legacy v1 is Shift, Control, Option, Command in bits 0...3.
        var legacyMask: UInt32 = 0
        if standardMask & (leftShift | rightShift) != 0 { legacyMask |= 0x01 }
        if standardMask & (leftControl | rightControl) != 0 { legacyMask |= 0x02 }
        if standardMask & (leftOption | rightOption) != 0 { legacyMask |= 0x04 }
        if standardMask & (leftCommand | rightCommand) != 0 { legacyMask |= 0x08 }
        return legacyMask
    }
}
