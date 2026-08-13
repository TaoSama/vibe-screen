import XCTest
@testable import VibeScreenCore

final class ReconnectCoordinatorTests: XCTestCase {
    func testSchedulesUseExistingBoundedBackoff() {
        var coordinator = ReconnectCoordinator()
        let generation = coordinator.start()

        XCTAssertEqual(coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds, 0.25)
        XCTAssertEqual(coordinator.schedule(generation: generation, failure: .heartbeat)?.delaySeconds, 0.5)
        XCTAssertEqual(coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds, 1)
        XCTAssertEqual(coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds, 2)
        XCTAssertEqual(coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds, 3)
        XCTAssertNil(coordinator.schedule(generation: generation, failure: .transientTransport))
    }

    func testManualStopInvalidatesPendingGeneration() {
        var coordinator = ReconnectCoordinator()
        let stoppedGeneration = coordinator.start()
        coordinator.stop()

        XCTAssertFalse(coordinator.accepts(generation: stoppedGeneration))
        XCTAssertNil(coordinator.schedule(generation: stoppedGeneration, failure: .transientTransport))
    }

    func testNewSessionRejectsOldGenerationAndConnectedResetsAttempts() {
        var coordinator = ReconnectCoordinator()
        let oldGeneration = coordinator.start()
        _ = coordinator.schedule(generation: oldGeneration, failure: .transientTransport)
        let currentGeneration = coordinator.start()

        XCTAssertNil(coordinator.schedule(generation: oldGeneration, failure: .transientTransport))
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration, failure: .transientTransport)?.attempt, 0)
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration, failure: .transientTransport)?.attempt, 1)
        coordinator.markConnected(generation: currentGeneration)
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration, failure: .transientTransport)?.attempt, 0)
    }

    func testPermanentFailureDoesNotRetryAndManualStartRecovers() {
        var coordinator = ReconnectCoordinator()
        let failedGeneration = coordinator.start()
        XCTAssertNil(coordinator.schedule(generation: failedGeneration, failure: .permanent))
        XCTAssertFalse(coordinator.accepts(generation: failedGeneration))

        let manualGeneration = coordinator.start()
        XCTAssertTrue(coordinator.accepts(generation: manualGeneration))
        XCTAssertEqual(
            coordinator.schedule(generation: manualGeneration, failure: .transientTransport)?.attempt,
            0
        )
    }
}
