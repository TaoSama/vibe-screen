import XCTest
@testable import Telemachus

final class ADBDeviceSelectionPolicyTests: XCTestCase {
    func testConfiguredOnlineDeviceWinsRegardlessOfEnumerationOrder() {
        for connectedSerials in [
            ["8a023e3a", "bac5b092"],
            ["bac5b092", "8a023e3a"]
        ] {
            XCTAssertEqual(
                ADBDeviceSelectionPolicy.resolveTargetSerial(
                    configuredSerial: "bac5b092",
                    connectedSerials: connectedSerials
                ),
                "bac5b092"
            )
        }
    }

    func testConfiguredOfflineDeviceDoesNotFallBackToAnotherDevice() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "bac5b092",
            connectedSerials: ["8a023e3a"]
        ))
    }

    func testUnconfiguredHostSelectsOnlyAvailableDevice() {
        XCTAssertEqual(
            ADBDeviceSelectionPolicy.resolveTargetSerial(
                configuredSerial: "",
                connectedSerials: ["bac5b092"]
            ),
            "bac5b092"
        )
    }

    func testUnconfiguredHostRequiresSelectionWhenSeveralDevicesAreOnline() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: ["8a023e3a", "bac5b092"]
        ))
    }

    func testNoConnectedDeviceProducesNoTarget() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: []
        ))
    }
}
