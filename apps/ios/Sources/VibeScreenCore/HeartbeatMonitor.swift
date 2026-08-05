import Foundation

public struct HeartbeatPing: Equatable, Sendable {
    public let owner: SessionOwner
    public let sequence: UInt64
    public let messageID: UInt64
    public let deadlineNanoseconds: UInt64
}

public enum HeartbeatStatus: Equatable, Sendable {
    case alive(missed: Int)
    case timedOut
}

public enum HeartbeatMonitorError: Error, Equatable {
    case inactive
    case ownerMismatch
    case timedOut
    case unknownSequence(UInt64)
    case correlationMismatch(expected: UInt64, received: UInt64)
    case nonMonotonicMessageID
}

/// Tracks heartbeat liveness for exactly one negotiated session generation.
public struct HeartbeatMonitor: Sendable {
    public static let defaultIntervalNanoseconds: UInt64 = 1_000_000_000
    public static let maximumMissed = 3

    public private(set) var owner: SessionOwner?
    public private(set) var intervalNanoseconds: UInt64

    private let nowNanoseconds: @Sendable () -> UInt64
    private var nextSequence: UInt64 = 1
    private var lastMessageID: UInt64 = 0
    private var lastAcknowledgedSequence: UInt64 = 0
    private var pending: [UInt64: HeartbeatPing] = [:]

    public init(
        owner: SessionOwner? = nil,
        intervalNanoseconds: UInt64 = Self.defaultIntervalNanoseconds,
        nowNanoseconds: @escaping @Sendable () -> UInt64
    ) {
        self.owner = owner
        self.intervalNanoseconds = max(intervalNanoseconds, 1)
        self.nowNanoseconds = nowNanoseconds
    }

    public mutating func reset(
        to owner: SessionOwner? = nil,
        intervalNanoseconds: UInt64? = nil
    ) {
        self.owner = owner
        if let intervalNanoseconds {
            self.intervalNanoseconds = max(intervalNanoseconds, 1)
        }
        nextSequence = 1
        lastMessageID = 0
        lastAcknowledgedSequence = 0
        pending.removeAll(keepingCapacity: true)
    }

    public mutating func issuePing(owner expectedOwner: SessionOwner, messageID: UInt64) throws -> HeartbeatPing {
        try requireOwner(expectedOwner)
        let now = nowNanoseconds()
        guard status(at: now) != .timedOut else {
            throw HeartbeatMonitorError.timedOut
        }
        guard messageID > lastMessageID else {
            throw HeartbeatMonitorError.nonMonotonicMessageID
        }

        let deadline = now.addingReportingOverflow(intervalNanoseconds)
        let ping = HeartbeatPing(
            owner: expectedOwner,
            sequence: nextSequence,
            messageID: messageID,
            deadlineNanoseconds: deadline.overflow ? .max : deadline.partialValue
        )
        pending[ping.sequence] = ping
        nextSequence &+= 1
        lastMessageID = messageID
        return ping
    }

    public mutating func observePong(
        owner expectedOwner: SessionOwner,
        sequence: UInt64,
        correlationID: UInt64
    ) throws {
        try requireOwner(expectedOwner)
        guard sequence > lastAcknowledgedSequence, let ping = pending[sequence] else {
            throw HeartbeatMonitorError.unknownSequence(sequence)
        }
        guard correlationID == ping.messageID else {
            throw HeartbeatMonitorError.correlationMismatch(
                expected: ping.messageID,
                received: correlationID
            )
        }

        lastAcknowledgedSequence = sequence
        pending = pending.filter { $0.key > sequence }
    }

    public func status(owner expectedOwner: SessionOwner) throws -> HeartbeatStatus {
        try requireOwner(expectedOwner)
        return status(at: nowNanoseconds())
    }

    private func status(at now: UInt64) -> HeartbeatStatus {
        let missed = pending.values.reduce(into: 0) { count, ping in
            if now >= ping.deadlineNanoseconds { count += 1 }
        }
        return missed >= Self.maximumMissed ? .timedOut : .alive(missed: missed)
    }

    private func requireOwner(_ expectedOwner: SessionOwner) throws {
        guard let owner else { throw HeartbeatMonitorError.inactive }
        guard owner == expectedOwner else { throw HeartbeatMonitorError.ownerMismatch }
    }
}
