import XCTest

final class VibeScreenAppUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testConnectionFormIsUsable() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.textFields["主机名或 IP"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.textFields["端口"].exists)
        XCTAssertTrue(app.buttons["连接"].exists)
    }
}
