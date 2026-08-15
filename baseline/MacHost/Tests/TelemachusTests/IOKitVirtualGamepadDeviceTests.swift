import Foundation
import XCTest
import IOKit
@testable import Telemachus

final class IOKitVirtualGamepadDeviceTests: XCTestCase {
    func testProviderReturningNilThrowsDeviceCreationFailed() {
        let provider = FakeVirtualGamepadIOProvider()
        provider.shouldFailCreation = true
        XCTAssertThrowsError(try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )) { error in
            XCTAssertEqual(error as? GameControllerInputError, .deviceCreationFailed)
        }
    }

    func testCloseSubmitsNeutralReportAndCancels() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        let handle = try XCTUnwrap(provider.createdHandle)

        try device.close()

        XCTAssertEqual(handle.submittedReports.count, 1)
        XCTAssertEqual(handle.submittedReports[0], try GameControllerHIDReport.encode(.neutral))
        XCTAssertEqual(handle.cancelCount, 1)
    }

    func testCloseIsIdempotentCancelCalledOnce() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        let handle = try XCTUnwrap(provider.createdHandle)

        try device.close()
        try device.close()
        try device.close()

        XCTAssertEqual(handle.cancelCount, 1)
        XCTAssertEqual(handle.submittedReports.count, 1)
    }

    func testSubmitAfterCloseThrowsInvalidTransition() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        try device.close()

        XCTAssertThrowsError(try device.submit(.neutral)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .invalidTransition)
        }
    }

    func testCloseStillCancelsWhenNeutralReportSubmitFails() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        let handle = try XCTUnwrap(provider.createdHandle)
        handle.submitResult = kIOReturnBadArgument

        XCTAssertThrowsError(try device.close()) { error in
            XCTAssertEqual(error as? GameControllerInputError, .reportFailed(kIOReturnBadArgument))
        }
        XCTAssertEqual(handle.cancelCount, 1)
    }

    func testSubmitForwardsEncodedReportToHandle() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        let handle = try XCTUnwrap(provider.createdHandle)

        let state = GameControllerState(
            buttonMask: 1, leftX: 0, leftY: 0, rightX: 0, rightY: 0,
            leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
        )
        try device.submit(state)

        XCTAssertEqual(handle.submittedReports.count, 1)
        let expectedReport = try GameControllerHIDReport.encode(state)
        XCTAssertEqual(handle.submittedReports[0], expectedReport)
    }

    func testSubmitFailureThrowsReportFailed() throws {
        let provider = FakeVirtualGamepadIOProvider()
        let device = try IOKitVirtualGamepadDevice(
            controllerID: "c1",
            controllerEpoch: 1,
            provider: provider
        )
        let handle = try XCTUnwrap(provider.createdHandle)
        handle.submitResult = kIOReturnBadArgument

        XCTAssertThrowsError(try device.submit(.neutral)) { error in
            XCTAssertEqual(error as? GameControllerInputError, .reportFailed(kIOReturnBadArgument))
        }
    }

    func testSerialNumberIsStableForSameIDEpochAndDiffersForDifferentEpoch() throws {
        let provider1 = FakeVirtualGamepadIOProvider()
        _ = try IOKitVirtualGamepadDevice(controllerID: "c1", controllerEpoch: 42, provider: provider1)
        let serial1 = provider1.lastProperties?[kIOHIDSerialNumberKey] as? String

        let provider2 = FakeVirtualGamepadIOProvider()
        _ = try IOKitVirtualGamepadDevice(controllerID: "c1", controllerEpoch: 42, provider: provider2)
        let serial2 = provider2.lastProperties?[kIOHIDSerialNumberKey] as? String

        XCTAssertEqual(serial1, serial2)
        XCTAssertEqual(serial1?.count, 32)

        let provider3 = FakeVirtualGamepadIOProvider()
        _ = try IOKitVirtualGamepadDevice(controllerID: "c1", controllerEpoch: 43, provider: provider3)
        let serial3 = provider3.lastProperties?[kIOHIDSerialNumberKey] as? String

        XCTAssertNotEqual(serial1, serial3)
    }
}
