import XCTest
@testable import Telemachus

final class HostCommandLineTests: XCTestCase {
    func testUnknownDoubleDashSelfTestFlagIsRejected() {
        let result = parse(["Vibe Screen", "--self-test"])

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Unknown Vibe Screen Host CLI flag: --self-test")
    }

    func testBareDoubleDashIsRejected() {
        let result = parse(["Vibe Screen", "--"])

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Unknown Vibe Screen Host CLI flag: --")
    }

    func testKnownCommandWithValueSyntaxIsRejected() {
        let result = parse(["Vibe Screen", "--host-self-test=foo"])

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Unknown Vibe Screen Host CLI flag: --host-self-test=foo")
    }

    func testKnownSelfTestFlagSelectsCommandMode() {
        let result = parse(["Vibe Screen", "--protocol-v1-self-test"])

        XCTAssertTrue(result.canLaunch)
        XCTAssertEqual(result.launchMode, .command(.protocolV1SelfTest))
        XCTAssertNil(result.errorMessage)
    }

    func testNoArgumentsSelectsGuiMode() {
        let result = parse(["Vibe Screen"])

        XCTAssertTrue(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertNil(result.errorMessage)
    }

    func testSingleDashInjectedArgumentsDoNotBlockGuiMode() {
        let result = parse(["Vibe Screen", "-NSDocumentRevisionsDebugMode", "YES"])

        XCTAssertTrue(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertNil(result.errorMessage)
    }

    func testKnownGuiDoubleDashFlagsDoNotBlockGuiMode() {
        let result = parse([
            "Vibe Screen",
            "--prefer-cgdisplaystream",
            "--headless-benchmark"
        ])

        XCTAssertTrue(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertNil(result.errorMessage)
    }

    func testMultipleCliCommandsAreRejected() {
        let result = parse(["Vibe Screen", "--host-self-test", "--issue-phase3-internet-lease"])

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Multiple Vibe Screen Host CLI commands are not supported.")
    }

    func testDuplicateCliCommandIsRejected() {
        let result = parse(["Vibe Screen", "--host-self-test", "--host-self-test"])

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Multiple Vibe Screen Host CLI commands are not supported.")
    }

    func testIOSLoopbackEnvironmentSelectsCommandMode() {
        let result = parse(
            ["Vibe Screen"],
            environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "invalid-target"]
        )

        XCTAssertTrue(result.canLaunch)
        XCTAssertEqual(result.launchMode, .command(.iOSLoopback(expectsInvalidTarget: true)))
        XCTAssertNil(result.errorMessage)
    }

    func testUnknownIOSLoopbackEnvironmentIsRejected() {
        let result = parse(
            ["Vibe Screen"],
            environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "other"]
        )

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Unknown iOS loopback scenario.")
    }

    func testEmptyIOSLoopbackEnvironmentIsRejected() {
        let result = parse(
            ["Vibe Screen"],
            environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": ""]
        )

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(result.errorMessage, "Unknown iOS loopback scenario.")
    }

    func testCliCommandCannotCombineWithIOSLoopbackEnvironment() {
        let result = parse(
            ["Vibe Screen", "--host-self-test"],
            environment: ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": "lifecycle"]
        )

        XCTAssertFalse(result.canLaunch)
        XCTAssertEqual(result.launchMode, .gui)
        XCTAssertEqual(
            result.errorMessage,
            "Vibe Screen Host CLI commands cannot be combined with iOS loopback mode."
        )
    }

    private func parse(
        _ arguments: [String],
        environment: [String: String] = [:]
    ) -> HostCommandLine.ParseResult {
        HostCommandLine.parse(arguments: arguments, environment: environment)
    }
}
