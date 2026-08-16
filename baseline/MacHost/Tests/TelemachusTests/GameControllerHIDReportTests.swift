import Foundation
import XCTest
@testable import Telemachus

final class GameControllerHIDReportTests: XCTestCase {
    func testByteCountIs16() {
        XCTAssertEqual(GameControllerHIDReport.byteCount, 16)
    }

    func testDescriptorDeclaresTheEncodedReportByteCount() throws {
        let descriptor = [UInt8](GameControllerHIDReport.descriptor)
        var reportSize = 0
        var reportCount = 0
        var inputBits = 0
        var index = 0

        while index < descriptor.count {
            let prefix = descriptor[index]
            index += 1
            guard prefix != 0xFE else { return XCTFail("Long HID items are not expected") }
            let payloadLength = [0, 1, 2, 4][Int(prefix & 0x03)]
            let type = (prefix >> 2) & 0x03
            let tag = prefix >> 4
            guard index + payloadLength <= descriptor.count else {
                return XCTFail("Truncated HID descriptor item")
            }
            let value = descriptor[index..<(index + payloadLength)]
                .enumerated()
                .reduce(0) { $0 | (Int($1.element) << ($1.offset * 8)) }
            if type == 1 && tag == 7 { reportSize = value }
            if type == 1 && tag == 9 { reportCount = value }
            if type == 0 && tag == 8 { inputBits += reportSize * reportCount }
            index += payloadLength
        }

        XCTAssertEqual(inputBits, GameControllerHIDReport.byteCount * 8)
    }

    func testNeutralStateEncodesNullHatReport() throws {
        let report = try GameControllerHIDReport.encode(.neutral)
        XCTAssertEqual(report.count, 16)
        var expected = Data(repeating: 0, count: 16)
        expected[8] = 8
        XCTAssertEqual(report, expected)
    }

    func testButtonMaskEncodesLittleEndian13Bits() throws {
        let state = GameControllerState(
            buttonMask: (1 << 0) | (1 << 8),
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        let report = try GameControllerHIDReport.encode(state)
        XCTAssertEqual(report[0], 0x01)
        XCTAssertEqual(report[1], 0x01)
    }

    func testAll13ButtonsFitInTwoBytes() throws {
        let state = GameControllerState(
            buttonMask: GameControllerState.supportedButtonMask,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        let report = try GameControllerHIDReport.encode(state)
        XCTAssertEqual(report[0], 0xFF)
        XCTAssertEqual(report[1], 0x1F)
    }

    func testSignedAxesEncodeAsInt8() throws {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: 1.0, leftY: -1.0, rightX: 0.5, rightY: -0.5,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        let report = try GameControllerHIDReport.encode(state)
        XCTAssertEqual(Int8(bitPattern: report[2]), 127)
        XCTAssertEqual(Int8(bitPattern: report[3]), -127)
        XCTAssertEqual(Int8(bitPattern: report[4]), 64)
        XCTAssertEqual(Int8(bitPattern: report[5]), -64)
    }

    func testUnsignedTriggersEncodeAsUInt8() throws {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 1.0, rightTrigger: 0.5,
            hatX: 0, hatY: 0
        )
        let report = try GameControllerHIDReport.encode(state)
        XCTAssertEqual(report[6], 255)
        XCTAssertEqual(report[7], 128)
    }

    func testHatSwitchEncodesAllEightDirectionsAndNull() throws {
        let directions: [(Int32, Int32, UInt8)] = [
            (0, -1, 0), (1, -1, 1), (1, 0, 2), (1, 1, 3),
            (0, 1, 4), (-1, 1, 5), (-1, 0, 6), (-1, -1, 7),
            (0, 0, 8)
        ]
        for (hatX, hatY, expected) in directions {
            let state = GameControllerState(
                buttonMask: 0,
                leftX: 0, leftY: 0, rightX: 0, rightY: 0,
                leftTrigger: 0, rightTrigger: 0,
                hatX: hatX, hatY: hatY
            )
            let report = try GameControllerHIDReport.encode(state)
            XCTAssertEqual(report[8] & 0x0F, expected, "hatX=\(hatX), hatY=\(hatY)")
            XCTAssertEqual(report[8] & 0xF0, 0)
        }
    }

    func testTrailingSevenBytesAreZeroPadding() throws {
        let state = GameControllerState(
            buttonMask: GameControllerState.supportedButtonMask,
            leftX: 1, leftY: 1, rightX: 1, rightY: 1,
            leftTrigger: 1, rightTrigger: 1,
            hatX: 1, hatY: 1
        )
        let report = try GameControllerHIDReport.encode(state)
        for i in 9..<16 {
            XCTAssertEqual(report[i], 0, "byte \(i) should be padding")
        }
    }

    func testInvalidButtonMaskThrowsInvalidState() {
        let state = GameControllerState(
            buttonMask: 1 << 13,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try GameControllerHIDReport.encode(state)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }

    func testAxisOutOfRangeThrowsInvalidState() {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: 1.5, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try GameControllerHIDReport.encode(state)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }

    func testNonFiniteAxisThrowsInvalidState() {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: .nan, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try GameControllerHIDReport.encode(state)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }

    func testTriggerOutOfRangeThrowsInvalidState() {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: -0.1, rightTrigger: 0,
            hatX: 0, hatY: 0
        )
        XCTAssertThrowsError(try GameControllerHIDReport.encode(state)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }

    func testHatOutOfRangeThrowsInvalidState() {
        let state = GameControllerState(
            buttonMask: 0,
            leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0,
            hatX: 2, hatY: 0
        )
        XCTAssertThrowsError(try GameControllerHIDReport.encode(state)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidState)
        }
    }
}
