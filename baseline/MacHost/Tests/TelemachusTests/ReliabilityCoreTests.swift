import Foundation
import XCTest
@testable import Telemachus

final class ReliabilityCoreTests: XCTestCase {
    private struct Frame: Equatable {
        let id: Int
        let keyframe: Bool
    }

    func testLatestFrameQueueRejectsInvalidCapacity() {
        XCTAssertThrowsError(try makeQueue(capacity: 0)) { error in
            XCTAssertEqual(error as? LatestFrameQueueError, .invalidCapacity(0))
        }
        XCTAssertThrowsError(try makeQueue(capacity: 3)) { error in
            XCTAssertEqual(error as? LatestFrameQueueError, .invalidCapacity(3))
        }
    }

    func testLatestFrameQueueWaitsForKeyframeAndNeverExceedsCapacity() throws {
        var queue = try makeQueue(capacity: 2)

        XCTAssertEqual(
            queue.enqueue(Frame(id: 1, keyframe: false)),
            LatestFrameEnqueueResult(accepted: false, droppedCount: 1, requiresKeyframe: true)
        )
        XCTAssertEqual(
            queue.enqueue(Frame(id: 2, keyframe: true)),
            LatestFrameEnqueueResult(accepted: true, droppedCount: 0, requiresKeyframe: false)
        )
        XCTAssertEqual(queue.enqueue(Frame(id: 3, keyframe: false)).accepted, true)
        XCTAssertLessThanOrEqual(queue.count, 2)

        let overflow = queue.enqueue(Frame(id: 4, keyframe: false))
        XCTAssertFalse(overflow.accepted)
        XCTAssertEqual(overflow.droppedCount, 1)
        XCTAssertFalse(overflow.requiresKeyframe)
        XCTAssertEqual(queue.dequeue(), Frame(id: 2, keyframe: true))
        XCTAssertEqual(queue.dequeue(), Frame(id: 3, keyframe: false))
    }

    func testDependentOverflowDropsBacklogAndRequestsKeyframe() throws {
        var queue = try makeQueue(capacity: 2, requiresKeyframe: false)
        XCTAssertTrue(queue.enqueue(Frame(id: 1, keyframe: false)).accepted)
        XCTAssertTrue(queue.enqueue(Frame(id: 2, keyframe: false)).accepted)

        let result = queue.enqueue(Frame(id: 3, keyframe: false))

        XCTAssertEqual(
            result,
            LatestFrameEnqueueResult(accepted: false, droppedCount: 3, requiresKeyframe: true)
        )
        XCTAssertEqual(queue.count, 0)
        XCTAssertFalse(queue.enqueue(Frame(id: 4, keyframe: false)).accepted)
        XCTAssertTrue(queue.enqueue(Frame(id: 5, keyframe: true)).accepted)
        XCTAssertEqual(queue.dequeue(), Frame(id: 5, keyframe: true))
    }

    func testNewKeyframeReplacesPendingBacklog() throws {
        var queue = try makeQueue(capacity: 2, requiresKeyframe: false)
        XCTAssertTrue(queue.enqueue(Frame(id: 1, keyframe: false)).accepted)
        XCTAssertTrue(queue.enqueue(Frame(id: 2, keyframe: false)).accepted)

        let result = queue.enqueue(Frame(id: 3, keyframe: true))

        XCTAssertEqual(result.droppedCount, 2)
        XCTAssertEqual(queue.count, 1)
        XCTAssertEqual(queue.dequeue(), Frame(id: 3, keyframe: true))
    }

    func testSessionEpochGateRejectsOldAndNonIncreasingEpochs() throws {
        let gate = SessionEpochGate()
        XCTAssertEqual(try gate.beginNextSession(), 1)
        XCTAssertTrue(gate.accepts(1))
        XCTAssertEqual(try gate.beginNextSession(), 2)
        XCTAssertFalse(gate.accepts(1))
        XCTAssertTrue(gate.accepts(2))
        XCTAssertThrowsError(try gate.activate(2)) { error in
            XCTAssertEqual(
                error as? SessionEpochError,
                .nonIncreasingEpoch(current: 2, proposed: 2)
            )
        }
        try gate.activate(7)
        XCTAssertTrue(gate.accepts(7))
    }

    func testHeartbeatTimeoutTransitionsToBoundedReconnectBackoff() {
        var controller = ConnectionRecoveryController(
            heartbeatTimeoutNs: 100,
            backoff: ReconnectBackoff(initialDelayNs: 10, maximumDelayNs: 25)
        )
        controller.startConnecting()
        XCTAssertEqual(controller.state, .connecting(attempt: 1))
        controller.didConnect(epoch: 4, nowNs: 1_000)
        XCTAssertFalse(controller.observeHeartbeat(epoch: 3, nowNs: 1_050))
        XCTAssertTrue(controller.observeHeartbeat(epoch: 4, nowNs: 1_050))
        XCTAssertFalse(controller.heartbeatTimedOut(nowNs: 1_149))
        XCTAssertTrue(controller.heartbeatTimedOut(nowNs: 1_150))
        XCTAssertEqual(
            controller.state,
            .waitingToReconnect(attempt: 1, deadlineNs: 1_160)
        )

        XCTAssertEqual(controller.scheduleReconnect(nowNs: 2_000), 20)
        XCTAssertEqual(controller.scheduleReconnect(nowNs: 3_000), 25)
        XCTAssertEqual(controller.scheduleReconnect(nowNs: 4_000), 25)
    }

    func testExplicitCodecFallbackAndNoMutualCodecFailure() throws {
        let preferred = try CodecFallbackPolicy.select(
            preferred: .hevc,
            hostSupported: [.hevc, .h264],
            clientSupported: [.hevc, .h264]
        )
        XCTAssertEqual(preferred.selected, .hevc)
        XCTAssertEqual(preferred.reason, .preferredSupported)

        let fallback = try CodecFallbackPolicy.select(
            preferred: .hevc,
            hostSupported: [.hevc, .h264],
            clientSupported: [.h264]
        )
        XCTAssertEqual(fallback.selected, .h264)
        XCTAssertEqual(fallback.reason, .preferredUnavailable)

        XCTAssertThrowsError(
            try CodecFallbackPolicy.select(
                preferred: .hevc,
                hostSupported: [.hevc],
                clientSupported: [.h264]
            )
        ) { error in
            XCTAssertEqual(error as? CodecFallbackError, .noMutuallySupportedCodec)
        }
    }

    func testJSONLTelemetryWritesOneDecodableObjectPerLine() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        addTeardownBlock {
            try FileManager.default.removeItem(at: directory)
        }
        let url = directory.appendingPathComponent("telemetry.jsonl")
        let sink = try JSONLTelemetrySink(url: url)

        try sink.record(
            TelemetryEvent(
                event: "frame_queue_drop",
                sessionEpoch: 9,
                attributes: [
                    "dropped": .unsigned(2),
                    "keyframe_required": .boolean(true)
                ],
                wallTime: "2026-08-04T00:00:00Z",
                monotonicNs: 123
            )
        )
        try sink.close()

        let bytes = try Data(contentsOf: url)
        XCTAssertEqual(bytes.last, 0x0A)
        let lines = bytes.split(separator: 0x0A)
        XCTAssertEqual(lines.count, 1)
        let decoded = try JSONDecoder().decode(TelemetryEvent.self, from: Data(lines[0]))
        XCTAssertEqual(decoded.event, "frame_queue_drop")
        XCTAssertEqual(decoded.sessionEpoch, 9)
        XCTAssertEqual(decoded.attributes["dropped"], .integer(2))
        XCTAssertEqual(decoded.attributes["keyframe_required"], .boolean(true))
    }

    func testJSONLTelemetryClosesOnDeinit() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        addTeardownBlock {
            try FileManager.default.removeItem(at: directory)
        }
        let url = directory.appendingPathComponent("telemetry.jsonl")

        do {
            let sink = try JSONLTelemetrySink(url: url)
            try sink.record(TelemetryEvent(event: "deinit_flush"))
        }

        let lines = try Data(contentsOf: url).split(separator: 0x0A)
        XCTAssertEqual(lines.count, 1)
        let decoded = try JSONDecoder().decode(TelemetryEvent.self, from: Data(lines[0]))
        XCTAssertEqual(decoded.event, "deinit_flush")
    }

    private func makeQueue(
        capacity: Int,
        requiresKeyframe: Bool = true
    ) throws -> LatestFrameQueue<Frame> {
        try LatestFrameQueue(
            capacity: capacity,
            requiresKeyframe: requiresKeyframe,
            isKeyframe: { $0.keyframe }
        )
    }
}
