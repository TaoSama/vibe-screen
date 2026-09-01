import Foundation

enum ReliabilityCoreSelfTest {
    private struct Frame {
        let id: Int
        let keyframe: Bool
    }

    static func run() -> Bool {
        var failures: [String] = []
        testQueue(failures: &failures)
        testMailboxKeyframeSync(failures: &failures)
        testEpoch(failures: &failures)
        testRecovery(failures: &failures)
        testCodec(failures: &failures)
        testTelemetry(failures: &failures)

        if failures.isEmpty {
            print("Reliability self-test: PASS (queue, epoch, heartbeat/backoff, codec, JSONL)")
            return true
        }
        print("Reliability self-test: FAIL (\(failures.joined(separator: "; ")))")
        return false
    }

    private static func testQueue(failures: inout [String]) {
        do {
            var queue = try LatestFrameQueue<Frame>(
                capacity: 2,
                requiresKeyframe: false,
                isKeyframe: { $0.keyframe }
            )
            _ = queue.enqueue(Frame(id: 1, keyframe: false))
            _ = queue.enqueue(Frame(id: 2, keyframe: false))
            let overflow = queue.enqueue(Frame(id: 3, keyframe: false))
            guard !overflow.accepted,
                  overflow.droppedCount == 3,
                  overflow.requiresKeyframe,
                  queue.count == 0 else {
                failures.append("latest-frame overflow did not require a keyframe")
                return
            }
            _ = queue.enqueue(Frame(id: 4, keyframe: true))
            guard queue.dequeue()?.id == 4 else {
                failures.append("latest-frame queue did not recover on keyframe")
                return
            }
        } catch {
            failures.append("latest-frame queue setup failed: \(error)")
        }
    }

    private static func testMailboxKeyframeSync(failures: inout [String]) {
        let mailbox = LatestFrameMailbox<Frame>(isKeyframe: { $0.keyframe })
        mailbox.reset(generation: 1, sessionEpoch: 10, accepting: true)

        guard mailbox.submit(Frame(id: 1, keyframe: true), generation: 1, sessionEpoch: 10),
              mailbox.take(generation: 1, sessionEpoch: 10)?.element?.id == 1 else {
            failures.append("latest-frame mailbox did not admit the initial keyframe")
            return
        }

        guard !mailbox.submit(Frame(id: 2, keyframe: false), generation: 1, sessionEpoch: 10) else {
            failures.append("latest-frame mailbox scheduled an unexpected dependent drain")
            return
        }
        mailbox.requireKeyframe(generation: 1, sessionEpoch: 10)
        guard mailbox.finishDrain(generation: 1, sessionEpoch: 10),
              let rejectedDependent = mailbox.take(generation: 1, sessionEpoch: 10),
              rejectedDependent.element == nil,
              rejectedDependent.droppedCount == 1,
              rejectedDependent.requiresKeyframe else {
            failures.append("latest-frame mailbox did not drop pending dependent frame after keyframe sync")
            return
        }

        guard !mailbox.finishDrain(generation: 1, sessionEpoch: 10),
              mailbox.submit(Frame(id: 3, keyframe: false), generation: 1, sessionEpoch: 10),
              let nextRejectedDependent = mailbox.take(generation: 1, sessionEpoch: 10),
              nextRejectedDependent.element == nil,
              nextRejectedDependent.droppedCount == 1,
              nextRejectedDependent.requiresKeyframe,
              !mailbox.finishDrain(generation: 1, sessionEpoch: 10),
              mailbox.submit(Frame(id: 4, keyframe: true), generation: 1, sessionEpoch: 10),
              let replacement = mailbox.take(generation: 1, sessionEpoch: 10),
              replacement.element?.id == 4,
              replacement.droppedCount == 0,
              !replacement.requiresKeyframe else {
            failures.append("latest-frame mailbox did not wait for a replacement keyframe")
            return
        }

        mailbox.reset(generation: 2, sessionEpoch: 20, accepting: true)
        guard mailbox.submit(Frame(id: 10, keyframe: true), generation: 2, sessionEpoch: 20),
              mailbox.take(generation: 2, sessionEpoch: 20)?.element?.id == 10 else {
            failures.append("latest-frame mailbox did not restart pending-keyframe coverage")
            return
        }
        guard !mailbox.submit(Frame(id: 11, keyframe: true), generation: 2, sessionEpoch: 20) else {
            failures.append("latest-frame mailbox scheduled duplicate drain for pending keyframe")
            return
        }
        mailbox.requireKeyframe(generation: 2, sessionEpoch: 20)
        guard mailbox.finishDrain(generation: 2, sessionEpoch: 20),
              let pendingKeyframe = mailbox.take(generation: 2, sessionEpoch: 20),
              pendingKeyframe.element?.id == 11,
              pendingKeyframe.droppedCount == 0,
              !pendingKeyframe.requiresKeyframe,
              !mailbox.finishDrain(generation: 2, sessionEpoch: 20),
              mailbox.submit(Frame(id: 12, keyframe: false), generation: 2, sessionEpoch: 20),
              mailbox.take(generation: 2, sessionEpoch: 20)?.element?.id == 12 else {
            failures.append("latest-frame mailbox treated pending keyframe as still waiting for a keyframe")
            return
        }
    }

    private static func testEpoch(failures: inout [String]) {
        let gate = SessionEpochGate()
        do {
            let old = try gate.beginNextSession()
            let current = try gate.beginNextSession()
            if gate.accepts(old) || !gate.accepts(current) {
                failures.append("session epoch gate accepted stale data")
            }
        } catch {
            failures.append("session epoch creation failed: \(error)")
        }
    }

    private static func testRecovery(failures: inout [String]) {
        var recovery = ConnectionRecoveryController(
            heartbeatTimeoutNs: 100,
            backoff: ReconnectBackoff(initialDelayNs: 10, maximumDelayNs: 25)
        )
        recovery.didConnect(epoch: 1, nowNs: 1_000)
        guard recovery.heartbeatTimedOut(nowNs: 1_100),
              recovery.scheduleReconnect(nowNs: 2_000) == 20,
              recovery.scheduleReconnect(nowNs: 3_000) == 25 else {
            failures.append("heartbeat timeout or reconnect backoff is incorrect")
            return
        }
    }

    private static func testCodec(failures: inout [String]) {
        do {
            let decision = try CodecFallbackPolicy.select(
                preferred: .hevc,
                hostSupported: [.hevc, .h264],
                clientSupported: [.h264]
            )
            if decision.selected != .h264 || decision.reason != .preferredUnavailable {
                failures.append("codec fallback was not explicit")
            }
        } catch {
            failures.append("codec fallback failed: \(error)")
        }
    }

    private static func testTelemetry(failures: inout [String]) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibe-screen-reliability-\(UUID().uuidString).jsonl")
        do {
            let sink = try JSONLTelemetrySink(url: url)
            try sink.record(
                TelemetryEvent(
                    event: "self_test",
                    sessionEpoch: 1,
                    wallTime: "2026-08-04T00:00:00Z",
                    monotonicNs: 1
                )
            )
            try sink.close()
            let lines = try Data(contentsOf: url).split(separator: 0x0A)
            guard lines.count == 1 else {
                failures.append("telemetry output was not one JSONL record")
                try FileManager.default.removeItem(at: url)
                return
            }
            _ = try JSONDecoder().decode(TelemetryEvent.self, from: Data(lines[0]))
            try FileManager.default.removeItem(at: url)
        } catch {
            failures.append("JSONL telemetry failed: \(error)")
            do {
                if FileManager.default.fileExists(atPath: url.path) {
                    try FileManager.default.removeItem(at: url)
                }
            } catch {
                failures.append("telemetry cleanup failed: \(error)")
            }
        }
    }
}
