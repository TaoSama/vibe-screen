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

    func testUnchangedDisplayBoundsPreservePartiallyOffscreenFrame() {
        let bounds = CGRect(x: -1200, y: 0, width: 1200, height: 800)
        let frame = CGRect(x: -1300, y: 100, width: 700, height: 400)
        XCTAssertEqual(WindowPlacement.recoveryFrame(
            frame,
            originalDisplayBounds: bounds,
            originalDisplayUUID: "same",
            onlineDisplays: [DisplayRecoveryTarget(
                persistentUUID: "same",
                bounds: bounds
            )],
            mainDisplayBounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
        ), frame)
    }

    func testUnchangedDisplayBoundsPreserveOversizedFrame() {
        let bounds = CGRect(x: 0, y: 0, width: 1200, height: 800)
        let frame = CGRect(x: -100, y: -50, width: 1800, height: 1200)
        XCTAssertEqual(WindowPlacement.recoveryFrame(
            frame,
            originalDisplayBounds: bounds,
            originalDisplayUUID: "same",
            onlineDisplays: [DisplayRecoveryTarget(
                persistentUUID: "same",
                bounds: bounds
            )],
            mainDisplayBounds: bounds
        ), frame)
    }

    @MainActor
    func testConcurrentDoubleStartAdmitsExactlyOneRequest() async {
        let lifecycle = HostServerLifecycle()
        let first = Task { @MainActor in lifecycle.beginStart() }
        let second = Task { @MainActor in lifecycle.beginStart() }
        let tokens = await [first.value, second.value]
        XCTAssertEqual(tokens.compactMap { $0 }.count, 1)
        XCTAssertFalse(lifecycle.canStart)
    }

    @MainActor
    func testStopInvalidatesSuspendedStart() {
        let lifecycle = HostServerLifecycle()
        let startToken = lifecycle.beginStart()!
        let stopToken = lifecycle.beginStop()
        XCTAssertFalse(lifecycle.isCurrentStart(startToken))
        XCTAssertFalse(lifecycle.finishStart(startToken))
        lifecycle.finishStop(stopToken)
        XCTAssertTrue(lifecycle.canStart)
    }

    @MainActor
    func testStaleFailureTokenCannotOwnReplacementSession() {
        let lifecycle = HostServerLifecycle()
        let first = lifecycle.beginStart()!
        XCTAssertTrue(lifecycle.finishStart(first))
        let stop = lifecycle.beginStop()
        lifecycle.finishStop(stop)
        let replacement = lifecycle.beginStart()!
        XCTAssertFalse(lifecycle.ownsSession(first))
        XCTAssertTrue(lifecycle.ownsSession(replacement))
    }

    func testFallbackRemovalReportsTerminalOnlyForCurrentGeneration() {
        let lifecycle = FallbackCaptureLifecycle()
        guard case .started(let generation) = lifecycle.begin() else {
            return XCTFail("fallback did not start")
        }
        XCTAssertEqual(lifecycle.disposition(
            status: .stopped,
            generation: generation,
            hasSurface: false
        ), .terminalFailure)
        XCTAssertTrue(lifecycle.isActive)
        XCTAssertEqual(lifecycle.begin(), .alreadyActive)
        XCTAssertEqual(lifecycle.disposition(
            status: .stopped,
            generation: generation,
            hasSurface: false
        ), .ignore)
        XCTAssertTrue(lifecycle.claimTerminal(generation: generation))
        XCTAssertFalse(lifecycle.isActive)
        XCTAssertFalse(lifecycle.claimTerminal(generation: generation))
    }

    func testStaleFallbackStopDoesNotTerminateReplacement() {
        let lifecycle = FallbackCaptureLifecycle()
        guard case .started(let first) = lifecycle.begin() else {
            return XCTFail("first fallback did not start")
        }
        lifecycle.invalidate()
        guard case .started(let second) = lifecycle.begin() else {
            return XCTFail("second fallback did not start")
        }
        XCTAssertEqual(lifecycle.disposition(
            status: .stopped,
            generation: first,
            hasSurface: false
        ), .ignore)
        XCTAssertTrue(lifecycle.isActive)
        XCTAssertEqual(lifecycle.disposition(
            status: .frameComplete,
            generation: second,
            hasSurface: true
        ), .consume)
    }

    func testFallbackBlankAndIdleFramesAreNonTerminal() {
        let lifecycle = FallbackCaptureLifecycle()
        guard case .started(let generation) = lifecycle.begin() else {
            return XCTFail("fallback did not start")
        }
        XCTAssertEqual(lifecycle.disposition(
            status: .frameIdle,
            generation: generation,
            hasSurface: false
        ), .ignore)
        XCTAssertEqual(lifecycle.disposition(
            status: .frameBlank,
            generation: generation,
            hasSurface: false
        ), .clearFrame)
        XCTAssertTrue(lifecycle.isActive)
    }

    func testVirtualDisplayCapabilityRejectsMissingClassAndSelector() {
        let complete = FakeRuntimeInspector.complete()
        XCTAssertTrue(VirtualDisplayPrivateAPICapability.evaluate(
            inspector: complete
        ).isAvailable)

        var missingMode = complete
        missingMode.classes.remove("CGVirtualDisplayMode")
        XCTAssertFalse(VirtualDisplayPrivateAPICapability.evaluate(
            inspector: missingMode
        ).isAvailable)

        var missingApply = complete
        missingApply.selectors["CGVirtualDisplay"]?.remove("applySettings:")
        XCTAssertFalse(VirtualDisplayPrivateAPICapability.evaluate(
            inspector: missingApply
        ).isAvailable)
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

private struct FakeRuntimeInspector: ObjectiveCRuntimeInspecting {
    var classes: Set<String>
    var selectors: [String: Set<String>]

    func classExists(named className: String) -> Bool {
        classes.contains(className)
    }

    func instanceResponds(className: String, selector: String) -> Bool {
        selectors[className]?.contains(selector) == true
    }

    static func complete() -> FakeRuntimeInspector {
        FakeRuntimeInspector(
            classes: Set(VirtualDisplayPrivateAPICapability.requirements.map(\.className)),
            selectors: Dictionary(uniqueKeysWithValues:
                VirtualDisplayPrivateAPICapability.requirements.map {
                    ($0.className, Set($0.selectors))
                }
            )
        )
    }
}
