import XCTest
@testable import Telemachus

final class LatestFrameMailboxTests: XCTestCase {
    func testBlockedDrainRetainsOnlyLatestFrameAndSchedulesOnce() {
        let mailbox = LatestFrameMailbox<Int>(isKeyframe: { _ in true })
        mailbox.reset(generation: 7, sessionEpoch: 11, accepting: true)

        var scheduledDrainCount = 0
        for frame in 0..<10_000 {
            if mailbox.submit(frame, generation: 7, sessionEpoch: 11) {
                scheduledDrainCount += 1
            }
        }

        XCTAssertEqual(scheduledDrainCount, 1)
        let drain = mailbox.take(generation: 7, sessionEpoch: 11)
        XCTAssertEqual(drain?.element, 9_999)
        XCTAssertEqual(drain?.droppedCount, 9_999)
        XCTAssertFalse(mailbox.finishDrain(generation: 7, sessionEpoch: 11))
    }

    func testStaleGenerationAndEpochCannotOverwriteCurrentFrame() {
        let mailbox = LatestFrameMailbox<String>(isKeyframe: { _ in true })
        mailbox.reset(generation: 2, sessionEpoch: 20, accepting: true)

        XCTAssertTrue(mailbox.submit("current", generation: 2, sessionEpoch: 20))
        XCTAssertFalse(mailbox.submit("old generation", generation: 1, sessionEpoch: 20))
        XCTAssertFalse(mailbox.submit("old epoch", generation: 2, sessionEpoch: 19))

        let drain = mailbox.take(generation: 2, sessionEpoch: 20)
        XCTAssertEqual(drain?.element, "current")
        XCTAssertEqual(drain?.droppedCount, 0)
    }

    func testStaleDrainCannotClearCurrentDrainSchedule() {
        let mailbox = LatestFrameMailbox<String>(isKeyframe: { _ in true })
        mailbox.reset(generation: 1, sessionEpoch: 10, accepting: true)
        XCTAssertTrue(mailbox.submit("retired", generation: 1, sessionEpoch: 10))

        mailbox.reset(generation: 2, sessionEpoch: 20, accepting: true)
        XCTAssertTrue(mailbox.submit("current", generation: 2, sessionEpoch: 20))
        XCTAssertFalse(mailbox.finishDrain(generation: 1, sessionEpoch: 10))
        XCTAssertFalse(mailbox.submit("latest", generation: 2, sessionEpoch: 20))

        let drain = mailbox.take(generation: 2, sessionEpoch: 20)
        XCTAssertEqual(drain?.element, "latest")
        XCTAssertEqual(drain?.droppedCount, 1)
    }

    func testDependentFrameCannotReplacePendingKeyframe() {
        let mailbox = LatestFrameMailbox<String>(isKeyframe: { $0.hasPrefix("I") })
        mailbox.reset(generation: 1, sessionEpoch: 10, accepting: true)

        XCTAssertTrue(mailbox.submit("I-1", generation: 1, sessionEpoch: 10))
        XCTAssertFalse(mailbox.submit("P-2", generation: 1, sessionEpoch: 10))

        let drain = mailbox.take(generation: 1, sessionEpoch: 10)
        XCTAssertEqual(drain?.element, "I-1")
        XCTAssertEqual(drain?.droppedCount, 1)
        XCTAssertEqual(drain?.requiresKeyframe, false)
    }

    func testDependentFrameReplacementDropsPredictionChainAndRequestsKeyframe() {
        let mailbox = LatestFrameMailbox<String>(isKeyframe: { $0.hasPrefix("I") })
        mailbox.reset(generation: 1, sessionEpoch: 10, accepting: true)
        XCTAssertTrue(mailbox.submit("I-1", generation: 1, sessionEpoch: 10))
        XCTAssertEqual(mailbox.take(generation: 1, sessionEpoch: 10)?.element, "I-1")

        XCTAssertFalse(mailbox.submit("P-2", generation: 1, sessionEpoch: 10))
        XCTAssertFalse(mailbox.submit("P-3", generation: 1, sessionEpoch: 10))
        XCTAssertTrue(mailbox.finishDrain(generation: 1, sessionEpoch: 10))

        let drain = mailbox.take(generation: 1, sessionEpoch: 10)
        XCTAssertNil(drain?.element)
        XCTAssertEqual(drain?.droppedCount, 2)
        XCTAssertEqual(drain?.requiresKeyframe, true)
    }

    func testResetClearsPendingFrameAndDropAccounting() {
        let mailbox = LatestFrameMailbox<String>(isKeyframe: { _ in true })
        mailbox.reset(generation: 1, sessionEpoch: 10, accepting: true)
        XCTAssertTrue(mailbox.submit("old", generation: 1, sessionEpoch: 10))
        XCTAssertFalse(mailbox.submit("old latest", generation: 1, sessionEpoch: 10))

        mailbox.reset(generation: 2, sessionEpoch: 20, accepting: true)
        XCTAssertTrue(mailbox.submit("new", generation: 2, sessionEpoch: 20))
        let drain = mailbox.take(generation: 2, sessionEpoch: 20)
        XCTAssertEqual(drain?.element, "new")
        XCTAssertEqual(drain?.droppedCount, 0)
    }
}
