import XCTest
@testable import Telemachus

final class WebRTCDataChannelBackpressurePolicyTests: XCTestCase {
    func testAdmissionIsBoundedWithoutOverflow() {
        XCTAssertTrue(WebRTCDataChannelBackpressurePolicy.canAdmit(
            bufferedAmount: 4, payloadBytes: 6, maximumBufferedAmount: 10
        ))
        XCTAssertFalse(WebRTCDataChannelBackpressurePolicy.canAdmit(
            bufferedAmount: 5, payloadBytes: 6, maximumBufferedAmount: 10
        ))
        XCTAssertFalse(WebRTCDataChannelBackpressurePolicy.canAdmit(
            bufferedAmount: UInt64.max, payloadBytes: 1, maximumBufferedAmount: 10
        ))
    }

    func testCompletionWaitsUntilSDKBufferReturnsToBaseline() {
        XCTAssertFalse(WebRTCDataChannelBackpressurePolicy.hasDrained(
            currentBufferedAmount: 101, baselineBufferedAmount: 100
        ))
        XCTAssertTrue(WebRTCDataChannelBackpressurePolicy.hasDrained(
            currentBufferedAmount: 100, baselineBufferedAmount: 100
        ))
        XCTAssertTrue(WebRTCDataChannelBackpressurePolicy.hasDrained(
            currentBufferedAmount: 0, baselineBufferedAmount: 100
        ))
    }
}
