import XCTest
@testable import Telemachus

final class ProtocolV1TouchAggregatorTests: XCTestCase {
    func testTwoPointerMoveDispatchesOnlyAfterBothPointersUpdate() {
        var aggregator = ProtocolV1TouchAggregator()
        XCTAssertEqual(
            aggregator.handle(pointerID: 1, x: 0.2, y: 0.3, phase: .began)?.pointerCount,
            1
        )
        XCTAssertEqual(
            aggregator.handle(pointerID: 2, x: 0.7, y: 0.3, phase: .began)?.pointerCount,
            2
        )

        for y: Float in [0.4, 0.5, 0.6] {
            XCTAssertNil(aggregator.handle(
                pointerID: 1,
                x: 0.2,
                y: y,
                phase: .changed
            ))
        }
        let move = aggregator.handle(
            pointerID: 2,
            x: 0.7,
            y: 0.5,
            phase: .changed
        )

        XCTAssertEqual(move?.action, 1)
        XCTAssertEqual(move?.pointerCount, 2)
        XCTAssertEqual(move?.x1, 0.2)
        XCTAssertEqual(move?.y1, 0.6)
        XCTAssertEqual(move?.x2, 0.7)
        XCTAssertEqual(move?.y2, 0.5)
    }

    func testLifecycleChangeClearsPartialMoveBarrier() {
        var aggregator = ProtocolV1TouchAggregator()
        _ = aggregator.handle(pointerID: 1, x: 0.2, y: 0.3, phase: .began)
        _ = aggregator.handle(pointerID: 2, x: 0.7, y: 0.3, phase: .began)
        XCTAssertNil(aggregator.handle(
            pointerID: 1,
            x: 0.2,
            y: 0.4,
            phase: .changed
        ))

        XCTAssertEqual(
            aggregator.handle(pointerID: 2, x: 0.7, y: 0.3, phase: .ended)?.pointerCount,
            2
        )
        let remaining = aggregator.handle(
            pointerID: 1,
            x: 0.2,
            y: 0.6,
            phase: .changed
        )
        XCTAssertEqual(remaining?.pointerCount, 1)
        XCTAssertEqual(remaining?.y1, 0.6)
    }

    func testChangedEventCannotCreatePointerWithoutBegan() {
        var aggregator = ProtocolV1TouchAggregator()
        XCTAssertNil(aggregator.handle(
            pointerID: 1,
            x: 0.5,
            y: 0.5,
            phase: .changed
        ))
    }
}
