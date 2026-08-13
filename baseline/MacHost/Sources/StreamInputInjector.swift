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

/// Creates touch-derived pointer events from the system state while isolating
/// pinch's synthetic Command modifier on a private source.
final class TouchGestureEventFactory {
    private let pointerSource: CGEventSource?
    private let zoomSource: CGEventSource?

    init(
        pointerSource: CGEventSource? = CGEventSource(stateID: .hidSystemState),
        zoomSource: CGEventSource? = CGEventSource(stateID: .privateState)
    ) {
        self.pointerSource = pointerSource
        self.zoomSource = zoomSource
    }

    func mouseEvent(
        type: CGEventType,
        position: CGPoint,
        button: CGMouseButton,
        clickState: Int64? = nil
    ) -> CGEvent? {
        let event = CGEvent(
            mouseEventSource: pointerSource,
            mouseType: type,
            mouseCursorPosition: position,
            mouseButton: button
        )
        if let clickState {
            event?.setIntegerValueField(.mouseEventClickState, value: clickState)
        }
        return event
    }

    func scrollEvent(
        deltaX: Int32,
        deltaY: Int32,
        position: CGPoint,
        commandModified: Bool = false
    ) -> CGEvent? {
        let event = CGEvent(
            scrollWheelEvent2Source: commandModified ? zoomSource : pointerSource,
            units: .pixel,
            wheelCount: commandModified ? 1 : 2,
            wheel1: deltaY,
            wheel2: deltaX,
            wheel3: 0
        )
        event?.location = position
        if commandModified {
            event?.flags = .maskCommand
        }
        return event
    }
}

/// Builds the CoreGraphics event for one pen-tip sample without posting it.
/// Keeping construction side-effect free lets protocol and field mapping be
/// verified without Accessibility permission or a live WindowServer target.
struct StylusEventFactory {
    static let maximumTiltDegrees = 90.0
    private static let tabletPointMouseSubtype: Int64 = 1

    private let eventSource: CGEventSource?

    init(eventSource: CGEventSource? = CGEventSource(stateID: .hidSystemState)) {
        self.eventSource = eventSource
    }

    func event(
        normalizedX: Float,
        normalizedY: Float,
        phase: VSInputPhase,
        pressure: Double,
        tiltXDegrees: Double,
        tiltYDegrees: Double,
        displayBounds: CGRect
    ) -> CGEvent? {
        guard pressure.isFinite, (0...1).contains(pressure),
              tiltXDegrees.isFinite, tiltYDegrees.isFinite,
              hypot(tiltXDegrees, tiltYDegrees) <= Self.maximumTiltDegrees,
              let location = StreamInputMapping.pointerLocation(
                  normalizedX: normalizedX,
                  normalizedY: normalizedY,
                  in: displayBounds
              ) else { return nil }

        let eventType: CGEventType
        switch phase {
        case .began: eventType = .leftMouseDown
        case .changed: eventType = .leftMouseDragged
        case .ended, .cancelled:
            guard pressure == 0 else { return nil }
            eventType = .leftMouseUp
        case .unspecified, .UNRECOGNIZED: return nil
        }
        guard let event = CGEvent(
            mouseEventSource: eventSource,
            mouseType: eventType,
            mouseCursorPosition: location,
            mouseButton: .left
        ) else { return nil }
        event.setIntegerValueField(
            .mouseEventSubtype,
            value: Self.tabletPointMouseSubtype
        )
        event.setDoubleValueField(.tabletEventPointPressure, value: pressure)
        event.setDoubleValueField(
            .tabletEventTiltX,
            value: min(max(tiltXDegrees / Self.maximumTiltDegrees, -1), 1)
        )
        event.setDoubleValueField(
            .tabletEventTiltY,
            value: min(max(tiltYDegrees / Self.maximumTiltDegrees, -1), 1)
        )
        return event
    }
}

/// Serializes the first supported pen slice: exactly one active pen tip.
/// A stale pointer can neither continue nor release another pointer's stroke.
struct StylusTipState {
    private(set) var activePointerID: UInt32?

    mutating func accepts(pointerID: UInt32, phase: VSInputPhase) -> Bool {
        switch phase {
        case .began:
            guard activePointerID == nil else { return false }
            activePointerID = pointerID
            return true
        case .changed:
            return activePointerID == pointerID
        case .ended, .cancelled:
            guard activePointerID == pointerID else { return false }
            activePointerID = nil
            return true
        case .unspecified, .UNRECOGNIZED:
            return false
        }
    }

    mutating func consumeResetPointerID() -> UInt32? {
        defer { activePointerID = nil }
        return activePointerID
    }
}

/// Main-thread ownership of the synthetic primary mouse button shared by the
/// legacy touch-drag path and Protocol v1 stylus path.
struct PrimaryButtonOwnerState {
    enum Owner: Equatable {
        case touchDrag
        case stylus(pointerID: UInt32)
    }

    private(set) var owner: Owner?

    mutating func beginTouchDrag() -> Bool {
        guard owner == nil else { return false }
        owner = .touchDrag
        return true
    }

    mutating func endTouchDrag() -> Bool {
        guard owner == .touchDrag else { return false }
        owner = nil
        return true
    }

    func canHandleStylus(pointerID: UInt32, phase: VSInputPhase) -> Bool {
        switch phase {
        case .began: return owner == nil
        case .changed, .ended, .cancelled: return owner == .stylus(pointerID: pointerID)
        case .unspecified, .UNRECOGNIZED: return false
        }
    }

    mutating func didHandleStylus(pointerID: UInt32, phase: VSInputPhase) {
        switch phase {
        case .began: owner = .stylus(pointerID: pointerID)
        case .ended, .cancelled: owner = nil
        case .changed, .unspecified, .UNRECOGNIZED: break
        }
    }

    mutating func reset() -> Owner? {
        defer { owner = nil }
        return owner
    }
}

/// Tracks only key events accepted for posting. Reset consumes a stable
/// HID-usage ordering so teardown produces deterministic release events.
struct PressedKeyState {
    struct Key: Equatable {
        let usbHIDUsage: UInt32
        let modifierMask: UInt32
    }

    private var modifierMaskByUsage: [UInt32: UInt32] = [:]

    mutating func didPost(
        usbHIDUsage: UInt32,
        pressed: Bool,
        modifierMask: UInt32
    ) {
        if pressed {
            modifierMaskByUsage[usbHIDUsage] = modifierMask
        } else {
            modifierMaskByUsage.removeValue(forKey: usbHIDUsage)
        }
    }

    mutating func consumeResetKeys() -> [Key] {
        defer { modifierMaskByUsage.removeAll(keepingCapacity: true) }
        return modifierMaskByUsage.keys.sorted().compactMap { usage in
            modifierMaskByUsage[usage].map {
                Key(usbHIDUsage: usage, modifierMask: $0)
            }
        }
    }
}

/// Posts CGEvents for client-driven native pointer, stylus, scroll, and keyboard input.
/// Coordinate mapping is shared with touch via StreamInputMapping so a single
/// geometry path serves every input kind. All posting requires Accessibility;
/// callers gate on AXIsProcessTrusted() before invoking these methods.
final class StreamInputInjector {
    private let eventSource: CGEventSource?
    private let stylusEventFactory: StylusEventFactory
    private let stylusEventPoster: (CGEvent) -> Void
    private let keyboardEventPoster: (CGEvent) -> Void
    private var pressedButtons: UInt32 = 0
    private var pressedKeyState = PressedKeyState()
    private var lastPointerLocation: CGPoint = .zero
    private var lastStylusLocation: CGPoint = .zero
    private var stylusTipState = StylusTipState()

    init(
        eventSource: CGEventSource? = CGEventSource(stateID: .hidSystemState),
        stylusEventPoster: @escaping (CGEvent) -> Void = {
            $0.post(tap: .cghidEventTap)
        },
        keyboardEventPoster: @escaping (CGEvent) -> Void = {
            $0.post(tap: .cghidEventTap)
        }
    ) {
        self.eventSource = eventSource
        stylusEventFactory = StylusEventFactory(eventSource: eventSource)
        self.stylusEventPoster = stylusEventPoster
        self.keyboardEventPoster = keyboardEventPoster
    }

    /// Releases held pointer, keyboard, and stylus state before clearing it so
    /// interrupted input cannot leak across sessions.
    func reset() {
        updateButtons(target: 0, at: lastPointerLocation)
        releasePressedKeys()
        guard stylusTipState.consumeResetPointerID() != nil,
              let release = stylusEventFactory.event(
                  normalizedX: 0,
                  normalizedY: 0,
                  phase: .cancelled,
                  pressure: 0,
                  tiltXDegrees: 0,
                  tiltYDegrees: 0,
                  displayBounds: CGRect(origin: lastStylusLocation, size: CGSize(width: 1, height: 1))
              ) else { return }
        release.location = lastStylusLocation
        postStylusEvent(release)
    }

    func handlePointer(
        normalizedX: Float,
        normalizedY: Float,
        phase: VSInputPhase,
        buttonMask: UInt32,
        displayBounds: CGRect
    ) -> Bool {
        let wantsPrimary = buttonMask & StreamInputWire.buttonPrimary != 0
        guard !(wantsPrimary && stylusTipState.activePointerID != nil),
              let location = StreamInputMapping.pointerLocation(
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
        keyboardEventPoster(event)
        pressedKeyState.didPost(
            usbHIDUsage: usbHIDUsage,
            pressed: pressed,
            modifierMask: modifierMask
        )
        return true
    }

    func handleStylus(
        pointerID: UInt32,
        normalizedX: Float,
        normalizedY: Float,
        phase: VSInputPhase,
        pressure: Double,
        tiltXDegrees: Double,
        tiltYDegrees: Double,
        displayBounds: CGRect
    ) -> Bool {
        guard pressedButtons & StreamInputWire.buttonPrimary == 0,
              let event = stylusEventFactory.event(
            normalizedX: normalizedX,
            normalizedY: normalizedY,
            phase: phase,
            pressure: pressure,
            tiltXDegrees: tiltXDegrees,
            tiltYDegrees: tiltYDegrees,
            displayBounds: displayBounds
        ), stylusTipState.accepts(pointerID: pointerID, phase: phase) else { return false }
        lastStylusLocation = event.location
        postStylusEvent(event)
        return true
    }

    private func postStylusEvent(_ event: CGEvent) {
        stylusEventPoster(event)
    }

    private func releasePressedKeys() {
        for key in pressedKeyState.consumeResetKeys() {
            guard let keyCode = StreamInputMapping.macKeyCode(
                fromUSBHIDUsage: key.usbHIDUsage
            ), let event = CGEvent(
                keyboardEventSource: eventSource,
                virtualKey: keyCode,
                keyDown: false
            ) else { continue }
            event.flags = StreamInputMapping.modifierFlags(
                fromModifierMask: key.modifierMask
            )
            keyboardEventPoster(event)
        }
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
