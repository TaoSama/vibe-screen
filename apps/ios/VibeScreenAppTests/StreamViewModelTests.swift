import XCTest

final class VibeScreenAppUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testConnectionFormIsUsable() {
        let app = XCUIApplication()
        app.launch()

        let hostFieldExists = app.textFields["主机名或 IP"].waitForExistence(timeout: 10)
        let portFieldExists = app.textFields["端口"].exists
        let connectButtonExists = app.buttons["连接"].exists

        XCTAssertTrue(hostFieldExists)
        XCTAssertTrue(portFieldExists)
        XCTAssertTrue(connectButtonExists)
    }
}
