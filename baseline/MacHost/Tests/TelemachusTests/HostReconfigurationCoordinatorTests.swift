import XCTest
@testable import Telemachus

@MainActor
final class HostReconfigurationCoordinatorTests: XCTestCase {
    private struct Configuration: Equatable {
        let mode: String
        let resolution: String
        let origin: String
        let displayID: Int

        init(
            mode: String,
            resolution: String,
            origin: String = "manual",
            displayID: Int = 1
        ) {
            self.mode = mode
            self.resolution = resolution
            self.origin = origin
            self.displayID = displayID
        }
    }

    func testBurstUsesOneStopAndOnlyFinalStart() async {
        var stops = 0
        var starts: [Configuration] = []
        let coordinator = makeCoordinator(
            stop: { stops += 1 },
            start: { configuration, _ in
                starts.append(configuration)
                return true
            }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        coordinator.request(Configuration(mode: "usb", resolution: "1920x1080"))
        coordinator.request(Configuration(mode: "usb", resolution: "2560x1600"))
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(stops, 1)
        XCTAssertEqual(starts, [Configuration(mode: "usb", resolution: "2560x1600")])
    }

    func testSingleSwitchStopsAndStartsOnce() async {
        var events: [String] = []
        let coordinator = makeCoordinator(
            stop: { events.append("stop") },
            start: { configuration, _ in
                events.append("start:\(configuration.mode)")
                return true
            }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(events, ["stop", "start:wireless"])
    }

    func testSameEffectiveConfigurationIsNoOp() async {
        var operationCount = 0
        let configuration = Configuration(mode: "usb", resolution: "1920x1080")
        let coordinator = makeCoordinator(
            stop: { operationCount += 1 },
            start: { _, _ in
                operationCount += 1
                return true
            }
        )
        coordinator.recordApplied(configuration)

        coordinator.request(configuration)
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(operationCount, 0)
    }

    func testBurstReturningToAppliedConfigurationIsNoOp() async {
        var operationCount = 0
        let applied = Configuration(mode: "usb", resolution: "1920x1080")
        let coordinator = makeCoordinator(
            stop: { operationCount += 1 },
            start: { _, _ in
                operationCount += 1
                return true
            }
        )
        coordinator.recordApplied(applied)

        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        coordinator.request(applied)
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(operationCount, 0)
    }

    func testManualStopCancelsPendingReconfiguration() async {
        let clock = ManualAsyncGate()
        var operationCount = 0
        let coordinator = HostReconfigurationCoordinator<Configuration>(
            debounceNanoseconds: 1,
            stop: { operationCount += 1 },
            start: { _, _ in
                operationCount += 1
                return true
            },
            sleep: { _ in await clock.wait() }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))
        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        await clock.waitUntilBlocked()

        coordinator.recordManualStop()
        coordinator.request(Configuration(mode: "usb", resolution: "2560x1600"))
        clock.resume()
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(operationCount, 0)

        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))
        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        await clock.waitUntilBlocked()
        clock.resume()
        await clock.waitUntilBlocked()
        clock.resume()
        await coordinator.waitUntilIdleForTesting()
        XCTAssertEqual(operationCount, 2)
    }

    func testDebounceWaitsForTrailingEdge() async {
        let clock = ManualAsyncGate()
        var stops = 0
        var starts: [Configuration] = []
        let coordinator = HostReconfigurationCoordinator<Configuration>(
            debounceNanoseconds: 1,
            stop: { stops += 1 },
            start: { configuration, _ in
                starts.append(configuration)
                return true
            },
            sleep: { _ in await clock.wait() }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        await clock.waitUntilBlocked()
        coordinator.request(Configuration(mode: "usb", resolution: "2560x1600"))
        clock.resume()
        await clock.waitUntilBlocked()
        XCTAssertEqual(stops, 0)

        clock.resume()
        await clock.waitUntilBlocked()
        XCTAssertEqual(stops, 1)
        XCTAssertTrue(starts.isEmpty)

        clock.resume()
        await coordinator.waitUntilIdleForTesting()
        XCTAssertEqual(starts, [Configuration(mode: "usb", resolution: "2560x1600")])
    }

    func testIntentSupersededDuringTeardownStartsOnlyLatestConfiguration() async {
        let teardownGate = ManualAsyncGate()
        var events: [String] = []
        let coordinator = makeCoordinator(
            stop: {
                events.append("stop")
                await teardownGate.wait()
            },
            start: { configuration, _ in
                events.append("start:\(configuration.mode):\(configuration.resolution)")
                return true
            }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(Configuration(mode: "wireless", resolution: "1920x1080"))
        await teardownGate.waitUntilBlocked()
        coordinator.request(Configuration(mode: "usb", resolution: "2560x1600"))
        teardownGate.resume()
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(events, ["stop", "start:usb:2560x1600"])
    }

    func testIntentSupersededDuringStartCannotBecomeApplied() async {
        let startGate = ManualAsyncGate()
        var stops = 0
        var completedStarts: [Configuration] = []
        let intermediate = Configuration(mode: "wireless", resolution: "1920x1080")
        let final = Configuration(mode: "usb", resolution: "2560x1600")
        let coordinator = makeCoordinator(
            stop: { stops += 1 },
            start: { configuration, isCurrent in
                if configuration == intermediate {
                    await startGate.wait()
                }
                guard isCurrent() else { return false }
                completedStarts.append(configuration)
                return true
            }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(intermediate)
        await startGate.waitUntilBlocked()
        coordinator.request(final)
        startGate.resume()
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(stops, 1)
        XCTAssertEqual(completedStarts, [final])
    }

    func testDynamicChangeDuringStartRetriesSameRebuildIntent() async {
        let startGate = ManualAsyncGate()
        var startAttempts = 0
        var completedStarts = 0
        let target = Configuration(mode: "usb", resolution: "2560x1600")
        let coordinator = makeCoordinator(
            stop: {},
            start: { configuration, isCurrent in
                startAttempts += 1
                if startAttempts == 1 {
                    await startGate.wait()
                }
                guard configuration == target, isCurrent() else { return false }
                completedStarts += 1
                return true
            }
        )
        coordinator.recordApplied(Configuration(mode: "usb", resolution: "1920x1080"))

        coordinator.request(target)
        await startGate.waitUntilBlocked()
        coordinator.request(target) // Dynamic settings changed outside the rebuild key.
        startGate.resume()
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(startAttempts, 2)
        XCTAssertEqual(completedStarts, 1)
    }

    func testCaptureTeardownCompletesBeforeDisplayDestruction() async {
        let captureGate = ManualAsyncGate()
        var events: [String] = []
        let teardown = Task { @MainActor in
            await HostTeardownOrdering.perform(
                stopListener: { events.append("listener-stopped") },
                stopCapture: {
                    events.append("capture-stop-started")
                    await captureGate.wait()
                    events.append("capture-stop-completed")
                },
                destroyDisplay: { events.append("display-destroyed") }
            )
        }

        await captureGate.waitUntilBlocked()
        XCTAssertEqual(events, ["listener-stopped", "capture-stop-started"])
        captureGate.resume()
        await teardown.value
        XCTAssertEqual(events, [
            "listener-stopped",
            "capture-stop-started",
            "capture-stop-completed",
            "display-destroyed"
        ])
    }

    func testConcurrentStopsShareWholeOperationWithoutLateStateMutation() async {
        let stopGate = ManualAsyncGate()
        let coordinator = HostStopOperationCoordinator()
        var stopCount = 0
        var state = "running"
        var secondJoined = false
        var firstReturned = false
        var secondReturned = false
        let first = Task { @MainActor in
            await coordinator.perform {
                stopCount += 1
                await stopGate.wait()
                state = "stopped"
            }
            firstReturned = true
        }
        await stopGate.waitUntilBlocked()
        let second = Task { @MainActor in
            secondJoined = true
            await coordinator.perform {
                stopCount += 1
                state = "stopped-again"
            }
            secondReturned = true
        }
        while !secondJoined {
            await Task.yield()
        }
        XCTAssertFalse(firstReturned)
        XCTAssertFalse(secondReturned)

        stopGate.resume()
        await first.value
        await second.value
        XCTAssertTrue(firstReturned)
        XCTAssertTrue(secondReturned)
        state = "replacement-running"
        await Task.yield()

        XCTAssertEqual(stopCount, 1)
        XCTAssertEqual(state, "replacement-running")

        await coordinator.perform {
            stopCount += 1
        }
        XCTAssertEqual(stopCount, 2)
    }

    func testTerminationDefersOnceAndTerminatesNowAfterCleanup() {
        let coordinator = HostTerminationCoordinator()
        var cleanupCount = 0

        if coordinator.requestTermination() == .beginDeferredCleanup {
            cleanupCount += 1
        }
        XCTAssertEqual(coordinator.requestTermination(), .waitForDeferredCleanup)
        XCTAssertEqual(cleanupCount, 1)

        coordinator.completeCleanup()
        XCTAssertEqual(coordinator.requestTermination(), .terminateNow)
        XCTAssertEqual(coordinator.requestTermination(), .terminateNow)
        XCTAssertEqual(cleanupCount, 1)
    }

    func testRestartWaitsForExistingAndNewlyAppendedStopBarriers() async {
        let firstStopGate = ManualAsyncGate()
        let secondStopGate = ManualAsyncGate()
        let barrier = AsyncStopBarrier()
        var setupCount = 0
        barrier.enqueue {
            await firstStopGate.wait()
        }
        let restart = Task { @MainActor in
            await barrier.waitForAll()
            setupCount += 1
        }

        await firstStopGate.waitUntilBlocked()
        barrier.enqueue {
            await secondStopGate.wait()
        }
        XCTAssertEqual(setupCount, 0)

        firstStopGate.resume()
        await secondStopGate.waitUntilBlocked()
        XCTAssertEqual(setupCount, 0)

        secondStopGate.resume()
        await restart.value
        XCTAssertEqual(setupCount, 1)
    }

    func testStopLeaseIsReleasedBeforeOwnerTaskReturns() async {
        let ownerReturnGate = ManualAsyncGate()
        var releaseHookCount = 0
        var stopCount = 0
        var state = "running"
        let coordinator = HostStopOperationCoordinator(
            afterReleaseHook: {
                releaseHookCount += 1
                if releaseHookCount == 1 {
                    await ownerReturnGate.wait()
                }
            }
        )
        let first = Task { @MainActor in
            await coordinator.perform {
                stopCount += 1
                state = "stopped-first"
            }
        }
        await ownerReturnGate.waitUntilBlocked()

        state = "replacement-running"
        await coordinator.perform {
            stopCount += 1
            state = "stopped-replacement"
        }
        XCTAssertEqual(stopCount, 2)
        XCTAssertEqual(state, "stopped-replacement")

        ownerReturnGate.resume()
        await first.value
        XCTAssertEqual(state, "stopped-replacement")
    }

    func testOlderOwnerCannotFollowUpAfterNewerStopFinalizes() async {
        let firstOwnerReturnGate = ManualAsyncGate()
        var releaseHookCount = 0
        var lastCompletedGeneration: UInt64 = 0
        let coordinator = HostStopOperationCoordinator(
            afterReleaseHook: {
                releaseHookCount += 1
                if releaseHookCount == 1 {
                    await firstOwnerReturnGate.wait()
                }
            }
        )
        let firstOwner = Task { @MainActor in
            await coordinator.perform({}, finalize: { generation in
                lastCompletedGeneration = generation
            })
        }
        await firstOwnerReturnGate.waitUntilBlocked()

        let secondResult = await coordinator.perform({}, finalize: { generation in
            lastCompletedGeneration = generation
        })
        XCTAssertEqual(lastCompletedGeneration, secondResult.generation)

        firstOwnerReturnGate.resume()
        let firstResult = await firstOwner.value
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: firstResult.performedOperation,
            requestedGeneration: firstResult.generation,
            lastCompletedGeneration: lastCompletedGeneration,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: false
        ))
    }

    func testJoiningPreserveRequestWinsBeforeSharedStopTail() async {
        let teardownGate = ManualAsyncGate()
        let stopCoordinator = HostStopOperationCoordinator()
        let preservation = StopRecoveryPreservationAccumulator()
        var observedPreserve = false
        var joinerStarted = false
        preservation.request(preserveRecoveryState: false)
        let owner = Task { @MainActor in
            await stopCoordinator.perform {
                await teardownGate.wait()
                observedPreserve = preservation.consume()
            }
        }
        await teardownGate.waitUntilBlocked()
        let joiner = Task { @MainActor in
            preservation.request(preserveRecoveryState: true)
            joinerStarted = true
            await stopCoordinator.perform {
                XCTFail("joiner unexpectedly created a second stop")
            }
        }
        while !joinerStarted {
            await Task.yield()
        }

        teardownGate.resume()
        await owner.value
        await joiner.value
        XCTAssertTrue(observedPreserve)
    }

    func testJoiningManualStopSuppressesOwnerFollowUp() async {
        let teardownGate = ManualAsyncGate()
        let stopCoordinator = HostStopOperationCoordinator()
        let suppression = StopFollowUpSuppressionAccumulator()
        var observedSuppression = false
        var joinerStarted = false
        suppression.request(suppressFollowUp: false)
        let owner = Task { @MainActor in
            await stopCoordinator.perform({
                await teardownGate.wait()
                observedSuppression = suppression.consume()
            }, finalize: { _ in })
        }
        await teardownGate.waitUntilBlocked()
        let joiner = Task { @MainActor in
            suppression.request(suppressFollowUp: true)
            joinerStarted = true
            return await stopCoordinator.perform {
                XCTFail("manual-stop joiner unexpectedly created a second stop")
            }
        }
        while !joinerStarted {
            await Task.yield()
        }

        teardownGate.resume()
        let ownerResult = await owner.value
        _ = await joiner.value
        XCTAssertTrue(observedSuppression)
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: ownerResult.performedOperation,
            requestedGeneration: ownerResult.generation,
            lastCompletedGeneration: ownerResult.generation,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: observedSuppression
        ))
    }

    func testStopLifecycleStaysNonStartableUntilTeardownCompletes() async {
        let lifecycle = HostServerLifecycle()
        let teardownGate = ManualAsyncGate()
        let startToken = lifecycle.beginStart()!
        let stop = Task { @MainActor in
            let stopToken = lifecycle.beginStop()
            await teardownGate.wait()
            lifecycle.finishStop(stopToken)
        }
        await teardownGate.waitUntilBlocked()

        XCTAssertFalse(lifecycle.isCurrentStart(startToken))
        XCTAssertFalse(lifecycle.canStart)
        teardownGate.resume()
        await stop.value
        XCTAssertTrue(lifecycle.canStart)
    }

    func testInitialStartIntentCanBeSupersededWithoutLosingOrigin() async {
        let startGate = ManualAsyncGate()
        var attempts: [Configuration] = []
        var completed: [Configuration] = []
        let coordinator = makeCoordinator(
            stop: {},
            start: { configuration, isCurrent in
                attempts.append(configuration)
                if attempts.count == 1 {
                    await startGate.wait()
                }
                guard isCurrent() else { return false }
                completed.append(configuration)
                return true
            }
        )
        coordinator.requestStart(Configuration(
            mode: "usb",
            resolution: "1920x1080",
            origin: "automatic"
        ))
        await startGate.waitUntilBlocked()
        coordinator.updateIntent { current in
            Configuration(
                mode: "wireless",
                resolution: "2560x1600",
                origin: current.origin,
                displayID: 2
            )
        }
        startGate.resume()
        await coordinator.waitUntilIdleForTesting()

        XCTAssertEqual(attempts.count, 2)
        XCTAssertEqual(completed, [Configuration(
            mode: "wireless",
            resolution: "2560x1600",
            origin: "automatic",
            displayID: 2
        )])
    }

    func testPendingInitialStartCanBeCancelledByToggleIntent() async {
        let clock = ManualAsyncGate()
        var starts = 0
        let coordinator = HostReconfigurationCoordinator<Configuration>(
            debounceNanoseconds: 1,
            stop: {},
            start: { _, _ in
                starts += 1
                return true
            },
            sleep: { _ in await clock.wait() }
        )
        coordinator.requestStart(Configuration(mode: "usb", resolution: "1920x1080"))
        await clock.waitUntilBlocked()
        XCTAssertTrue(coordinator.hasDesiredRunning)

        coordinator.recordManualStop()
        clock.resume()
        await coordinator.waitUntilIdleForTesting()
        XCTAssertFalse(coordinator.hasDesiredRunning)
        XCTAssertEqual(starts, 0)
    }

    func testStopFollowUpRejectsOlderGenerationAndReplacementSession() {
        XCTAssertTrue(HostStopFollowUpPolicy.shouldApply(
            performedOperation: true,
            requestedGeneration: 2,
            lastCompletedGeneration: 2,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: false
        ))
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: true,
            requestedGeneration: 1,
            lastCompletedGeneration: 2,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: false
        ))
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: true,
            requestedGeneration: 2,
            lastCompletedGeneration: 2,
            lifecycleIsIdle: true,
            hasActiveConfiguration: true,
            hasDesiredRunning: false,
            followUpWasSuppressed: false
        ))
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: false,
            requestedGeneration: 2,
            lastCompletedGeneration: 2,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: false
        ))
        XCTAssertFalse(HostStopFollowUpPolicy.shouldApply(
            performedOperation: true,
            requestedGeneration: 2,
            lastCompletedGeneration: 2,
            lifecycleIsIdle: true,
            hasActiveConfiguration: false,
            hasDesiredRunning: false,
            followUpWasSuppressed: true
        ))
    }

    func testSelectedDisplayIdentityReplacementCanClearPersistentUUID() {
        let original = HostSelectedDisplayIdentity(
            id: 10,
            persistentUUID: "old-display"
        )

        let replacement = original.replacing(id: 11, persistentUUID: nil)

        XCTAssertEqual(replacement.id, 11)
        XCTAssertNil(replacement.persistentUUID)
    }

    private func makeCoordinator(
        stop: @escaping @MainActor () async -> Void,
        start: @escaping @MainActor (
            Configuration,
            @escaping @MainActor () -> Bool
        ) async -> Bool
    ) -> HostReconfigurationCoordinator<Configuration> {
        HostReconfigurationCoordinator(
            debounceNanoseconds: 0,
            stop: stop,
            start: start,
            sleep: { _ in }
        )
    }
}

@MainActor
private final class ManualAsyncGate {
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        await withCheckedContinuation { continuation in
            precondition(self.continuation == nil)
            self.continuation = continuation
        }
    }

    func waitUntilBlocked() async {
        while continuation == nil {
            await Task.yield()
        }
    }

    func resume() {
        let blocked = continuation
        continuation = nil
        blocked?.resume()
    }
}
