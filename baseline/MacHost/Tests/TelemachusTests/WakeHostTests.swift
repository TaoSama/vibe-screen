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

    func testSecureOnPasswordIsEmptyOrExactlySixRawBytes() throws {
        let mac = Data([1, 2, 3, 4, 5, 6])
        XCTAssertEqual(try WakeHostPacketBuilder.magicPacket(targetMACAddress: mac).count, 102)

        let rawPassword = Data([0x00, 0xff, 0x10, 0x20, 0x30, 0x40])
        let packet = try WakeHostPacketBuilder.magicPacket(
            targetMACAddress: mac,
            secureOnPassword: rawPassword
        )
        XCTAssertEqual(packet.count, 108)
        XCTAssertEqual(packet.suffix(6), rawPassword)

        for invalidPassword in [
            Data(repeating: 0x31, count: 1),
            Data(repeating: 0x31, count: 5),
            Data(repeating: 0x31, count: 7),
            Data("aabbccddeeff".utf8),
            Data("aa:bb:cc:dd:ee:ff".utf8),
        ] {
            XCTAssertThrowsError(try WakeHostPacketBuilder.magicPacket(
                targetMACAddress: mac,
                secureOnPassword: invalidPassword
            )) { error in
                XCTAssertEqual(error as? WakeHostRequestError, .invalidSecureOnPassword)
            }
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

    func testSharedSecretAuthorizerAcceptsClockSkewBoundariesOnly() {
        let secret = Data((0..<32).map(UInt8.init))
        let current: UInt64 = 1_000
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { current })

        let futureAtBoundary = signedRequest(secret: secret, issuedAt: current + 30, expiresAt: current + 60)
        XCTAssertNil(authorizer.authorizationFailure(for: futureAtBoundary))

        let futureBeyondBoundary = signedRequest(
            secret: secret,
            issuedAt: current + 31,
            expiresAt: current + 90,
            nonce: Data(repeating: 0x21, count: WakeHostProof.minimumNonceByteCount)
        )
        XCTAssertEqual(authorizer.authorizationFailure(for: futureBeyondBoundary), .expiredAuthorization)

        let expiredAtBoundary = signedRequest(
            secret: secret,
            issuedAt: current - 90,
            expiresAt: current - 30,
            nonce: Data(repeating: 0x22, count: WakeHostProof.minimumNonceByteCount)
        )
        XCTAssertNil(authorizer.authorizationFailure(for: expiredAtBoundary))

        let expiredBeyondBoundary = signedRequest(
            secret: secret,
            issuedAt: current - 91,
            expiresAt: current - 31,
            nonce: Data(repeating: 0x23, count: WakeHostProof.minimumNonceByteCount)
        )
        XCTAssertEqual(authorizer.authorizationFailure(for: expiredBeyondBoundary), .expiredAuthorization)
    }

    func testSharedSecretAuthorizerAcceptsActiveAndPreviousRotationKeys() {
        let activeSecret = Data((0..<32).map(UInt8.init))
        let previousSecret = Data((32..<64).map(UInt8.init))
        let unknownSecret = Data((64..<96).map(UInt8.init))
        let authorizer = SharedSecretWakeHostAuthorizer(
            activeSecret: activeSecret,
            acceptedPreviousSecrets: [previousSecret],
            now: { 1_010 }
        )

        XCTAssertNil(authorizer.authorizationFailure(for: signedRequest(
            secret: activeSecret,
            issuedAt: 1_000,
            expiresAt: 1_060
        )))
        XCTAssertNil(authorizer.authorizationFailure(for: signedRequest(
            secret: previousSecret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x24, count: WakeHostProof.minimumNonceByteCount)
        )))
        XCTAssertEqual(authorizer.authorizationFailure(for: signedRequest(
            secret: unknownSecret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x25, count: WakeHostProof.minimumNonceByteCount)
        )), .invalidAuthorization)
    }

    func testSharedSecretAuthorizerBindsExpectedHostAndDeviceIdentity() {
        let secret = Data((0..<32).map(UInt8.init))
        let authorizer = SharedSecretWakeHostAuthorizer(
            secret: secret,
            now: { 1_010 },
            expectedHostID: "host-a",
            expectedDeviceID: "device-a"
        )

        XCTAssertNil(authorizer.authorizationFailure(for: signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            hostID: "host-a",
            deviceID: "device-a"
        )))
        XCTAssertEqual(authorizer.authorizationFailure(for: signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x26, count: WakeHostProof.minimumNonceByteCount),
            hostID: "host-b",
            deviceID: "device-a"
        )), .invalidAuthorization)
        XCTAssertEqual(authorizer.authorizationFailure(for: signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x27, count: WakeHostProof.minimumNonceByteCount),
            hostID: "host-a",
            deviceID: "device-b"
        )), .invalidAuthorization)
    }

    func testSharedSecretAuthorizerRejectsMissingHostOrDeviceIdentity() {
        let secret = Data((0..<32).map(UInt8.init))
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { 1_010 })

        XCTAssertEqual(authorizer.authorizationFailure(for: signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            hostID: "",
            deviceID: "device"
        )), .invalidAuthorization)
        XCTAssertEqual(authorizer.authorizationFailure(for: signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            nonce: Data(repeating: 0x28, count: WakeHostProof.minimumNonceByteCount),
            hostID: "host",
            deviceID: ""
        )), .invalidAuthorization)
    }

    func testWakeHostProofBindsDeviceIdentityIntoTranscript() {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            deviceID: "device-a"
        )
        let rebound = WakeHostRequestContext(
            requestID: request.requestID,
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword,
            hostID: request.hostID,
            deviceID: "device-b",
            keyID: request.keyID,
            issuedAtUnixSeconds: request.issuedAtUnixSeconds,
            expiresAtUnixSeconds: request.expiresAtUnixSeconds,
            nonce: request.nonce,
            signature: request.signature
        )
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { 1_010 })

        XCTAssertEqual(authorizer.authorizationFailure(for: rebound), .invalidAuthorization)
    }

    func testWakeHostProofBindsSecureOnPasswordIntoTranscript() {
        let secret = Data((0..<32).map(UInt8.init))
        let request = signedRequest(
            secret: secret,
            issuedAt: 1_000,
            expiresAt: 1_060,
            secureOnPassword: Data([0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff])
        )
        let rebound = WakeHostRequestContext(
            requestID: request.requestID,
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: Data([0x00, 0xbb, 0xcc, 0xdd, 0xee, 0xff]),
            hostID: request.hostID,
            deviceID: request.deviceID,
            keyID: request.keyID,
            issuedAtUnixSeconds: request.issuedAtUnixSeconds,
            expiresAtUnixSeconds: request.expiresAtUnixSeconds,
            nonce: request.nonce,
            signature: request.signature
        )
        let authorizer = SharedSecretWakeHostAuthorizer(secret: secret, now: { 1_010 })

        XCTAssertEqual(authorizer.authorizationFailure(for: rebound), .invalidAuthorization)
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

    func testReplayStoreEvictsOldestEntryAndScopesByKey() {
        let store = InMemoryWakeHostReplayStore(maximumEntries: 2)
        let nonceA = Data(repeating: 0xa1, count: WakeHostProof.minimumNonceByteCount)
        let nonceB = Data(repeating: 0xb1, count: WakeHostProof.minimumNonceByteCount)
        let nonceC = Data(repeating: 0xc1, count: WakeHostProof.minimumNonceByteCount)

        XCTAssertTrue(store.consume(keyID: "key-1", nonce: nonceA))
        XCTAssertFalse(store.consume(keyID: "key-1", nonce: nonceA))
        XCTAssertTrue(store.consume(keyID: "key-2", nonce: nonceA))
        XCTAssertTrue(store.consume(keyID: "key-1", nonce: nonceB))
        XCTAssertTrue(store.consume(keyID: "key-1", nonce: nonceC))
        XCTAssertTrue(store.consume(keyID: "key-1", nonce: nonceA))
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
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "10.0.0.255", port: 9).address, "10.0.0.255")
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "172.16.0.255", port: 9).address, "172.16.0.255")
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "172.31.0.255", port: 9).address, "172.31.0.255")
        XCTAssertEqual(try WakeHostBroadcastTarget(address: "192.168.1.255", port: 7).address, "192.168.1.255")
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "192.168.1.10", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "172.32.0.255", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "203.0.113.255", port: 9)) { error in
            XCTAssertEqual(error as? WakeHostPacketSenderError, .invalidBroadcastAddress)
        }
        XCTAssertThrowsError(try WakeHostBroadcastTarget(address: "192.168.001.255", port: 9)) { error in
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
    secureOnPassword: Data = Data(),
    hostID: String = "host",
    deviceID: String = "device",
    signatureMutator: ((inout Data) -> Void)? = nil
) -> WakeHostRequestContext {
    let keyID = overrideKeyID ?? WakeHostProof.keyID(secret: secret)
    let nonce = overrideNonce ?? Data((0..<16).map { UInt8(0xa0 + $0) })
    let requestID = Data([0x42])
    let mac = Data([1, 2, 3, 4, 5, 6])
    var signature = WakeHostProof.signature(
        requestID: requestID,
        targetMACAddress: mac,
        secureOnPassword: secureOnPassword,
        hostID: hostID,
        deviceID: deviceID,
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
        secureOnPassword: secureOnPassword,
        hostID: hostID,
        deviceID: deviceID,
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
