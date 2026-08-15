import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class USBHIDModifierWireTests: XCTestCase {
    func testCapabilityRawValueIsStable() {
        XCTAssertEqual(VSCapability.usbHidModifierByte.rawValue, 27)
    }

    func testNewClientAndNewHostUseStandardUSBHIDByte() {
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.leftControl,
            standardByteNegotiated: true
        ), 0x01)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.leftShift,
            standardByteNegotiated: true
        ), 0x02)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: 0xF0,
            standardByteNegotiated: true
        ), 0xF0)
    }

    func testNewClientAndOldHostUseLegacyLeftSideFallback() {
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.leftControl,
            standardByteNegotiated: false
        ), 0x02)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.leftShift,
            standardByteNegotiated: false
        ), 0x01)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.rightControl,
            standardByteNegotiated: false
        ), 0x02)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.rightShift,
            standardByteNegotiated: false
        ), 0x01)
        XCTAssertEqual(USBHIDModifierWire.encode(
            standardMask: USBHIDModifierWire.rightOption | USBHIDModifierWire.rightCommand,
            standardByteNegotiated: false
        ), 0x0C)
    }

    func testReservedBitsFailClosed() {
        XCTAssertNil(USBHIDModifierWire.encode(standardMask: 0x100, standardByteNegotiated: true))
        XCTAssertNil(USBHIDModifierWire.encode(standardMask: 0x100, standardByteNegotiated: false))
    }

    func testSessionNegotiationFiltersCapabilitiesWithMissingDependencies() throws {
        var filtered = SessionState()
        try filtered.beginConnection()
        try filtered.transportConnected()
        try filtered.accept(
            selectedProtocol: 1,
            sessionID: Data([1]),
            epoch: 1,
            localCapabilities: [.touch, .usbHidModifierByte, .stylusExtended],
            hostCapabilities: [.touch, .usbHidModifierByte, .stylusExtended]
        )
        XCTAssertEqual(filtered.negotiatedCapabilities, [.touch])

        var valid = SessionState()
        try valid.beginConnection()
        try valid.transportConnected()
        try valid.accept(
            selectedProtocol: 1,
            sessionID: Data([2]),
            epoch: 1,
            localCapabilities: [.touch, .keyboard, .usbHidModifierByte, .stylus, .stylusExtended],
            hostCapabilities: [.touch, .keyboard, .usbHidModifierByte, .stylus, .stylusExtended]
        )
        XCTAssertEqual(
            valid.negotiatedCapabilities,
            [.touch, .keyboard, .usbHidModifierByte, .stylus, .stylusExtended]
        )
    }
}
