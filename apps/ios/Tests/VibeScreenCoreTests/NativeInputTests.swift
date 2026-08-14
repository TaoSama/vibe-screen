import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class NativeInputTests: XCTestCase {
    func testCapabilitiesFollowConcreteCapturePaths() {
        let production = NativeInputAvailability(
            keyboard: true,
            pointer: true,
            stylus: false
        )

        XCTAssertEqual(production.advertisedCapabilities, [.touch, .keyboard, .pointer])
        XCTAssertFalse(production.advertisedCapabilities.contains(.stylus))
        XCTAssertFalse(production.advertisedCapabilities.contains(.stylusExtended))
    }

    func testStylusExtendedIsNeverAdvertisedWithoutStylusCapture() {
        let unavailable = NativeInputAvailability(
            keyboard: false,
            pointer: false,
            stylus: false
        )

        XCTAssertEqual(unavailable.advertisedCapabilities, [.touch])
    }

    func testKeyboardMapperUsesUSBHIDKeyboardPage() {
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "a"), 0x04)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "Z"), 0x1D)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "1"), 0x1E)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: "0"), 0x27)
        XCTAssertEqual(USBHIDKeyboardMapper.usage(for: " "), 0x2C)
        XCTAssertNil(USBHIDKeyboardMapper.usage(for: "你"))
    }

    func testModifierMapperUsesWireBitOrder() {
        XCTAssertEqual(USBHIDModifierMapper.mask(shift: true, control: false, option: false, command: false), 1)
        XCTAssertEqual(USBHIDModifierMapper.mask(shift: false, control: true, option: false, command: false), 2)
        XCTAssertEqual(USBHIDModifierMapper.mask(shift: false, control: false, option: true, command: false), 4)
        XCTAssertEqual(USBHIDModifierMapper.mask(shift: false, control: false, option: false, command: true), 8)
        XCTAssertEqual(USBHIDModifierMapper.mask(shift: true, control: true, option: true, command: true), 15)
    }

    func testNativeInputEnvelopesCarryTargetAndSession() {
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
            pressed: true,
            modifierMask: 1,
            text: "A",
            sessionID: Data([1, 2]),
            sessionEpoch: 3,
            target: target
        )
        XCTAssertEqual(key.messageID, 11)
        XCTAssertEqual(key.keyEvent.usbHidUsage, 0x04)
        XCTAssertEqual(key.keyEvent.modifierMask, 1)
        XCTAssertEqual(key.keyEvent.target.displayID, "display-1")
    }
}
