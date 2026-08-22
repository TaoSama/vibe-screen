import Foundation
import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class NativeInputTests: XCTestCase {
    func testAvailabilityAdvertisesOnlyImplementedInputPaths() {
        XCTAssertEqual(
            NativeInputAvailability(keyboard: true, pointer: true).advertisedCapabilities,
            [.touch, .keyboard, .pointer, .usbHidModifierByte]
        )
    }

    func testKeyboardMapperUsesUSBHIDKeyboardPage() {
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "a"), 0x04)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "Z"), 0x1D)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "1"), 0x1E)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "0"), 0x27)
        XCTAssertNil(USBHIDKeyboardMapper.usage(for: "你"))
    }

    func testVoiceOverControlOptionChordIsIgnoredOnlyWhileVoiceOverRuns() {
        let voMask = USBHIDModifierWire.leftControl | USBHIDModifierWire.leftOption
        XCTAssertTrue(NativeKeyCapturePolicy.ignoresVoiceOverChord(
            standardModifierMask: voMask,
            voiceOverRunning: true
        ))
        XCTAssertFalse(NativeKeyCapturePolicy.ignoresVoiceOverChord(
            standardModifierMask: voMask,
            voiceOverRunning: false
        ))
        XCTAssertFalse(NativeKeyCapturePolicy.ignoresVoiceOverChord(
            standardModifierMask: USBHIDModifierWire.leftControl,
            voiceOverRunning: true
        ))
        XCTAssertTrue(NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voMask,
            voiceOverRunning: true,
            pressed: true,
            keyWasCaptured: false
        ))
        XCTAssertTrue(NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voMask,
            voiceOverRunning: true,
            pressed: false,
            keyWasCaptured: false
        ))
        XCTAssertFalse(NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voMask,
            voiceOverRunning: true,
            pressed: false,
            keyWasCaptured: true
        ))
    }

    func testPressedKeyStateChangesOnlyAfterSuccessfulEnqueueAndRetainsModifier() {
        var state = PressedKeyboardInputState()
        XCTAssertFalse(state.enqueuePress(
            usbHIDUsage: 0x04,
            wireModifierMask: USBHIDModifierWire.leftShift
        ) { false })
        XCTAssertEqual(state.pressedKeys, [])

        XCTAssertTrue(state.enqueuePress(
            usbHIDUsage: 0x04,
            wireModifierMask: USBHIDModifierWire.leftShift
        ) { true })
        XCTAssertEqual(state.pressedKeys, [PressedKey(
            usbHIDUsage: 0x04,
            wireModifierMask: USBHIDModifierWire.leftShift
        )])
        XCTAssertTrue(state.contains(usbHIDUsage: 0x04))

        XCTAssertFalse(state.enqueueRelease(usbHIDUsage: 0x04) { key in
            XCTAssertEqual(key.wireModifierMask, USBHIDModifierWire.leftShift)
            return false
        })
        XCTAssertEqual(state.pressedKeys.count, 1)

        XCTAssertTrue(state.enqueueRelease(usbHIDUsage: 0x04) { key in
            XCTAssertEqual(key.wireModifierMask, USBHIDModifierWire.leftShift)
            return true
        })
        XCTAssertEqual(state.pressedKeys, [])
        XCTAssertFalse(state.contains(usbHIDUsage: 0x04))
    }

    func testKeyReleaseModifierPolicyUsesCurrentMaskAndCleanupUsesZeroMask() {
        XCTAssertEqual(
            NativeKeyReleaseModifierPolicy.wireMaskForExplicitRelease(
                standardModifierMask: 0,
                standardByteNegotiated: true
            ),
            0
        )
        XCTAssertEqual(
            NativeKeyReleaseModifierPolicy.wireMaskForExplicitRelease(
                standardModifierMask: USBHIDModifierWire.leftShift,
                standardByteNegotiated: true
            ),
            USBHIDModifierWire.leftShift
        )
        XCTAssertNil(NativeKeyReleaseModifierPolicy.wireMaskForExplicitRelease(
            standardModifierMask: 0x100,
            standardByteNegotiated: true
        ))
        XCTAssertEqual(NativeKeyReleaseModifierPolicy.wireMaskForCleanupRelease, 0)
    }

    func testContinuousTerminalKeepsActiveStateUntilEnqueueSucceeds() {
        let position = NormalizedInputPosition(x: 0.25, y: 0.5)
        var state = ContinuousInputState()
        XCTAssertFalse(state.enqueueUpdate(position: position) { _, _ in false })
        XCTAssertFalse(state.isActive)
        XCTAssertTrue(state.enqueueUpdate(position: position) { phase, _ in phase == .began })
        XCTAssertTrue(state.isActive)
        XCTAssertFalse(state.enqueueTerminal { _ in false })
        XCTAssertTrue(state.isActive)
        XCTAssertTrue(state.enqueueTerminal { _ in true })
        XCTAssertFalse(state.isActive)
    }

    func testInputEnvelopeFactoriesCarrySessionTargetAndClampPosition() {
        var target = VSInputTarget()
        target.displayID = "display-1"
        target.streamID = 7
        var factory = EnvelopeFactory(firstMessageID: 10)

        let pointer = factory.pointer(
            inputID: 1,
            phase: .changed,
            x: 1.5,
            y: -1,
            buttonMask: 0,
            sessionID: Data([1, 2]),
            sessionEpoch: 3,
            target: target
        )
        XCTAssertEqual(pointer.messageID, 10)
        XCTAssertEqual(pointer.pointerEvent.position.x, 1)
        XCTAssertEqual(pointer.pointerEvent.position.y, 0)
        XCTAssertEqual(pointer.pointerEvent.target.streamID, 7)

        let key = factory.key(
            inputID: 2,
            usbHIDUsage: 0x04,
            pressed: false,
            modifierMask: USBHIDModifierWire.leftShift,
            text: "",
            sessionID: Data([1, 2]),
            sessionEpoch: 3,
            target: target
        )
        XCTAssertEqual(key.messageID, 11)
        XCTAssertEqual(key.keyEvent.modifierMask, USBHIDModifierWire.leftShift)
        XCTAssertEqual(key.keyEvent.target.displayID, "display-1")
    }

    func testInputTargetFailsClosedWhenSelectedStreamHasNoBinding() throws {
        XCTAssertNil(try NativeInputTargetResolver.target(selectedStreamID: nil, bindings: []))
        let target = try NativeInputTargetResolver.target(
            selectedStreamID: 7,
            bindings: [DisplayStreamBinding(displayID: "display-1", streamID: 7)]
        )
        XCTAssertEqual(target?.displayID, "display-1")
        XCTAssertEqual(target?.streamID, 7)
        XCTAssertThrowsError(try NativeInputTargetResolver.target(
            selectedStreamID: 8,
            bindings: [DisplayStreamBinding(displayID: "display-1", streamID: 7)]
        )) { error in
            XCTAssertEqual(error as? NativeInputTargetError, .selectedStreamBindingMissing(8))
        }
    }
}
