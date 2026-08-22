import XCTest

final class VibeScreenAppUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testConnectionFormIsUsable() {
        let app = XCUIApplication()
        app.launch()

        let pairingFieldExists = app.textFields["telemachus:// 配对链接"].waitForExistence(timeout: 10)
        let connectButtonExists = app.buttons["连接"].exists
        let defaultPortHintExists = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS %@", "未写端口时使用 54321")
        ).firstMatch.exists

        XCTAssertTrue(pairingFieldExists)
        XCTAssertTrue(connectButtonExists)
        XCTAssertTrue(defaultPortHintExists)
    }

    @MainActor
    func testInvalidPairingURLShowsActionableError() {
        let app = XCUIApplication()
        app.launch()

        let pairingField = app.textFields["telemachus:// 配对链接"]
        XCTAssertTrue(pairingField.waitForExistence(timeout: 10))
        pairingField.tap()
        pairingField.typeText("https://127.0.0.1")
        app.buttons["连接"].tap()

        XCTAssertTrue(app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS %@", "配对链接无效")
        ).firstMatch.waitForExistence(timeout: 5))
    }

    @MainActor
    func testAudioPlaybackSelfTestSchedulesPCMAndRestarts() {
        let app = XCUIApplication()
        app.launchArguments.append("--audio-playback-self-test")
        app.launch()

        let result = app.staticTexts["audio-playback-self-test-result"]
        XCTAssertTrue(result.waitForExistence(timeout: 10))
        XCTAssertTrue(result.label.contains("AUDIO_PLAYBACK_SELF_TEST=PASS"), result.label)
        XCTAssertTrue(result.label.contains("scheduled=9"), result.label)
        XCTAssertTrue(result.label.contains("overruns=3"), result.label)
        XCTAssertTrue(result.label.contains("stops=2"), result.label)
    }
}
