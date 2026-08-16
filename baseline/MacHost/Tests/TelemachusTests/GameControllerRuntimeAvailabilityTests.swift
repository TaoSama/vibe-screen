import Foundation
import XCTest
import IOKit
@testable import Telemachus

final class GameControllerRuntimeAvailabilityTests: XCTestCase {
    func testUnsignedBuildReturnsNilFactoryWithAdHocReason() {
        let factory = FakeVirtualGamepadFactory()
        let availability = GameControllerRuntimeAvailability.probe(
            identitySigned: false,
            entitlementPresent: true,
            factory: factory
        )
        XCTAssertNil(availability.factory)
        XCTAssertNotNil(availability.unavailableReason)
        XCTAssertTrue(availability.unavailableReason?.contains("ad-hoc") == true)
    }

    func testMissingEntitlementReturnsNilFactoryWithEntitlementReason() {
        let factory = FakeVirtualGamepadFactory()
        let availability = GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: false,
            factory: factory
        )
        XCTAssertNil(availability.factory)
        XCTAssertNotNil(availability.unavailableReason)
        XCTAssertTrue(availability.unavailableReason?.contains("entitlement") == true)
    }

    func testRuntimeProbeMakeDeviceFailureReturnsNilFactory() {
        let factory = FakeVirtualGamepadFactory()
        factory.makeError = GameControllerInputError.deviceCreationFailed
        let availability = GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: true,
            factory: factory
        )
        XCTAssertNil(availability.factory)
        XCTAssertNotNil(availability.unavailableReason)
        XCTAssertTrue(availability.unavailableReason?.contains("runtime probe") == true)
    }

    func testRuntimeProbeCloseFailureReturnsNilFactory() {
        let factory = FakeVirtualGamepadFactory()
        factory.closeError = GameControllerInputError.reportFailed(kIOReturnBadArgument)
        let availability = GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: true,
            factory: factory
        )
        XCTAssertNil(availability.factory)
        XCTAssertNotNil(availability.unavailableReason)
        XCTAssertTrue(availability.unavailableReason?.contains("runtime probe") == true)
    }

    func testSignedEntitledAndProbeSuccessReturnsFactory() {
        let factory = FakeVirtualGamepadFactory()
        let availability = GameControllerRuntimeAvailability.probe(
            identitySigned: true,
            entitlementPresent: true,
            factory: factory
        )
        XCTAssertNotNil(availability.factory)
        XCTAssertNil(availability.unavailableReason)
    }
}
