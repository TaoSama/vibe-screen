import CoreGraphics
import XCTest
@testable import Telemachus

final class Phase1HostCapabilityTests: XCTestCase {
    func testTouchGestureFactoryIsolatesSyntheticZoomModifier() throws {
        let pointerSource = try XCTUnwrap(CGEventSource(stateID: .privateState))
        let zoomSource = try XCTUnwrap(CGEventSource(stateID: .privateState))
        pointerSource.userData = 101
        zoomSource.userData = 202
        let factory = TouchGestureEventFactory(
            pointerSource: pointerSource,
            zoomSource: zoomSource
        )
        let zoom = try XCTUnwrap(factory.scrollEvent(
            deltaX: 0,
            deltaY: 10,
            position: .zero,
            commandModified: true
        ))
        XCTAssertTrue(zoom.flags.contains(.maskCommand))
        XCTAssertEqual(zoom.getIntegerValueField(.eventSourceUserData), 202)

        let down = try XCTUnwrap(factory.mouseEvent(
            type: .leftMouseDown,
            position: .zero,
            button: .left,
            clickState: 1
        ))
        let drag = try XCTUnwrap(factory.mouseEvent(
            type: .leftMouseDragged,
            position: .zero,
            button: .left
        ))
        let up = try XCTUnwrap(factory.mouseEvent(
            type: .leftMouseUp,
            position: .zero,
            button: .left,
            clickState: 1
        ))
        let scroll = try XCTUnwrap(factory.scrollEvent(
            deltaX: 1,
            deltaY: 2,
            position: .zero
        ))
        for event in [down, drag, up, scroll] {
            XCTAssertEqual(event.getIntegerValueField(.eventSourceUserData), 101)
            XCTAssertFalse(event.flags.contains(.maskCommand))
        }
        XCTAssertEqual(down.type, .leftMouseDown)
        XCTAssertEqual(drag.type, .leftMouseDragged)
        XCTAssertEqual(up.type, .leftMouseUp)
        XCTAssertEqual(down.getIntegerValueField(.mouseEventButtonNumber), 0)
        XCTAssertEqual(drag.getIntegerValueField(.mouseEventButtonNumber), 0)
        XCTAssertEqual(up.getIntegerValueField(.mouseEventButtonNumber), 0)
        XCTAssertEqual(down.getIntegerValueField(.mouseEventClickState), 1)
        XCTAssertEqual(drag.getIntegerValueField(.mouseEventClickState), 1)
        XCTAssertEqual(up.getIntegerValueField(.mouseEventClickState), 1)
    }

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

    @MainActor
    func testQueuedOldCallbackCannotMutateReplacementSession() async {
        final class Source {}
        let lifecycle = HostServerLifecycle()
        let oldSource = Source()
        let replacementSource = Source()
        var currentSource: Source? = oldSource
        var mutations = 0
        let oldToken = lifecycle.beginStart()!
        XCTAssertTrue(lifecycle.finishStart(oldToken))

        let queuedCallback = Task { @MainActor in
            if lifecycle.acceptsCallback(
                oldToken,
                sourceMatches: currentSource === oldSource,
                clientGeneration: 1
            ) {
                mutations += 1
            }
        }
        let stop = lifecycle.beginStop()
        lifecycle.finishStop(stop)
        let replacementToken = lifecycle.beginStart()!
        XCTAssertTrue(lifecycle.finishStart(replacementToken))
        currentSource = replacementSource

        await queuedCallback.value
        XCTAssertEqual(mutations, 0)
    }

    @MainActor
    func testOlderClientGenerationCannotOverrideTakeover() {
        let lifecycle = HostServerLifecycle()
        let token = lifecycle.beginStart()!
        XCTAssertTrue(lifecycle.finishStart(token))
        XCTAssertTrue(lifecycle.acceptsCallback(
            token,
            sourceMatches: true,
            clientGeneration: 2
        ))
        XCTAssertFalse(lifecycle.acceptsCallback(
            token,
            sourceMatches: true,
            clientGeneration: 1
        ))
    }

    func testAuthoritativeGenerationRejectsCallbackQueuedBeforeTakeover() {
        let gate = ClientCallbackGenerationGate()
        gate.advance(to: 1)
        gate.advance(to: 2)
        var oldClientMutations = 0

        XCTAssertFalse(gate.performIfCurrent(1) {
            oldClientMutations += 1
        })
        XCTAssertEqual(oldClientMutations, 0)
        XCTAssertTrue(gate.performIfCurrent(2) {
            oldClientMutations += 1
        })
        XCTAssertEqual(oldClientMutations, 1)
        gate.advance(to: 1)
        XCTAssertTrue(gate.isCurrent(2))
    }

    func testInvalidatedGenerationRejectsLaterQueuedControllerDelivery() {
        let gate = ClientCallbackGenerationGate()
        gate.advance(to: 7)
        var delivered = 0

        XCTAssertTrue(gate.performIfCurrent(7) { delivered += 1 })
        XCTAssertTrue(gate.invalidateIfCurrent(7))
        XCTAssertFalse(gate.performIfCurrent(7) { delivered += 1 })
        XCTAssertFalse(gate.invalidateIfCurrent(7))
        XCTAssertEqual(delivered, 1)
        XCTAssertTrue(gate.isCurrent(8))
    }

    @MainActor
    func testAutomaticLaunchIntentIsConsumedOnlyOnce() {
        let launch = AutomaticLaunchCoordinator(enabled: true)
        XCTAssertTrue(launch.consumeIfEligible(true))
        XCTAssertFalse(launch.consumeIfEligible(true))
    }

    @MainActor
    func testSlowPermissionCompletionCannotBypassRecovery() {
        let launch = AutomaticLaunchCoordinator(enabled: true)
        XCTAssertTrue(launch.consumeIfEligible(true))
        let lifecycle = HostServerLifecycle()
        let failedStart = lifecycle.beginStart()!
        lifecycle.failStart(failedStart)
        XCTAssertTrue(lifecycle.canStart)
        XCTAssertFalse(launch.consumeIfEligible(true))
        XCTAssertEqual(UnattendedRecoveryPolicy.delay(afterFailure: 0), 1)
    }

    @MainActor
    func testAutomaticLaunchWaitsForPermissionAndDisabledNeverLaunches() {
        let pending = AutomaticLaunchCoordinator(enabled: true)
        XCTAssertFalse(pending.consumeIfEligible(false))
        XCTAssertTrue(pending.consumeIfEligible(true))
        let disabled = AutomaticLaunchCoordinator(enabled: false)
        XCTAssertFalse(disabled.consumeIfEligible(true))
    }

    func testUnattendedRecoveryPolicyUsesBoundedBackoffAndStopsAfterLimit() {
        let expectedDelays: [TimeInterval?] = [
            nil,
            1,
            2,
            4,
            8,
            16,
            30,
            30,
            30,
            nil
        ]
        let attempts = (-1...UnattendedRecoveryPolicy.maximumAttempts).map {
            UnattendedRecoveryPolicy.delay(afterFailure: $0)
        }

        XCTAssertEqual(attempts, expectedDelays)
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

    func testStoppedFallbackRebuildsReplacementBeforeMonitor() {
        XCTAssertEqual(FallbackStoppedPolicy.action(
            followsMainDisplay: true,
            capturedDisplayID: 10,
            currentMainDisplayID: 11
        ), .rebuild(11))
        let lifecycle = FallbackCaptureLifecycle()
        guard case .started(let oldGeneration) = lifecycle.begin() else {
            return XCTFail("old fallback did not start")
        }
        XCTAssertEqual(lifecycle.disposition(
            status: .stopped,
            generation: oldGeneration,
            hasSurface: false
        ), .terminalFailure)
        XCTAssertTrue(lifecycle.claimTerminal(generation: oldGeneration))
        guard case .started(let replacementGeneration) = lifecycle.begin() else {
            return XCTFail("replacement fallback did not start")
        }
        XCTAssertEqual(lifecycle.disposition(
            status: .stopped,
            generation: oldGeneration,
            hasSurface: false
        ), .ignore)
        XCTAssertEqual(lifecycle.disposition(
            status: .frameComplete,
            generation: replacementGeneration,
            hasSurface: true
        ), .consume)
    }

    func testStoppedFallbackWithoutReplacementIsTerminal() {
        XCTAssertEqual(FallbackStoppedPolicy.action(
            followsMainDisplay: true,
            capturedDisplayID: 10,
            currentMainDisplayID: 10
        ), .terminalFailure)
        XCTAssertEqual(FallbackStoppedPolicy.action(
            followsMainDisplay: false,
            capturedDisplayID: 10,
            currentMainDisplayID: 11
        ), .terminalFailure)
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
