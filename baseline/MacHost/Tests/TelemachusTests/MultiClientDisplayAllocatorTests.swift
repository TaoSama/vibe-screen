import Foundation
import XCTest
@testable import Telemachus

final class MultiClientDisplayAllocatorTests: XCTestCase {
    func testAllocatorIsolatesTwoClientsDistinctStreamsAndEpochs() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 2, maximumStreamsPerClient: 2)
        let first = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = MultiClientSessionKey(sessionID: Data([0x02]), epoch: 1)
        let firstNextEpoch = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 2)

        try allocator.register(first)
        try allocator.register(second)

        let firstMainStream = try allocator.allocateStream(for: "first-main", in: first)
        let firstAuxStream = try allocator.allocateStream(for: "first-aux", in: first)
        let secondMainStream = try allocator.allocateStream(for: "second-main", in: second)

        XCTAssertEqual(firstMainStream, 1)
        XCTAssertEqual(firstAuxStream, 2)
        XCTAssertEqual(secondMainStream, 1)
        XCTAssertEqual(allocator.binding(streamID: firstMainStream, in: first)?.displayID, "first-main")
        XCTAssertEqual(allocator.binding(streamID: secondMainStream, in: second)?.displayID, "second-main")

        XCTAssertThrowsError(try allocator.allocateStream(for: "first-over-limit", in: first)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .streamLimitReached(2))
        }
        XCTAssertThrowsError(try allocator.register(MultiClientSessionKey(sessionID: Data([0x03]), epoch: 1))) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .clientLimitReached(2))
        }

        try allocator.register(firstNextEpoch)

        XCTAssertNil(allocator.binding(streamID: firstMainStream, in: first))
        XCTAssertEqual(allocator.binding(streamID: secondMainStream, in: second)?.displayID, "second-main")
        XCTAssertEqual(try allocator.allocateStream(for: "first-main", in: firstNextEpoch), 1)
        XCTAssertThrowsError(try allocator.register(first)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidSession)
        }
    }

    func testAllocatorRejectsDuplicateDisplayAcrossClientsUntilReleased() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 2, maximumStreamsPerClient: 2)
        let first = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = MultiClientSessionKey(sessionID: Data([0x02]), epoch: 1)

        try allocator.register(first)
        try allocator.register(second)

        let firstStream = try allocator.allocateStream(for: "shared-display", in: first)
        XCTAssertThrowsError(try allocator.allocateStream(for: "shared-display", in: second)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .duplicateDisplay("shared-display"))
        }

        XCTAssertTrue(allocator.release(streamID: firstStream, in: first))
        XCTAssertEqual(try allocator.allocateStream(for: "shared-display", in: second), 1)
    }

    func testRebindUpdatesGlobalDisplayOwner() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 2, maximumStreamsPerClient: 1)
        let first = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = MultiClientSessionKey(sessionID: Data([0x02]), epoch: 1)

        try allocator.register(first)
        try allocator.register(second)
        let streamID = try allocator.allocateStream(for: "first-display", in: first)

        try allocator.rebind(streamID: streamID, toDisplayID: "first-other-display", in: first)

        XCTAssertEqual(try allocator.allocateStream(for: "first-display", in: second), 1)
        XCTAssertThrowsError(try allocator.allocateStream(for: "first-other-display", in: second)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .duplicateDisplay("first-other-display"))
        }
    }

    func testReleaseIsScopedToExactClientEpochAndStream() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 2, maximumStreamsPerClient: 2)
        let first = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = MultiClientSessionKey(sessionID: Data([0x02]), epoch: 1)
        let staleFirst = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 0)

        try allocator.register(first)
        try allocator.register(second)
        let firstStream = try allocator.allocateStream(for: "first-display", in: first)
        let secondStream = try allocator.allocateStream(for: "second-display", in: second)
        let unallocatedFirstStream = firstStream + 1

        XCTAssertFalse(allocator.release(streamID: firstStream, in: staleFirst))
        XCTAssertFalse(allocator.release(streamID: unallocatedFirstStream, in: first))
        XCTAssertEqual(allocator.binding(streamID: firstStream, in: first)?.displayID, "first-display")
        XCTAssertEqual(allocator.binding(streamID: secondStream, in: second)?.displayID, "second-display")

        XCTAssertTrue(allocator.release(streamID: firstStream, in: first))
        XCTAssertEqual(try allocator.allocateStream(for: "first-display", in: second), 2)
        XCTAssertEqual(allocator.binding(streamID: secondStream, in: second)?.displayID, "second-display")
    }

    func testAllocatorMergesReservedStreamIDsAndBoundsSearch() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 1, maximumStreamsPerClient: 3)
        let key = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)

        try allocator.register(key, reservedStreamIDs: [2])
        try allocator.register(key, reservedStreamIDs: [3])

        XCTAssertEqual(try allocator.allocateStream(for: "main", in: key), 1)
        XCTAssertEqual(try allocator.allocateStream(for: "aux", in: key), 4)
        XCTAssertThrowsError(try allocator.bind(
            MultiClientDisplayStreamBinding(displayID: "reserved-two", streamID: 2),
            to: key
        )) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }
        XCTAssertThrowsError(try allocator.bind(
            MultiClientDisplayStreamBinding(displayID: "reserved-three", streamID: 3),
            to: key
        )) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }

        let prefixed = MultiClientDisplayAllocator(maximumClients: 1, maximumStreamsPerClient: 1)
        try prefixed.register(key, reservedStreamIDs: [1, 2, 3, 4])
        XCTAssertEqual(try prefixed.allocateStream(for: "after-reserved-prefix", in: key), 5)

        let exhausted = MultiClientDisplayAllocator(maximumClients: 1, maximumStreamsPerClient: 1)
        try exhausted.register(key, reservedStreamIDs: [UInt64.max])
        try exhausted.bind(
            MultiClientDisplayStreamBinding(displayID: "last-bound", streamID: UInt64.max - 1),
            to: key
        )
        XCTAssertTrue(exhausted.release(streamID: UInt64.max - 1, in: key))
        XCTAssertThrowsError(try exhausted.allocateStream(for: "blocked", in: key)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .streamLimitReached(1))
        }
    }

    func testAllocatorRejectsDuplicateReservedAndMalformedBindings() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 1, maximumStreamsPerClient: 3)
        let key = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)

        XCTAssertThrowsError(try allocator.register(MultiClientSessionKey(sessionID: Data(), epoch: 1))) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidSession)
        }
        XCTAssertThrowsError(try allocator.register(MultiClientSessionKey(sessionID: Data([0x09]), epoch: 0))) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidSession)
        }

        try allocator.register(key, reservedStreamIDs: [2])
        XCTAssertThrowsError(try allocator.allocateStream(for: "", in: key)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }

        XCTAssertEqual(try allocator.allocateStream(for: "main", in: key), 1)
        XCTAssertEqual(try allocator.allocateStream(for: "aux", in: key), 3)
        XCTAssertThrowsError(try allocator.bind(
            MultiClientDisplayStreamBinding(displayID: "main", streamID: 3),
            to: key
        )) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .duplicateDisplay("main"))
        }
        XCTAssertThrowsError(try allocator.bind(
            MultiClientDisplayStreamBinding(displayID: "reserved", streamID: 2),
            to: key
        )) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }
        XCTAssertThrowsError(try allocator.reserveStreamIDs([0], in: key)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }
        XCTAssertThrowsError(try allocator.reserveStreamIDs([1], in: key)) { error in
            XCTAssertEqual(error as? MultiClientDisplayAllocatorError, .invalidBinding)
        }
    }

    func testDisconnectReleasesOnlyTheExactClientEpoch() throws {
        let allocator = MultiClientDisplayAllocator(maximumClients: 2, maximumStreamsPerClient: 1)
        let first = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 1)
        let second = MultiClientSessionKey(sessionID: Data([0x02]), epoch: 1)
        let staleFirst = MultiClientSessionKey(sessionID: Data([0x01]), epoch: 0)

        try allocator.register(first)
        try allocator.register(second)
        _ = try allocator.allocateStream(for: "first", in: first)
        _ = try allocator.allocateStream(for: "second", in: second)

        allocator.disconnect(staleFirst)
        XCTAssertEqual(allocator.activeClientCount, 2)

        allocator.disconnect(first)
        XCTAssertNil(allocator.binding(streamID: 1, in: first))
        XCTAssertEqual(allocator.binding(streamID: 1, in: second)?.displayID, "second")
        XCTAssertEqual(allocator.activeClientCount, 1)
    }
}
