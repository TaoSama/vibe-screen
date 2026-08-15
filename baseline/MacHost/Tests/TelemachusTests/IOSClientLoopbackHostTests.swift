import Foundation
import XCTest
@testable import Telemachus

final class IOSClientLoopbackHostTests: XCTestCase {
    func testMissingOverrideUsesProductionDefault() throws {
        XCTAssertEqual(
            try IOSClientLoopbackHost.requestedPort(environment: [:]),
            IOSClientLoopbackHost.defaultPort
        )
    }

    func testExplicitEphemeralAndNonDefaultPortsAreAccepted() throws {
        XCTAssertEqual(
            try IOSClientLoopbackHost.requestedPort(environment: [
                IOSClientLoopbackHost.portEnvironmentVariable: "0"
            ]),
            0
        )
        XCTAssertEqual(
            try IOSClientLoopbackHost.requestedPort(environment: [
                IOSClientLoopbackHost.portEnvironmentVariable: "61234"
            ]),
            61_234
        )
    }

    func testInvalidOverridesFailClosed() {
        for value in ["", "-1", "+1", " 54321", "54321 ", "65536", "１２３"] {
            XCTAssertThrowsError(try IOSClientLoopbackHost.requestedPort(environment: [
                IOSClientLoopbackHost.portEnvironmentVariable: value
            ])) { error in
                XCTAssertEqual(
                    error as? IOSClientLoopbackHost.ConfigurationError,
                    .invalidPort(value)
                )
            }
        }
    }

    func testEphemeralStreamingServerReportsNonzeroReadyPort() throws {
        let server = StreamingServer(
            port: 0,
            mode: .wireless(authToken: Data(repeating: 0xA5, count: 32))
        )
        defer { server.stop() }

        try server.start()
        let listeningPort = try XCTUnwrap(server.listeningPort)

        XCTAssertNotEqual(listeningPort, 0)
    }
}
