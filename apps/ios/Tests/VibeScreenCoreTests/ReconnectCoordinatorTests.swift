import XCTest
@testable import VibeScreenCore

final class ReconnectCoordinatorTests: XCTestCase {
    func testSchedulesUseExistingBoundedBackoff() {
        var coordinator = ReconnectCoordinator()
        let generation = coordinator.start()

        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 0.25)
        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 0.5)
        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 1)
        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 2)
        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 3)
        XCTAssertEqual(coordinator.schedule(generation: generation)?.delaySeconds, 3)
    }

    func testManualStopInvalidatesPendingGeneration() {
        var coordinator = ReconnectCoordinator()
        let stoppedGeneration = coordinator.start()
        coordinator.stop()

        XCTAssertFalse(coordinator.accepts(generation: stoppedGeneration))
        XCTAssertNil(coordinator.schedule(generation: stoppedGeneration))
    }

    func testNewSessionRejectsOldGenerationAndConnectedResetsAttempts() {
        var coordinator = ReconnectCoordinator()
        let oldGeneration = coordinator.start()
        _ = coordinator.schedule(generation: oldGeneration)
        let currentGeneration = coordinator.start()

        XCTAssertNil(coordinator.schedule(generation: oldGeneration))
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration)?.attempt, 0)
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration)?.attempt, 1)
        coordinator.markConnected(generation: currentGeneration)
        XCTAssertEqual(coordinator.schedule(generation: currentGeneration)?.attempt, 0)
    }
}
