import XCTest
@testable import VibeScreenCore

final class MacHostLoopbackTestConfigurationTests: XCTestCase {
    func testMissingOverrideUsesProductionDefault() throws {
        XCTAssertEqual(
            try MacHostLoopbackTestConfiguration.port(environment: [:]),
            TrustedLANPairing.defaultPort
        )
    }

    func testValidOverrideUsesNonDefaultPort() throws {
        XCTAssertEqual(
            try MacHostLoopbackTestConfiguration.port(environment: [
                MacHostLoopbackTestConfiguration.portEnvironmentVariable: "61234"
            ]),
            61_234
        )
    }

    func testInvalidOverridesFailClosed() {
        for value in ["", "0", "-1", "+1", " 54321", "54321 ", "65536", "１２３"] {
            XCTAssertThrowsError(try MacHostLoopbackTestConfiguration.port(environment: [
                MacHostLoopbackTestConfiguration.portEnvironmentVariable: value
            ])) { error in
                XCTAssertEqual(
                    error as? MacHostLoopbackTestConfigurationError,
                    .invalidPort(value)
                )
            }
        }
    }
}
