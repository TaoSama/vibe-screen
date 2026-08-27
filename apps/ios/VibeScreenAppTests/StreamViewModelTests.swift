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
        app.launchEnvironment["AUDIO_PLAYBACK_SELF_TEST"] = "1"
        app.launch()

        let result = app.staticTexts["audio-playback-self-test-result"]
        XCTAssertTrue(result.waitForExistence(timeout: 30))
        XCTAssertEqual(result.label, "AUDIO_PLAYBACK_SELF_TEST=RUNNING")

        let start = app.buttons["audio-playback-self-test-start"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        start.tap()

        let terminalResult = XCTNSPredicateExpectation(
            predicate: NSPredicate(
                format: "label CONTAINS %@ OR label CONTAINS %@",
                "AUDIO_PLAYBACK_SELF_TEST=PASS",
                "AUDIO_PLAYBACK_SELF_TEST=FAIL"
            ),
            object: result
        )
        let waitResult = XCTWaiter.wait(for: [terminalResult], timeout: 30)
        XCTAssertEqual(waitResult, .completed, result.label)
        XCTAssertTrue(result.label.contains("AUDIO_PLAYBACK_SELF_TEST=PASS"), result.label)
        let counters = Self.audioPlaybackCounters(from: result.label)
        XCTAssertGreaterThanOrEqual(counters["scheduled", default: 0], 9, result.label)
        XCTAssertGreaterThanOrEqual(counters["played", default: 0], 9, result.label)
        XCTAssertEqual(counters["queued"], 0, result.label)
        XCTAssertGreaterThanOrEqual(counters["queue_empty", default: 0], 2, result.label)
        XCTAssertGreaterThanOrEqual(counters["overruns", default: 0], 1, result.label)
        XCTAssertGreaterThanOrEqual(counters["stops", default: 0], 2, result.label)
        XCTAssertNotNil(counters["late_completions"], result.label)
    }

    private static func audioPlaybackCounters(from label: String) -> [String: Int] {
        label.split(separator: " ").reduce(into: [:]) { counters, field in
            let parts = field.split(separator: "=", maxSplits: 1)
            guard parts.count == 2, let value = Int(parts[1]) else { return }
            counters[String(parts[0])] = value
        }
    }
}
