import XCTest
@testable import Telemachus

final class NetworkPathFingerprintTests: XCTestCase {
    func testEndpointRelevantChangeProducesDifferentOpaqueFingerprint() {
        let first = NetworkPathFingerprint.digest(components: [
            "status=satisfied", "interface=wifi:en0", "gateway=192.0.2.1:0",
        ])
        let second = NetworkPathFingerprint.digest(components: [
            "status=satisfied", "interface=wifi:en0", "gateway=198.51.100.1:0",
        ])

        XCTAssertNotEqual(first, second)
        XCTAssertEqual(first.count, 32)
        XCTAssertFalse(first.contains("192.0.2.1"))
        XCTAssertFalse(second.contains("198.51.100.1"))
    }

    func testVPNInterfaceSetChangesFingerprintWithoutExposingInterfaceNames() {
        let wifi = NetworkPathFingerprint.digest(components: [
            "status=satisfied", "interface=wifi:en0",
        ])
        let vpn = NetworkPathFingerprint.digest(components: [
            "status=satisfied", "interface=wifi:en0", "interface=other:utun7",
        ])

        XCTAssertNotEqual(wifi, vpn)
        XCTAssertFalse(vpn.contains("utun7"))
    }
}
