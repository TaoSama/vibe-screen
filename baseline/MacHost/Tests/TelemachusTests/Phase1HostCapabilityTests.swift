import CoreGraphics
import XCTest
@testable import Telemachus

final class Phase1HostCapabilityTests: XCTestCase {
    func testInputMappingSupportsNegativeDisplayOrigins() {
        let point = StreamInputMapper.point(
            normalizedX: 0.25,
            normalizedY: 0.75,
            in: CGRect(x: -1920, y: -100, width: 1920, height: 1080)
        )
        XCTAssertEqual(point, CGPoint(x: -1440, y: 710))
    }

    func testInputMappingRejectsMalformedCoordinates() {
        let bounds = CGRect(x: 0, y: 0, width: 100, height: 100)
        XCTAssertNil(StreamInputMapper.point(normalizedX: .nan, normalizedY: 0.5, in: bounds))
        XCTAssertNil(StreamInputMapper.point(normalizedX: .infinity, normalizedY: 0.5, in: bounds))
        XCTAssertNil(StreamInputMapper.point(normalizedX: -0.01, normalizedY: 0.5, in: bounds))
        XCTAssertNil(StreamInputMapper.point(normalizedX: 0.5, normalizedY: 1.01, in: bounds))
    }

    func testWindowOnOfflineDisplayRecoversToMainDisplay() {
        let main = CGRect(x: 0, y: 0, width: 1920, height: 1080)
        let result = WindowPlacement.recoveryFrame(
            CGRect(x: -1100, y: 100, width: 600, height: 400),
            originalDisplayBounds: CGRect(x: -1200, y: 0, width: 1200, height: 800),
            originalDisplayUUID: "offline",
            onlineDisplays: [DisplayRecoveryTarget(
                persistentUUID: "main",
                bounds: main
            )],
            mainDisplayBounds: main
        )
        XCTAssertTrue(main.contains(result))
    }

    func testWindowReturnsToOriginalFrameWhileDisplayIsOnline() {
        let originalDisplay = CGRect(x: -1200, y: 0, width: 1200, height: 800)
        let originalFrame = CGRect(x: -1100, y: 100, width: 600, height: 400)
        XCTAssertEqual(
            WindowPlacement.recoveryFrame(
                originalFrame,
                originalDisplayBounds: originalDisplay,
                originalDisplayUUID: "original",
                onlineDisplays: [
                    DisplayRecoveryTarget(
                        persistentUUID: "original",
                        bounds: originalDisplay
                    ),
                    DisplayRecoveryTarget(
                        persistentUUID: "main",
                        bounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
                    )
                ],
                mainDisplayBounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
            ),
            originalFrame
        )
    }

    func testWindowUsesUUIDInsteadOfReusedCoordinateSpace() {
        let oldBounds = CGRect(x: -1200, y: 0, width: 1200, height: 800)
        let originalFrame = CGRect(x: -1100, y: 100, width: 600, height: 400)
        let main = CGRect(x: 0, y: 0, width: 1920, height: 1080)
        let recovered = WindowPlacement.recoveryFrame(
            originalFrame,
            originalDisplayBounds: oldBounds,
            originalDisplayUUID: "offline-original",
            onlineDisplays: [
                DisplayRecoveryTarget(
                    persistentUUID: "replacement",
                    bounds: oldBounds
                ),
                DisplayRecoveryTarget(persistentUUID: "main", bounds: main)
            ],
            mainDisplayBounds: main
        )
        XCTAssertTrue(main.contains(recovered))
    }

    func testWindowMapsIntoChangedBoundsForSameDisplayUUID() {
        let originalBounds = CGRect(x: -1200, y: 0, width: 1200, height: 800)
        let currentBounds = CGRect(x: 1920, y: 0, width: 1600, height: 1000)
        let recovered = WindowPlacement.recoveryFrame(
            CGRect(x: -1100, y: 100, width: 600, height: 400),
            originalDisplayBounds: originalBounds,
            originalDisplayUUID: "same-display",
            onlineDisplays: [DisplayRecoveryTarget(
                persistentUUID: "same-display",
                bounds: currentBounds
            )],
            mainDisplayBounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
        )
        XCTAssertTrue(currentBounds.contains(recovered))
    }

    func testInteractiveSessionIsNotEligibleForUnattendedRecovery() {
        XCTAssertFalse(HostStartupPolicy.shouldRecover(
            autoStartEnabled: true,
            hasScreenRecordingPermission: true,
            hasCompletedOnboarding: true,
            explicitHeadlessBenchmark: false,
            isUnattendedOperation: false
        ))
    }

    func testAutomaticStartupRequiresOnboardingOutsideBenchmark() {
        XCTAssertFalse(HostStartupPolicy.shouldAutoStart(
            autoStartEnabled: true,
            hasScreenRecordingPermission: true,
            hasCompletedOnboarding: false,
            explicitHeadlessBenchmark: false
        ))
        XCTAssertTrue(HostStartupPolicy.shouldAutoStart(
            autoStartEnabled: true,
            hasScreenRecordingPermission: true,
            hasCompletedOnboarding: false,
            explicitHeadlessBenchmark: true
        ))
    }

    func testWirelessModeDoesNotProbeUSB() {
        XCTAssertFalse(HostStartupPolicy.shouldProbeUSB(connectionMode: .wireless))
        XCTAssertTrue(HostStartupPolicy.shouldProbeUSB(connectionMode: .usb))
    }

    func testVirtualDisplayIdentityIncludesDensityAndRefreshRate() {
        let hiDPI = identity(logicalWidth: 2000, refreshRate: 60, hiDPI: true)
        let native = VirtualDisplayIdentity.productID(
            logicalWidth: 4000,
            logicalHeight: 2400,
            physicalWidth: 4000,
            physicalHeight: 2400,
            refreshRate: 60,
            hiDPI: false
        )
        let highRefresh = identity(logicalWidth: 2000, refreshRate: 120, hiDPI: true)
        XCTAssertNotEqual(hiDPI, native)
        XCTAssertNotEqual(hiDPI, highRefresh)
    }

    func testDisplayUUIDWinsAndMissingUUIDFallsBackToMain() {
        let displays = [
            descriptor(id: 10, uuid: "main", isMain: true),
            descriptor(id: 11, uuid: "secondary", isMain: false)
        ]
        XCTAssertEqual(DisplayCatalog.resolve(
            persistentUUID: "secondary",
            fallbackID: 10,
            onlineDisplays: displays,
            mainDisplayID: 10
        ), 11)
        XCTAssertEqual(DisplayCatalog.resolve(
            persistentUUID: "missing",
            fallbackID: 11,
            onlineDisplays: displays,
            mainDisplayID: 10
        ), 10)
    }

    private func descriptor(
        id: CGDirectDisplayID,
        uuid: String,
        isMain: Bool
    ) -> HostDisplayDescriptor {
        HostDisplayDescriptor(
            id: id,
            persistentUUID: uuid,
            name: uuid,
            width: 100,
            height: 100,
            isMain: isMain
        )
    }

    private func identity(
        logicalWidth: Int,
        refreshRate: Int,
        hiDPI: Bool
    ) -> UInt32 {
        VirtualDisplayIdentity.productID(
            logicalWidth: logicalWidth,
            logicalHeight: 1200,
            physicalWidth: logicalWidth * (hiDPI ? 2 : 1),
            physicalHeight: 1200 * (hiDPI ? 2 : 1),
            refreshRate: refreshRate,
            hiDPI: hiDPI
        )
    }
}
