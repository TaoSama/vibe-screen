import XCTest
@testable import Telemachus

final class ADBDeviceSelectionPolicyTests: XCTestCase {
    private let configuredDevice = "fixture-configured-adb-device"
    private let otherDevice = "fixture-other-adb-device"

    func testConfiguredOnlineDeviceWinsRegardlessOfEnumerationOrder() {
        for connectedSerials in [
            [otherDevice, configuredDevice],
            [configuredDevice, otherDevice]
        ] {
            XCTAssertEqual(
                ADBDeviceSelectionPolicy.resolveTargetSerial(
                    configuredSerial: configuredDevice,
                    connectedSerials: connectedSerials
                ),
                configuredDevice
            )
        }
    }

    func testConfiguredOfflineDeviceDoesNotFallBackToAnotherDevice() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: configuredDevice,
            connectedSerials: [otherDevice]
        ))
    }

    func testUnconfiguredHostSelectsOnlyAvailableDevice() {
        XCTAssertEqual(
            ADBDeviceSelectionPolicy.resolveTargetSerial(
                configuredSerial: "",
                connectedSerials: [configuredDevice]
            ),
            configuredDevice
        )
    }

    func testUnconfiguredHostRequiresSelectionWhenSeveralDevicesAreOnline() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: [configuredDevice, otherDevice]
        ))
    }

    func testNoConnectedDeviceProducesNoTarget() {
        XCTAssertNil(ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: []
        ))
    }
}
