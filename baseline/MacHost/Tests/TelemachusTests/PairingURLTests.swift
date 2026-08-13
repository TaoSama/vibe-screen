import XCTest
@testable import Telemachus

final class PairingURLTests: XCTestCase {
    func testWirelessPairingEndpointChangesProduceDifferentURLs() throws {
        let token = Data(repeating: 7, count: 32)
        let original = WirelessPairingEndpoint(address: "192.168.1.42", port: 54321)
        let newAddress = WirelessPairingEndpoint(address: "10.0.0.8", port: 54321)
        let newPort = WirelessPairingEndpoint(address: "192.168.1.42", port: 54322)

        let originalURL = try XCTUnwrap(original.pairingURL(token: token, name: "Mac"))
        XCTAssertNotEqual(originalURL, newAddress.pairingURL(token: token, name: "Mac"))
        XCTAssertNotEqual(originalURL, newPort.pairingURL(token: token, name: "Mac"))
    }

    func testWirelessPairingEndpointBuildsURLFromPublishedAddress() throws {
        let endpoint = WirelessPairingEndpoint(address: "192.168.1.42", port: 54321)
        let url = try XCTUnwrap(endpoint.pairingURL(token: Data(repeating: 7, count: 32), name: "Mac"))

        XCTAssertTrue(url.hasPrefix("telemachus://192.168.1.42:54321?"))
        XCTAssertEqual(endpoint.statusText, "LAN address: 192.168.1.42:54321")
    }

    func testWirelessPairingEndpointRemovesURLWhenAddressDisappears() {
        let endpoint = WirelessPairingEndpoint(address: nil, port: 54321)

        XCTAssertNil(endpoint.pairingURL(token: Data(repeating: 7, count: 32), name: "Mac"))
        XCTAssertEqual(endpoint.statusText, "No LAN address available")
    }

    func testBuildContainsAllFields() {
        let token = Data((0..<32).map { UInt8($0) })
        let url = PairingURL.build(host: "192.168.1.42", port: 8888, token: token, name: "Dat's MacBook")
        XCTAssertTrue(url.hasPrefix("telemachus://192.168.1.42:8888?"))
        XCTAssertTrue(url.contains("t="))
        XCTAssertTrue(url.contains("name="))
    }

    func testTokenIsBase64URLNoPadding() {
        let token = Data((0..<32).map { _ in UInt8(0xAB) })
        let url = PairingURL.build(host: "1.2.3.4", port: 9, token: token, name: "x")
        let tValue = url.split(separator: "?")[1]
            .split(separator: "&")
            .first { $0.hasPrefix("t=") }!
            .dropFirst(2)
        XCTAssertEqual(tValue.count, 43)
        XCTAssertFalse(tValue.contains("="))
        XCTAssertFalse(tValue.contains("+"))
        XCTAssertFalse(tValue.contains("/"))
    }

    func testNameIsURLEncoded() {
        let token = Data(repeating: 0, count: 32)
        let url = PairingURL.build(host: "1.2.3.4", port: 9, token: token, name: "Dat's MacBook")
        XCTAssertTrue(url.contains("name=Dat%27s%20MacBook") || url.contains("name=Dat's%20MacBook"))
    }
}
