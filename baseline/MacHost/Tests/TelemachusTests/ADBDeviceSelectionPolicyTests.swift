import XCTest
@testable import Telemachus

final class ADBDeviceSelectionPolicyTests: XCTestCase {
    func testConfiguredOnlineDeviceWinsRegardlessOfEnumerationOrder() {
        for connectedSerials in [
            ["<redacted-xiaomi-adb-serial>", "<redacted-xiaomi-adb-serial>"],
            ["<redacted-xiaomi-adb-serial>", "<redacted-xiaomi-adb-serial>"]
        ] {
            XCTAssertEqual(
                ADBDeviceSelectionPolicy.resolveTargetSerial(
                    configuredSerial: "<redacted-xiaomi-adb-serial>",
                    connectedSerials: connectedSerials
                ),
                "<redacted-xiaomi-adb-serial>"
            )
        }
    }

    func testConfiguredOfflineDeviceDoesNotFallBackToAnotherDevice() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "<redacted-xiaomi-adb-serial>",
            connectedSerials: ["<redacted-xiaomi-adb-serial>"]
        ))
    }

    func testUnconfiguredHostSelectsOnlyAvailableDevice() {
        XCTAssertEqual(
            ADBDeviceSelectionPolicy.resolveTargetSerial(
                configuredSerial: "",
                connectedSerials: ["<redacted-xiaomi-adb-serial>"]
            ),
            "<redacted-xiaomi-adb-serial>"
        )
    }

    func testUnconfiguredHostRequiresSelectionWhenSeveralDevicesAreOnline() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: ["<redacted-xiaomi-adb-serial>", "<redacted-xiaomi-adb-serial>"]
        ))
    }

    func testNoConnectedDeviceProducesNoTarget() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: []
        ))
    }
}
