import Foundation
import XCTest
@testable import VibeScreenCore

final class ReconnectCoordinatorTests: XCTestCase {
    func testManualDisconnectSuppressesQueueErrorsAndClearsAnyOldError() {
        XCTAssertFalse(SessionClosureContext.manualDisconnect.reportsEnqueueErrors)
        XCTAssertTrue(SessionClosureContext.manualDisconnect.clearsErrorOnCompletion)
        XCTAssertTrue(SessionClosureContext.manualDisconnect.shouldEnqueueDisconnectNotice(
            hasSession: true,
            allReleasesAdmitted: false
        ))
        XCTAssertFalse(SessionClosureContext.manualDisconnect.shouldEnqueueDisconnectNotice(
            hasSession: false,
            allReleasesAdmitted: true
        ))
        XCTAssertNil(SessionClosureContext.manualDisconnect.errorOnCompletion(
            currentError: "release enqueue failed"
        ))
        XCTAssertTrue(SessionClosureContext.sessionFailure.reportsEnqueueErrors)
        XCTAssertFalse(SessionClosureContext.sessionFailure.clearsErrorOnCompletion)
        XCTAssertEqual(SessionClosureContext.sessionFailure.errorOnCompletion(
            currentError: "transport failed"
        ), "transport failed")
        XCTAssertNil(SessionClosureContext.manualDisconnect.errorAfterEnqueueFailure(
            currentError: nil,
            enqueueError: "queue inactive"
        ))
        XCTAssertEqual(SessionClosureContext.sessionFailure.errorAfterEnqueueFailure(
            currentError: "video stream ended",
            enqueueError: "queue inactive"
        ), "video stream ended")
        XCTAssertEqual(SessionClosureContext.sessionFailure.errorAfterEnqueueFailure(
            currentError: nil,
            enqueueError: "queue inactive"
        ), "queue inactive")
    }

    func testScheduleUsesBoundedBackoffAndAttemptLimit() {
        var coordinator = ReconnectCoordinator()
        let generation = coordinator.start()
        let delays = (0..<5).map { _ in
            coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds
        }
        XCTAssertEqual(delays.compactMap { $0 }, [0.25, 0.5, 1, 2, 3])
        XCTAssertNil(coordinator.schedule(generation: generation, failure: .transientTransport))
    }

    func testStopAndNewSessionRejectOldGeneration() {
        var coordinator = ReconnectCoordinator()
        let stoppedGeneration = coordinator.start()
        coordinator.stop()
        XCTAssertFalse(coordinator.accepts(generation: stoppedGeneration))

        let oldGeneration = coordinator.start()
        _ = coordinator.schedule(generation: oldGeneration, failure: .heartbeat)
        let currentGeneration = coordinator.start()
        XCTAssertNil(coordinator.schedule(generation: oldGeneration, failure: .transientTransport))
        XCTAssertEqual(
            coordinator.schedule(generation: currentGeneration, failure: .transientTransport)?.attempt,
            0
        )
    }

    func testPermanentFailureStopsWithoutRetry() {
        var coordinator = ReconnectCoordinator()
        let generation = coordinator.start()
        XCTAssertNil(coordinator.schedule(generation: generation, failure: .permanent))
        XCTAssertFalse(coordinator.accepts(generation: generation))
    }

    func testDisconnectNoticeMayResumeControlsRetryability() {
        XCTAssertEqual(
            ReconnectFailure.fromDisconnectNotice(mayResume: true),
            .transientTransport
        )
        XCTAssertEqual(
            ReconnectFailure.fromDisconnectNotice(mayResume: false),
            .permanent
        )
    }

    func testClassifierRetriesOnlyTransportAndHeartbeatFailures() {
        XCTAssertEqual(ReconnectFailure.classify(TCPTransportError.connectionClosed), .transientTransport)
        XCTAssertEqual(ReconnectFailure.classify(TCPTransportError.timedOut("send")), .transientTransport)
        XCTAssertEqual(ReconnectFailure.classify(ControlOutboxError.sendFailed("reset")), .transientTransport)
        XCTAssertEqual(ReconnectFailure.classify(HeartbeatMonitorError.timedOut), .heartbeat)

        XCTAssertEqual(ReconnectFailure.classify(TCPTransportError.authenticationRequired), .permanent)
        XCTAssertEqual(
            ReconnectFailure.classify(TrustedLANHandshakeError.rejected(.invalidToken)),
            .permanent
        )
        XCTAssertEqual(
            ReconnectFailure.classify(ProtocolV1UpgradeError.invalidAcknowledgement(Data())),
            .permanent
        )
        XCTAssertEqual(ReconnectFailure.classify(TransportFramerError.unknownChannel(99)), .permanent)
        XCTAssertEqual(ReconnectFailure.classify(ClientControlEnvelopeError.invalidSession), .permanent)
    }
}
