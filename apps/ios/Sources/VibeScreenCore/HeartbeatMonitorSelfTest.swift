import Foundation

private enum HeartbeatMonitorSelfTestError: Error {
    case failed(String)
}

private final class HeartbeatTestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value: UInt64 = 0

    func now() -> UInt64 {
        lock.withLock { value }
    }

    func advance(by nanoseconds: UInt64) {
        lock.withLock { value &+= nanoseconds }
    }
}

/// Deterministic coverage used by the release core self-test executable.
public func runHeartbeatMonitorSelfTests() throws {
    let interval: UInt64 = 100
    let clock = HeartbeatTestClock()
    let connection = ConnectionOwner()
    let firstOwner = SessionOwner(connectionOwner: connection)
    let replacementOwner = SessionOwner(connectionOwner: connection)
    var monitor = HeartbeatMonitor(
        owner: firstOwner,
        intervalNanoseconds: interval,
        nowNanoseconds: { clock.now() }
    )

    let first = try monitor.issuePing(owner: firstOwner, messageID: 10)
    clock.advance(by: interval)
    _ = try monitor.issuePing(owner: firstOwner, messageID: 11)
    clock.advance(by: interval)
    let recovery = try monitor.issuePing(owner: firstOwner, messageID: 12)
    guard try monitor.status(owner: firstOwner) == .alive(missed: 2) else {
        throw HeartbeatMonitorSelfTestError.failed("budget minus one was not alive")
    }

    try monitor.observePong(
        owner: firstOwner,
        sequence: recovery.sequence,
        correlationID: recovery.messageID
    )
    guard try monitor.status(owner: firstOwner) == .alive(missed: 0) else {
        throw HeartbeatMonitorSelfTestError.failed("valid pong did not recover heartbeat")
    }
    do {
        try monitor.observePong(
            owner: firstOwner,
            sequence: first.sequence,
            correlationID: first.messageID
        )
        throw HeartbeatMonitorSelfTestError.failed("late pong was accepted")
    } catch HeartbeatMonitorError.unknownSequence { }

    monitor.reset(to: firstOwner)
    for messageID in 20 ... 22 {
        _ = try monitor.issuePing(owner: firstOwner, messageID: UInt64(messageID))
        clock.advance(by: interval)
    }
    guard try monitor.status(owner: firstOwner) == .timedOut else {
        throw HeartbeatMonitorSelfTestError.failed("miss budget boundary did not time out")
    }
    do {
        _ = try monitor.issuePing(owner: firstOwner, messageID: 23)
        throw HeartbeatMonitorSelfTestError.failed("timed-out monitor issued another ping")
    } catch HeartbeatMonitorError.timedOut { }

    monitor.reset(to: replacementOwner)
    let replacementPing = try monitor.issuePing(owner: replacementOwner, messageID: 1)
    do {
        try monitor.observePong(
            owner: firstOwner,
            sequence: replacementPing.sequence,
            correlationID: replacementPing.messageID
        )
        throw HeartbeatMonitorSelfTestError.failed("old owner pong crossed reset")
    } catch HeartbeatMonitorError.ownerMismatch { }
    guard try monitor.status(owner: replacementOwner) == .alive(missed: 0) else {
        throw HeartbeatMonitorSelfTestError.failed("late old-owner pong mutated replacement")
    }

    do {
        try monitor.observePong(
            owner: replacementOwner,
            sequence: replacementPing.sequence,
            correlationID: replacementPing.messageID + 1
        )
        throw HeartbeatMonitorSelfTestError.failed("wrong pong correlation was accepted")
    } catch HeartbeatMonitorError.correlationMismatch { }
    try monitor.observePong(
        owner: replacementOwner,
        sequence: replacementPing.sequence,
        correlationID: replacementPing.messageID
    )
}
