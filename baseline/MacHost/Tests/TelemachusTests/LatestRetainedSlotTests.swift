import XCTest
@testable import Telemachus

final class LatestRetainedSlotTests: XCTestCase {
    private final class Payload {
        let value: Int

        init(_ value: Int) {
            self.value = value
        }
    }

    func testStoresOnlyLatestValue() {
        let slot = LatestRetainedSlot<Payload>()

        for value in 0..<10_000 {
            slot.store(Payload(value))
        }

        XCTAssertEqual(slot.retainedCount, 1)
        XCTAssertEqual(slot.latest()?.value.value, 9_999)
    }

    func testClearDropsRetainedValue() {
        let slot = LatestRetainedSlot<Payload>()
        slot.store(Payload(1))

        slot.clear()

        XCTAssertNil(slot.latest())
        XCTAssertEqual(slot.retainedCount, 0)
    }

    func testConcurrentStoresRemainBounded() {
        let slot = LatestRetainedSlot<Payload>()
        let group = DispatchGroup()

        for worker in 0..<8 {
            group.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                for value in 0..<1_000 {
                    slot.store(Payload(worker * 1_000 + value))
                }
                group.leave()
            }
        }

        XCTAssertEqual(group.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(slot.retainedCount, 1)
        XCTAssertNotNil(slot.latest())
    }
}
