import Foundation
import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

private enum ControlledSenderError: Error {
    case unknownCall(Int)
    case timedOutWaitingForCallCount(Int)
}

private struct WireControlRecord: Sendable {
    let owner: ConnectionOwner
    let messageID: UInt64
    let payloadName: String
}

private actor ControlledControlSender {
    private var records: [WireControlRecord] = []
    private var activeSendCount = 0
    private var maximumActiveSendCount = 0
    private var releaseContinuations: [Int: CheckedContinuation<Void, Never>] = [:]
    private struct ArrivalWaiter {
        let id: UUID
        let count: Int
        let continuation: CheckedContinuation<Void, Error>
    }

    private var arrivalContinuations: [ArrivalWaiter] = []

    func send(owner: ConnectionOwner, frame: TransportFrame) async throws {
        let envelope = try EnvelopeCodec.deserialize(frame.payload)
        let callIndex = records.count
        records.append(WireControlRecord(
            owner: owner,
            messageID: envelope.messageID,
            payloadName: Self.payloadName(envelope)
        ))
        activeSendCount += 1
        maximumActiveSendCount = max(maximumActiveSendCount, activeSendCount)
        resumeSatisfiedArrivalContinuations()

        await withCheckedContinuation { continuation in
            releaseContinuations[callIndex] = continuation
        }
        activeSendCount -= 1
    }

    func waitUntilCallCount(_ count: Int) async throws {
        guard records.count < count else { return }
        let waiterID = UUID()
        try await withCheckedThrowingContinuation { continuation in
            arrivalContinuations.append(ArrivalWaiter(
                id: waiterID,
                count: count,
                continuation: continuation
            ))
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(10))
                await self?.expireArrivalWaiter(id: waiterID, count: count)
            }
        }
    }

    func release(call index: Int) throws {
        guard let continuation = releaseContinuations.removeValue(forKey: index) else {
            throw ControlledSenderError.unknownCall(index)
        }
        continuation.resume()
    }

    func snapshot() -> (records: [WireControlRecord], maximumActiveSendCount: Int) {
        (records, maximumActiveSendCount)
    }

    private func resumeSatisfiedArrivalContinuations() {
        let satisfied = arrivalContinuations.filter { records.count >= $0.count }
        arrivalContinuations.removeAll { records.count >= $0.count }
        for waiter in satisfied {
            waiter.continuation.resume()
        }
    }

    private func expireArrivalWaiter(id: UUID, count: Int) {
        guard let index = arrivalContinuations.firstIndex(where: { $0.id == id }) else { return }
        let waiter = arrivalContinuations.remove(at: index)
        waiter.continuation.resume(throwing: ControlledSenderError.timedOutWaitingForCallCount(count))
    }

    private static func payloadName(_ envelope: VSEnvelope) -> String {
        switch envelope.payload {
        case .listDisplaysRequest: "list-displays"
        case .startDisplayRequest: "start-display"
        case .ping: "ping"
        case .pong: "pong"
        case .videoConfigResult: "video-config-result"
        default: "other"
        }
    }
}

final class ControlOutboxTests: XCTestCase {
    @MainActor
    func testMixedProducersUseOneFIFOInWireOrder() async throws {
        let controlledSender = ControlledControlSender()
        let connectionOwner = ConnectionOwner()
        let sessionOwner = SessionOwner(connectionOwner: connectionOwner)
        let sessionID = Data([0x01])
        let outbox = ControlOutbox { owner, frame, _ in
            try await controlledSender.send(owner: owner, frame: frame)
        }
        outbox.activate(owner: sessionOwner)

        let tickets = try [
            outbox.enqueue(owner: sessionOwner) { factory in
                factory.listDisplays(sessionID: sessionID, sessionEpoch: 7)
            },
            outbox.enqueue(owner: sessionOwner) { factory in
                factory.startExistingDisplay(
                    displayID: "display-a",
                    sessionID: sessionID,
                    sessionEpoch: 7
                )
            },
            outbox.enqueue(owner: sessionOwner) { factory in
                factory.ping(sequence: 1, sessionID: sessionID, sessionEpoch: 7)
            },
            outbox.enqueue(owner: sessionOwner) { factory in
                factory.pong(
                    sequence: 2,
                    correlationID: 3,
                    sessionID: sessionID,
                    sessionEpoch: 7
                )
            },
            outbox.enqueue(owner: sessionOwner) { factory in
                var result = VSVideoConfigResult()
                result.streamID = 41
                result.configEpoch = 9
                result.accepted = true
                return factory.videoConfigResult(
                    result,
                    sessionID: sessionID,
                    sessionEpoch: 7
                )
            },
            outbox.enqueue(owner: sessionOwner) { factory in
                factory.startExistingDisplay(
                    displayID: "display-b",
                    sessionID: sessionID,
                    sessionEpoch: 7
                )
            },
        ]

        XCTAssertEqual(tickets.map(\.messageID), Array(1...6).map(UInt64.init))

        // Every send is held until the test releases it. A concurrent drain
        // would therefore make the controlled sender's active count exceed one.
        for callCount in 1...tickets.count {
            try await controlledSender.waitUntilCallCount(callCount)
            try await controlledSender.release(call: callCount - 1)
        }
        for ticket in tickets {
            let completedMessageID = try await ticket.wait()
            XCTAssertEqual(completedMessageID, ticket.messageID)
        }

        let snapshot = await controlledSender.snapshot()
        XCTAssertEqual(snapshot.maximumActiveSendCount, 1)
        XCTAssertEqual(snapshot.records.map(\.messageID), Array(1...6).map(UInt64.init))
        XCTAssertEqual(snapshot.records.map(\.owner), Array(repeating: connectionOwner, count: 6))
        XCTAssertEqual(snapshot.records.map(\.payloadName), [
            "list-displays",
            "start-display",
            "ping",
            "pong",
            "video-config-result",
            "start-display",
        ])
    }

    @MainActor
    func testMixedProducersStressMaintainsFIFOAcross512Messages() async throws {
        let messageCount = 512
        let controlledSender = ControlledControlSender()
        let connectionOwner = ConnectionOwner()
        let sessionOwner = SessionOwner(connectionOwner: connectionOwner)
        let sessionID = Data([0x03])
        let outbox = ControlOutbox { owner, frame, _ in
            try await controlledSender.send(owner: owner, frame: frame)
        }
        outbox.activate(owner: sessionOwner)

        var tickets: [ControlSendTicket] = []
        tickets.reserveCapacity(messageCount)
        for index in 0..<messageCount {
            let sequence = UInt64(index + 1)
            let ticket: ControlSendTicket
            switch index % 4 {
            case 0:
                ticket = try outbox.enqueue(owner: sessionOwner) { factory in
                    factory.startExistingDisplay(
                        displayID: "display-\(index % 8)",
                        sessionID: sessionID,
                        sessionEpoch: 11
                    )
                }
            case 1:
                ticket = try outbox.enqueue(owner: sessionOwner) { factory in
                    factory.ping(sequence: sequence, sessionID: sessionID, sessionEpoch: 11)
                }
            case 2:
                ticket = try outbox.enqueue(owner: sessionOwner) { factory in
                    factory.pong(
                        sequence: sequence,
                        correlationID: sequence - 1,
                        sessionID: sessionID,
                        sessionEpoch: 11
                    )
                }
            default:
                ticket = try outbox.enqueue(owner: sessionOwner) { factory in
                    var result = VSVideoConfigResult()
                    result.streamID = UInt64(index % 8 + 1)
                    result.configEpoch = sequence
                    result.accepted = true
                    return factory.videoConfigResult(
                        result,
                        sessionID: sessionID,
                        sessionEpoch: 11
                    )
                }
            }
            tickets.append(ticket)
        }

        let expectedMessageIDs = (1...messageCount).map(UInt64.init)
        XCTAssertEqual(tickets.map(\.messageID), expectedMessageIDs)

        // Each fake send remains suspended. If the outbox starts a second
        // drain, later IDs can arrive and finish out of order; the gate makes
        // that bug deterministic instead of relying on scheduler timing.
        for callCount in 1...messageCount {
            try await controlledSender.waitUntilCallCount(callCount)
            try await controlledSender.release(call: callCount - 1)
        }
        for ticket in tickets {
            let completedMessageID = try await ticket.wait()
            XCTAssertEqual(completedMessageID, ticket.messageID)
        }

        let snapshot = await controlledSender.snapshot()
        XCTAssertEqual(snapshot.maximumActiveSendCount, 1)
        XCTAssertEqual(snapshot.records.map(\.messageID), expectedMessageIDs)
        XCTAssertEqual(
            snapshot.records.map(\.owner),
            Array(repeating: connectionOwner, count: messageCount)
        )
    }

    @MainActor
    func testRotationDropsOldQueueAndLateCompletionCannotPolluteNewOwner() async throws {
        let controlledSender = ControlledControlSender()
        let connectionOwner = ConnectionOwner()
        let ownerA = SessionOwner(connectionOwner: connectionOwner)
        let ownerB = SessionOwner(connectionOwner: connectionOwner)
        let sessionID = Data([0x02])
        let outbox = ControlOutbox { owner, frame, _ in
            try await controlledSender.send(owner: owner, frame: frame)
        }
        outbox.activate(owner: ownerA)

        let inFlightA = try outbox.enqueue(owner: ownerA) { factory in
            factory.ping(sequence: 1, sessionID: sessionID, sessionEpoch: 1)
        }
        let pendingA = try outbox.enqueue(owner: ownerA) { factory in
            factory.startExistingDisplay(
                displayID: "old-session-display",
                sessionID: sessionID,
                sessionEpoch: 1
            )
        }
        try await controlledSender.waitUntilCallCount(1)

        outbox.activate(owner: ownerB)
        let firstB = try outbox.enqueue(owner: ownerB) { factory in
            factory.ping(sequence: 1, sessionID: sessionID, sessionEpoch: 2)
        }
        XCTAssertEqual(firstB.messageID, 1)

        // The old connection send cannot be cancelled synchronously. The new
        // activation must remain queued until that await returns, even though
        // both logical sessions share one ConnectionOwner.
        var beforeLateA = await controlledSender.snapshot()
        XCTAssertEqual(beforeLateA.records.map(\.messageID), [1])
        try await controlledSender.release(call: 0)
        try await controlledSender.waitUntilCallCount(2)
        try await controlledSender.release(call: 1)
        let firstBCompletedMessageID = try await firstB.wait()
        XCTAssertEqual(firstBCompletedMessageID, 1)

        await assertSuperseded(inFlightA)
        await assertSuperseded(pendingA)

        let secondB = try outbox.enqueue(owner: ownerB) { factory in
            factory.listDisplays(sessionID: sessionID, sessionEpoch: 2)
        }
        XCTAssertEqual(secondB.messageID, 2)
        try await controlledSender.waitUntilCallCount(3)
        try await controlledSender.release(call: 2)
        let secondBCompletedMessageID = try await secondB.wait()
        XCTAssertEqual(secondBCompletedMessageID, 2)

        beforeLateA = await controlledSender.snapshot()
        XCTAssertEqual(beforeLateA.records.map(\.owner), [
            connectionOwner,
            connectionOwner,
            connectionOwner,
        ])
        XCTAssertEqual(beforeLateA.records.map(\.messageID), [1, 1, 2])
        XCTAssertFalse(beforeLateA.records.contains { $0.payloadName == "start-display" })
        XCTAssertEqual(beforeLateA.maximumActiveSendCount, 1)
    }

    @MainActor
    private func assertSuperseded(
        _ ticket: ControlSendTicket,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            _ = try await ticket.wait()
            XCTFail("expected superseded ticket", file: file, line: line)
        } catch let error as ControlOutboxError {
            guard case .superseded = error else {
                XCTFail("unexpected outbox error: \(error)", file: file, line: line)
                return
            }
        } catch {
            XCTFail("unexpected error: \(error)", file: file, line: line)
        }
    }
}
