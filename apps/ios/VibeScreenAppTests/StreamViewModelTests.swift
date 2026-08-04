import XCTest
@testable import VibeScreen

final class StreamViewModelTests: XCTestCase {
    @MainActor
    func testInitialStateAndInvalidPortValidation() async {
        let model = StreamViewModel()

        XCTAssertFalse(model.isConnecting)
        XCTAssertFalse(model.isStreaming)
        XCTAssertNil(model.errorMessage)

        await model.connect(host: "127.0.0.1", port: 0)

        XCTAssertFalse(model.isConnecting)
        XCTAssertFalse(model.isStreaming)
        XCTAssertEqual(model.errorMessage, "端口必须在 1–65535 之间")
    }
}
