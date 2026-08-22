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

    func testSharedSecretAuthorizerAcceptsSignedRequestOnce() throws {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060)
        let store = InMemoryWakeHostReplayStore()
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, replayStore: store, now: { 1_010 })

        XCTAssertNil(authorizer.authorizationFailure(for: request))
        XCTAssertEqual(authorizer.authorizationFailure(for: request), .replayedRequest)

        let secondRequest = signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x11, count: WakeHostProof.minimumNonceByteCount)
        )
        XCTAssertNil(authorizer.authorizationFailure(for: secondRequest))
    }

    func testSharedSecretAuthorizerHandlesMaximumTimestampWithoutOverflow() {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(secret: secret, issuedAt: UInt64.max - 60, expiresAt: UInt64.max)
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { UInt64.max })

        XCTAssertNil(authorizer.authorizationFailure(for: request))
    }

    func testSharedSecretAuthorizerRejectsTamperedExpiredAndMalformedProofs() {
        let secret = Data((0..<32).map(UInt8.init))
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { 1_010 })

        let tampered = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060) { signature in
            signature[0] ^= 0x01
        }
        XCTAssertEqual(authorizer.authorizationFailure(for: tampered), .invalidAuthorization)

        let wrongKey = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060, keyID: "wrong")
        XCTAssertEqual(authorizer.authorizationFailure(for: wrongKey), .invalidAuthorization)

        let shortNonce = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060, nonce: Data([0x01]))
        XCTAssertEqual(authorizer.authorizationFailure(for: shortNonce), .invalidAuthorization)

        let expired = signedRequest(secret: secret, issuedAt: 900, expiresAt: 950)
        XCTAssertEqual(authorizer.authorizationFailure(for: expired), .expiredAuthorization)

        let tooLong = signedRequest(secret: secret, issuedAt: 900, expiresAt: 1_200)
        XCTAssertEqual(authorizer.authorizationFailure(for: tooLong), .expiredAuthorization)
    }

    func testWakeHostProofGoldenVector() {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060)
        XCTAssertEqual(request.keyID, "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd")
        XCTAssertEqual(
            request.signature.map { String(format: "%02x", $0) }.joined(),
            "5651fe6601bff89f975e6a02981b020fbb219e3b920477c02bfe37775ae08ea7"
        )
    }

    func testBroadcastTargetValidation() throws {
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "255.255.255.255", port: 9), try WakeHostBroadcastTarget(address: "255.255.255.255", port: 9))
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "192.168.1.255", port: 7).address, "192.168.1.255")
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "192.168.1.10", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "0.0.0.0", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "example.test", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "255.255.255.255", port: 0)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidPort)
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

    func testStreamingServerWakeHostRequestRequiresValidAuthorizationBeforeSending() {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060)
        let store = InMemoryWakeHostReplayStore()
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, replayStore: store, now: { 1_010 })

        let acceptedSender = RecordingWakeHostPacketSender()
        let accepted = StreamingServer.performWakeHostRequest(
            request,
            authorizer: authorizer,
            packetSender: acceptedSender
        )
        XCTAssertTrue(accepted.accepted)
        XCTAssertEqual(accepted.reason, "")
        XCTAssertEqual(acceptedSender.sentPackets.count, 1)

        let replaySender = RecordingWakeHostPacketSender()
        let replayed = StreamingServer.performWakeHostRequest(
            request,
            authorizer: authorizer,
            packetSender: replaySender
        )
        XCTAssertFalse(replayed.accepted)
        XCTAssertEqual(replayed.reason, "wake_host_replay")
        XCTAssertTrue(replaySender.sentPackets.isEmpty)

        let tampered = signedRequest(secret: secret, issuedAt: 1_000, expiresAt: 1_060) { signature in
            signature[0] ^= 0x01
        }
        let tamperedSender = RecordingWakeHostPacketSender()
        let unauthorized = StreamingServer.performWakeHostRequest(
            tampered,
            authorizer: authorizer,
            packetSender: tamperedSender
        )
        XCTAssertFalse(unauthorized.accepted)
        XCTAssertEqual(unauthorized.reason, "wake_host_unauthorized")
        XCTAssertTrue(tamperedSender.sentPackets.isEmpty)
    }
}

private func signedRequest(
    secret: Data,
    issuedAt: UInt64,
    expiresAt: UInt64,
    keyID overrideKeyID: String? = nil,
    nonce overrideNonce: Data? = nil,
    signatureMutator: ((inout Data) -> Void)? = nil
) -> WakeHostRequestContext {
    let keyID = overrideKeyID ?? WakeHostProof.keyID(secret: secret)
    let nonce = overrideNonce ?? Data((0..<16).map { UInt8(0xa0 + $0) })
    let requestID = Data([0x42])
    let mac = Data([1, 2, 3, 4, 5, 6])
    var signature = WakeHostProof.signature(
        requestID: requestID,
        targetMACAddress: mac,
        secureOnPassword: Data(),
        hostID: "host",
        deviceID: "device",
        keyID: keyID,
        issuedAtUnixSeconds: issuedAt,
        expiresAtUnixSeconds: expiresAt,
        nonce: nonce,
        secret: secret
    )
    signatureMutator?(&signature)
    return WakeHostRequestContext(
        requestID: requestID,
        targetMACAddress: mac,
        secureOnPassword: Data(),
        hostID: "host",
        deviceID: "device",
        keyID: keyID,
        issuedAtUnixSeconds: issuedAt,
        expiresAtUnixSeconds: expiresAt,
        nonce: nonce,
        signature: signature
    )
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
