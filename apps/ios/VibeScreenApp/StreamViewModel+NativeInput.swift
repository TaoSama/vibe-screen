import CoreGraphics
import VibeScreenCore
import VibeScreenProtocol

struct InputReleaseBatch: Sendable {
    let tickets: [ControlSendTicket]
    let allAdmitted: Bool

    func waitForAdmittedReleases() async {
        for ticket in tickets {
            _ = try? await ticket.wait()
        }
    }
}

extension StreamViewModel {
    var keyboardInputAvailable: Bool {
        isStreaming && negotiatedCapabilities.contains(.keyboard)
    }

    func requestKeyboardInput() {
        guard keyboardInputAvailable else { return }
        requestKeyboardFocus()
    }

    func hasCapturedKey(usbHIDUsage: UInt32) -> Bool {
        keyboardInputState.contains(usbHIDUsage: usbHIDUsage)
    }

    @discardableResult
    func sendPointerHover(location: CGPoint?, size: CGSize) -> Bool {
        if let location {
            guard isStreaming,
                  negotiatedCapabilities.contains(.pointer),
                  size.width > 0,
                  size.height > 0,
                  selectedDecoderIsReady else { return false }
            let position = NormalizedInputPosition(
                x: location.x / size.width,
                y: location.y / size.height
            )
            var nextState = pointerHoverInputState
            let accepted = nextState.enqueueUpdate(position: position) { phase, admittedPosition in
                enqueuePointer(phase: phase, position: admittedPosition) != nil
            }
            pointerHoverInputState = nextState
            return accepted
        }

        var nextState = pointerHoverInputState
        let accepted = nextState.enqueueTerminal { position in
            enqueuePointer(phase: .ended, position: position) != nil
        }
        pointerHoverInputState = nextState
        return accepted
    }

    @discardableResult
    func sendKey(
        usbHIDUsage: UInt32,
        pressed: Bool,
        standardModifierMask: UInt32,
        text: String
    ) -> Bool {
        var nextState = keyboardInputState
        let accepted: Bool
        if pressed {
            guard isStreaming,
                  negotiatedCapabilities.contains(.keyboard),
                  selectedDecoderIsReady,
                  let wireModifierMask = USBHIDModifierWire.encode(
                      standardMask: standardModifierMask,
                      standardByteNegotiated: negotiatedCapabilities.contains(.usbHidModifierByte)
                  ) else { return false }
            accepted = nextState.enqueuePress(
                usbHIDUsage: usbHIDUsage,
                wireModifierMask: wireModifierMask
            ) {
                enqueueKey(
                    usbHIDUsage: usbHIDUsage,
                    pressed: true,
                    wireModifierMask: wireModifierMask,
                    text: text
                ) != nil
            }
        } else {
            guard let wireModifierMask = NativeKeyReleaseModifierPolicy.wireMaskForExplicitRelease(
                standardModifierMask: standardModifierMask,
                standardByteNegotiated: negotiatedCapabilities.contains(.usbHidModifierByte)
            ) else { return false }
            accepted = nextState.enqueueRelease(usbHIDUsage: usbHIDUsage) { pressedKey in
                enqueueKey(
                    usbHIDUsage: pressedKey.usbHIDUsage,
                    pressed: false,
                    wireModifierMask: wireModifierMask,
                    text: ""
                ) != nil
            }
        }
        keyboardInputState = nextState
        return accepted
    }

    @discardableResult
    func releaseActiveInput(reportErrors: Bool = true) -> InputReleaseBatch {
        var tickets: [ControlSendTicket] = []
        var allAdmitted = true

        var nextKeyboardState = keyboardInputState
        for key in keyboardInputState.pressedKeys {
            var releaseTicket: ControlSendTicket?
            let admitted = nextKeyboardState.enqueueRelease(usbHIDUsage: key.usbHIDUsage) { pressedKey in
                releaseTicket = enqueueKey(
                    usbHIDUsage: pressedKey.usbHIDUsage,
                    pressed: false,
                    wireModifierMask: NativeKeyReleaseModifierPolicy.wireMaskForCleanupRelease,
                    text: "",
                    reportErrors: reportErrors
                )
                return releaseTicket != nil
            }
            if let releaseTicket { tickets.append(releaseTicket) }
            if !admitted { allAdmitted = false }
        }
        keyboardInputState = nextKeyboardState

        var nextTouchState = touchInputState
        var touchTicket: ControlSendTicket?
        let touchAdmitted = nextTouchState.enqueueTerminal { position in
            touchTicket = enqueueTouch(
                phase: .cancelled,
                position: position,
                pressure: 0,
                reportErrors: reportErrors
            )
            return touchTicket != nil
        }
        if let touchTicket { tickets.append(touchTicket) }
        if !touchAdmitted { allAdmitted = false }
        touchInputState = nextTouchState

        var nextHoverState = pointerHoverInputState
        var hoverTicket: ControlSendTicket?
        let hoverAdmitted = nextHoverState.enqueueTerminal { position in
            hoverTicket = enqueuePointer(
                phase: .ended,
                position: position,
                reportErrors: reportErrors
            )
            return hoverTicket != nil
        }
        if let hoverTicket { tickets.append(hoverTicket) }
        if !hoverAdmitted { allAdmitted = false }
        pointerHoverInputState = nextHoverState

        return InputReleaseBatch(tickets: tickets, allAdmitted: allAdmitted)
    }

    func enqueueTouch(
        phase: VSInputPhase,
        position: NormalizedInputPosition,
        pressure: Double,
        reportErrors: Bool = true
    ) -> ControlSendTicket? {
        enqueueTargetedInput(reportErrors: reportErrors) { inputID, owner, target in
            try controlOutbox.enqueue(owner: owner) { factory in
                factory.touch(
                    inputID: inputID,
                    pointerID: 0,
                    phase: phase,
                    x: position.x,
                    y: position.y,
                    pressure: pressure,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch,
                    target: target
                )
            }
        }
    }

    private func enqueuePointer(
        phase: VSInputPhase,
        position: NormalizedInputPosition,
        reportErrors: Bool = true
    ) -> ControlSendTicket? {
        return enqueueTargetedInput(reportErrors: reportErrors) { inputID, owner, target in
            try controlOutbox.enqueue(owner: owner) { factory in
                factory.pointer(
                    inputID: inputID,
                    phase: phase,
                    x: position.x,
                    y: position.y,
                    buttonMask: 0,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch,
                    target: target
                )
            }
        }
    }

    private func enqueueKey(
        usbHIDUsage: UInt32,
        pressed: Bool,
        wireModifierMask: UInt32,
        text: String,
        reportErrors: Bool = true
    ) -> ControlSendTicket? {
        return enqueueTargetedInput(reportErrors: reportErrors) { inputID, owner, target in
            try controlOutbox.enqueue(owner: owner) { factory in
                factory.key(
                    inputID: inputID,
                    usbHIDUsage: usbHIDUsage,
                    pressed: pressed,
                    modifierMask: wireModifierMask,
                    text: text,
                    sessionID: self.state.sessionID,
                    sessionEpoch: self.state.sessionEpoch,
                    target: target
                )
            }
        }
    }

    private var selectedDecoderIsReady: Bool {
        guard let selectedStreamID else { return false }
        return decoderOwners[selectedStreamID] != nil
    }

    private func enqueueTargetedInput(
        reportErrors: Bool,
        perform: (UInt64, SessionOwner, VSInputTarget?) throws -> ControlSendTicket
    ) -> ControlSendTicket? {
        let target: VSInputTarget?
        do {
            target = try NativeInputTargetResolver.target(
                selectedStreamID: selectedStreamID,
                bindings: displayBindings
            )
        } catch {
            if reportErrors { errorMessage = error.localizedDescription }
            return nil
        }
        return enqueueNextInput(reportErrors: reportErrors) { inputID, owner in
            try perform(inputID, owner, target)
        }
    }

    private func enqueueNextInput(
        reportErrors: Bool = true,
        perform: (UInt64, SessionOwner) throws -> ControlSendTicket
    ) -> ControlSendTicket? {
        guard let owner = sessionOwner else { return nil }
        let inputID = nextInputID
        do {
            let ticket = try perform(inputID, owner)
            nextInputID += 1
            return ticket
        } catch {
            if reportErrors { errorMessage = error.localizedDescription }
            return nil
        }
    }
}
