import Foundation
import XCTest
@testable import Telemachus

final class WakeHostTests: XCTestCase {
    func testMagicPacketRepeatsTargetMacAndAppendsSecureOnPassword() throws {
        let mac = Data([0x01, 0x23, 0x45, 0x67, 0x89, 0xab])
        let password = Data([0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff])

        let packet = try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: mac,
            secureOnPassword: password
        )

        XCTAssertEqual(packet.count, 108)
        XCTAssertEqual(packet.prefix(6), Data(repeating: 0xff, count: 6))
        for index in 0..<16 {
            XCTAssertEqual(packet[(6 + index * 6)..<(12 + index * 6)], mac)
        }
        XCTAssertEqual(packet.suffix(6), password)
    }

    func testMagicPacketRejectsInvalidMacAndSecureOnPassword() {
        XCTAssertThrowsError(try WakeHostPacketBuilder.magicPacket(targetMACAddress: Data())) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .invalidMACAddress)
        }
        XCTAssertThrowsError(try WakeHostPacketBuilder.magicPacket(targetMACAddress: Data(repeating: 0, count: 6))) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .invalidMACAddress)
        }
        XCTAssertThrowsError(try WakeHostPacketBuilder.magicPacket(targetMACAddress: Data(repeating: 0xff, count: 6))) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .invalidMACAddress)
        }
        XCTAssertThrowsError(try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: Data([1, 2, 3, 4, 5, 6]),
            secureOnPassword: Data([1, 2, 3])
        )) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .invalidSecureOnPassword)
        }
    }

    func testDecisionDefaultsToDenyAndAllowsExplicitAuthorizer() throws {
        let request = WakeHostRequestContext(
            requestID: Data([0x42]),
            targetMACAddress: Data([1, 2, 3, 4, 5, 6]),
            secureOnPassword: Data(),
            hostID: "host",
            deviceID: "device",
            keyID: "",
            issuedAtUnixSeconds: 0,
            expiresAtUnixSeconds: 0,
            nonce: Data(),
            signature: Data()
        )

        XCTAssertThrowsError(try WakeHostDecision.magicPacket(for: request)) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .policyDenied)
        }
        XCTAssertEqual(
            try WakeHostDecision.magicPacket(for: request, authorizer: StaticWakeHostAuthorizer(wakeAllowed: true)).count,
            WakeHostPacketBuilder.baseMagicPacketByteCount
        )
    }

    func testDecisionRejectsEmptyRequestIDBeforePolicy() {
        let request = WakeHostRequestContext(
            requestID: Data(),
            targetMACAddress: Data([1, 2, 3, 4, 5, 6]),
            secureOnPassword: Data(),
            hostID: "host",
            deviceID: "device",
            keyID: "",
            issuedAtUnixSeconds: 0,
            expiresAtUnixSeconds: 0,
            nonce: Data(),
            signature: Data()
        )

        XCTAssertThrowsError(try WakeHostDecision.magicPacket(
            for: request,
            authorizer: StaticWakeHostAuthorizer(wakeAllowed: true)
        )) { error in
            XCTAssertEqual(error as? WakeHostRequestError, .invalidRequestID)
        }
    }

    func testStreamingServerWakeHostRequestMapsPolicyAndSenderResults() {
        let request = WakeHostRequestContext(
            requestID: Data([0x42]),
            targetMACAddress: Data([1, 2, 3, 4, 5, 6]),
            secureOnPassword: Data(),
            hostID: "host",
            deviceID: "device",
            keyID: "",
            issuedAtUnixSeconds: 0,
            expiresAtUnixSeconds: 0,
            nonce: Data(),
            signature: Data()
        )

        let deniedSender = RecordingWakeHostPacketSender()
        XCTAssertEqual(
            StreamingServer.performWakeHostRequest(
                request,
                authorizer: DenyWakeHostAuthorizer(),
                packetSender: deniedSender
            ).reason,
            "wake_host_policy_denied"
        )
        XCTAssertEqual(deniedSender.sentPackets.count, 0)

        let allowedSender = RecordingWakeHostPacketSender()
        let accepted = StreamingServer.performWakeHostRequest(
            request,
            authorizer: StaticWakeHostAuthorizer(wakeAllowed: true),
            packetSender: allowedSender
        )
        XCTAssertTrue(accepted.accepted)
        XCTAssertEqual(accepted.reason, "")
        XCTAssertEqual(allowedSender.sentPackets.count, 1)
        XCTAssertEqual(allowedSender.sentPackets.first?.count, WakeHostPacketBuilder.baseMagicPacketByteCount)

        let failingSender = RecordingWakeHostPacketSender(error: RecordingWakeHostPacketSenderError.failed)
        let failed = StreamingServer.performWakeHostRequest(
            request,
            authorizer: StaticWakeHostAuthorizer(wakeAllowed: true),
            packetSender: failingSender
        )
        XCTAssertFalse(failed.accepted)
        XCTAssertEqual(failed.reason, "wake_packet_send_failed")
    }
}

private enum RecordingWakeHostPacketSenderError: Error {
    case failed
}

private final class RecordingWakeHostPacketSender: WakeHostPacketSending, @unchecked Sendable {
    private let lock = NSLock()
    private let error: Error?
    private var packets: [Data] = []

    init(error: Error? = nil) {
        self.error = error
    }

    var sentPackets: [Data] {
        lock.withLock { packets }
    }

    func sendWakeHostPacket(_ packet: Data) throws {
        if let error { throw error }
        lock.withLock { packets.append(packet) }
    }
}
