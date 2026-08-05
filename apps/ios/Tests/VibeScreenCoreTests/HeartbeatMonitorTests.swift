import Foundation
import XCTest
@testable import VibeScreenCore

private final class ManualClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value: UInt64 = 0

    func now() -> UInt64 { lock.withLock { value } }
    func advance(_ delta: UInt64) { lock.withLock { value += delta } }
}

final class HeartbeatMonitorTests: XCTestCase {
    func testImmediatePongIsAcceptedBeforeAnySendCompletion() throws {
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        let clock = ManualClock()
        var monitor = HeartbeatMonitor(
            owner: owner,
            intervalNanoseconds: 10,
            nowNanoseconds: { clock.now() }
        )

        let ping = try monitor.issuePing(owner: owner, messageID: 41)
        try monitor.observePong(owner: owner, sequence: ping.sequence, correlationID: 41)
        XCTAssertEqual(try monitor.status(owner: owner), .alive(missed: 0))
    }

    func testMissBudgetTimesOutExactlyAtBoundary() throws {
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        let clock = ManualClock()
        var monitor = HeartbeatMonitor(
            owner: owner,
            intervalNanoseconds: 10,
            nowNanoseconds: { clock.now() }
        )

        for messageID in 1 ... HeartbeatMonitor.maximumMissed - 1 {
            _ = try monitor.issuePing(owner: owner, messageID: UInt64(messageID))
            clock.advance(10)
        }
        XCTAssertEqual(
            try monitor.status(owner: owner),
            .alive(missed: HeartbeatMonitor.maximumMissed - 1)
        )

        _ = try monitor.issuePing(owner: owner, messageID: UInt64(HeartbeatMonitor.maximumMissed))
        clock.advance(10)
        XCTAssertEqual(try monitor.status(owner: owner), .timedOut)
    }

    func testRotationRejectsLatePongAndLeavesReplacementAlive() throws {
        let connection = ConnectionOwner()
        let oldOwner = SessionOwner(connectionOwner: connection)
        let currentOwner = SessionOwner(connectionOwner: connection)
        let clock = ManualClock()
        var monitor = HeartbeatMonitor(
            owner: oldOwner,
            intervalNanoseconds: 10,
            nowNanoseconds: { clock.now() }
        )
        let oldPing = try monitor.issuePing(owner: oldOwner, messageID: 1)
        monitor.reset(to: currentOwner)
        let currentPing = try monitor.issuePing(owner: currentOwner, messageID: 1)

        XCTAssertThrowsError(try monitor.observePong(
            owner: oldOwner,
            sequence: oldPing.sequence,
            correlationID: oldPing.messageID
        )) { XCTAssertEqual($0 as? HeartbeatMonitorError, .ownerMismatch) }
        XCTAssertEqual(try monitor.status(owner: currentOwner), .alive(missed: 0))
        try monitor.observePong(
            owner: currentOwner,
            sequence: currentPing.sequence,
            correlationID: currentPing.messageID
        )
    }
}
