import CoreGraphics
import VibeScreenProtocol

/// Wire conventions for native pointer/keyboard input, owned end to end by the
/// host and client. Both peers encode these bits into the Protocol v1
/// PointerEvent.button_mask and KeyEvent.modifier_mask fields.
enum StreamInputWire {
    /// PointerEvent.button_mask bits.
    static let buttonPrimary: UInt32 = 1 << 0
    static let buttonSecondary: UInt32 = 1 << 1

    /// KeyEvent.modifier_mask bits.
    static let modifierShift: UInt32 = 1 << 0
    static let modifierControl: UInt32 = 1 << 1
    static let modifierOption: UInt32 = 1 << 2
    static let modifierCommand: UInt32 = 1 << 3
}

/// Pure, side-effect-free translation of client input into the values a
/// CGEvent needs. Kept separate from the CGEvent-posting layer so the mapping
/// (coordinates, button/scroll/key math, modifier flags) is unit testable
/// without a window server.
enum StreamInputMapping {
    /// Reuses the touch coordinate mapping so pointer input lands on the same
    /// display-normalized geometry as touch, rather than inventing a second path.
    static func pointerLocation(
        normalizedX: Float,
        normalizedY: Float,
        in displayBounds: CGRect
    ) -> CGPoint? {
        StreamInputMapper.point(
            normalizedX: normalizedX,
            normalizedY: normalizedY,
            in: displayBounds
        )
    }

    static func modifierFlags(fromModifierMask mask: UInt32) -> CGEventFlags {
        var flags: CGEventFlags = []
        if mask & StreamInputWire.modifierShift != 0 { flags.insert(.maskShift) }
        if mask & StreamInputWire.modifierControl != 0 { flags.insert(.maskControl) }
        if mask & StreamInputWire.modifierOption != 0 { flags.insert(.maskAlternate) }
        if mask & StreamInputWire.modifierCommand != 0 { flags.insert(.maskCommand) }
        return flags
    }

    /// Maps scroll deltas to CGEvent wheel units. macOS wheel1 is vertical and
    /// wheel2 horizontal, matching the touch scroll path.
    static func scrollWheels(deltaX: Double, deltaY: Double) -> (wheel1: Int32, wheel2: Int32) {
        (clampWheel(deltaY), clampWheel(deltaX))
    }

    private static func clampWheel(_ value: Double) -> Int32 {
        guard value.isFinite else { return 0 }
        let rounded = value.rounded()
        if rounded > Double(Int32.max) { return Int32.max }
        if rounded < Double(Int32.min) { return Int32.min }
        return Int32(rounded)
    }

    /// Translates a USB HID usage (keyboard/keypad page) into the macOS virtual
    /// key code CGEvent expects. Returns nil for usages the host does not map.
    static func macKeyCode(fromUSBHIDUsage usage: UInt32) -> CGKeyCode? {
        hidUsageToMacKeyCode[usage].map(CGKeyCode.init)
    }

    /// USB HID Keyboard/Keypad usage page (0x07) -> macOS virtual key codes.
    /// Covers letters, digits, punctuation, whitespace, arrows, and F1-F12.
    private static let hidUsageToMacKeyCode: [UInt32: Int] = [
        0x04: 0x00, 0x05: 0x0B, 0x06: 0x08, 0x07: 0x02, 0x08: 0x0E,
        0x09: 0x03, 0x0A: 0x05, 0x0B: 0x04, 0x0C: 0x22, 0x0D: 0x26,
        0x0E: 0x28, 0x0F: 0x25, 0x10: 0x2E, 0x11: 0x2D, 0x12: 0x1F,
        0x13: 0x23, 0x14: 0x0C, 0x15: 0x0F, 0x16: 0x01, 0x17: 0x11,
        0x18: 0x20, 0x19: 0x09, 0x1A: 0x0D, 0x1B: 0x07, 0x1C: 0x10,
        0x1D: 0x06,
        0x1E: 0x12, 0x1F: 0x13, 0x20: 0x14, 0x21: 0x15, 0x22: 0x17,
        0x23: 0x16, 0x24: 0x1A, 0x25: 0x1C, 0x26: 0x19, 0x27: 0x1D,
        0x28: 0x24, 0x29: 0x35, 0x2A: 0x33, 0x2B: 0x30, 0x2C: 0x31,
        0x2D: 0x1B, 0x2E: 0x18, 0x2F: 0x21, 0x30: 0x1E, 0x31: 0x2A,
        0x33: 0x29, 0x34: 0x27, 0x35: 0x32, 0x36: 0x2B, 0x37: 0x2F,
        0x38: 0x2C,
        0x3A: 0x7A, 0x3B: 0x78, 0x3C: 0x63, 0x3D: 0x76, 0x3E: 0x60,
        0x3F: 0x61, 0x40: 0x62, 0x41: 0x64, 0x42: 0x65, 0x43: 0x6D,
        0x44: 0x67, 0x45: 0x6F,
        0x4A: 0x73, 0x4D: 0x77, 0x4F: 0x7C, 0x50: 0x7B, 0x51: 0x7D,
        0x52: 0x7E,
    ]
}

/// Posts CGEvents for client-driven native pointer, scroll, and keyboard input.
/// Coordinate mapping is shared with touch via StreamInputMapping so a single
/// geometry path serves every input kind. All posting requires Accessibility;
/// callers gate on AXIsProcessTrusted() before invoking these methods.
final class StreamInputInjector {
    private let eventSource: CGEventSource?
    private var pressedButtons: UInt32 = 0
    private var lastPointerLocation: CGPoint = .zero

    init(eventSource: CGEventSource? = CGEventSource(stateID: .hidSystemState)) {
        self.eventSource = eventSource
    }

    /// Resets transient button state so a held button does not leak across
    /// sessions. Any button still pressed is released at the last known
    /// pointer location first, so a drag interrupted by a reset does not leave
    /// the WindowServer with a stuck button-down.
    func reset() {
        updateButtons(target: 0, at: lastPointerLocation)
    }

    func handlePointer(
        normalizedX: Float,
        normalizedY: Float,
        phase: VSInputPhase,
        buttonMask: UInt32,
        displayBounds: CGRect
    ) -> Bool {
        guard let location = StreamInputMapping.pointerLocation(
            normalizedX: normalizedX,
            normalizedY: normalizedY,
            in: displayBounds
        ) else { return false }
        lastPointerLocation = location

        switch phase {
        case .began:
            updateButtons(target: buttonMask, at: location)
        case .changed:
            if buttonMask != pressedButtons {
                updateButtons(target: buttonMask, at: location)
            }
            postPointerMove(to: location)
        case .ended, .cancelled:
            updateButtons(target: 0, at: location)
            postPointerMove(to: location)
        case .unspecified, .UNRECOGNIZED:
            return false
        }
        return true
    }

    func handleScroll(deltaX: Double, deltaY: Double) -> Bool {
        let wheels = StreamInputMapping.scrollWheels(deltaX: deltaX, deltaY: deltaY)
        guard wheels.wheel1 != 0 || wheels.wheel2 != 0 else { return false }
        guard let event = CGEvent(
            scrollWheelEvent2Source: eventSource,
            units: .pixel,
            wheelCount: 2,
            wheel1: wheels.wheel1,
            wheel2: wheels.wheel2,
            wheel3: 0
        ) else { return false }
        event.location = lastPointerLocation
        event.post(tap: .cghidEventTap)
        return true
    }

    func handleKey(
        usbHIDUsage: UInt32,
        pressed: Bool,
        modifierMask: UInt32
    ) -> Bool {
        guard let keyCode = StreamInputMapping.macKeyCode(fromUSBHIDUsage: usbHIDUsage) else {
            return false
        }
        guard let event = CGEvent(
            keyboardEventSource: eventSource,
            virtualKey: keyCode,
            keyDown: pressed
        ) else { return false }
        event.flags = StreamInputMapping.modifierFlags(fromModifierMask: modifierMask)
        event.post(tap: .cghidEventTap)
        return true
    }

    // MARK: - Button reconciliation

    private func updateButtons(target: UInt32, at location: CGPoint) {
        reconcileButton(
            mask: StreamInputWire.buttonPrimary,
            target: target,
            downType: .leftMouseDown,
            upType: .leftMouseUp,
            button: .left,
            at: location
        )
        reconcileButton(
            mask: StreamInputWire.buttonSecondary,
            target: target,
            downType: .rightMouseDown,
            upType: .rightMouseUp,
            button: .right,
            at: location
        )
        pressedButtons = target & (StreamInputWire.buttonPrimary | StreamInputWire.buttonSecondary)
    }

    private func reconcileButton(
        mask: UInt32,
        target: UInt32,
        downType: CGEventType,
        upType: CGEventType,
        button: CGMouseButton,
        at location: CGPoint
    ) {
        let wasDown = pressedButtons & mask != 0
        let wantsDown = target & mask != 0
        guard wasDown != wantsDown else { return }
        let type = wantsDown ? downType : upType
        if let event = CGEvent(
            mouseEventSource: eventSource,
            mouseType: type,
            mouseCursorPosition: location,
            mouseButton: button
        ) {
            event.setIntegerValueField(.mouseEventClickState, value: 1)
            event.post(tap: .cghidEventTap)
        }
    }

    private func postPointerMove(to location: CGPoint) {
        let leftDown = pressedButtons & StreamInputWire.buttonPrimary != 0
        let rightDown = pressedButtons & StreamInputWire.buttonSecondary != 0
        let type: CGEventType
        let button: CGMouseButton
        if leftDown {
            type = .leftMouseDragged
            button = .left
        } else if rightDown {
            type = .rightMouseDragged
            button = .right
        } else {
            type = .mouseMoved
            button = .left
        }
        if let event = CGEvent(
            mouseEventSource: eventSource,
            mouseType: type,
            mouseCursorPosition: location,
            mouseButton: button
        ) {
            event.post(tap: .cghidEventTap)
        }
    }
}
