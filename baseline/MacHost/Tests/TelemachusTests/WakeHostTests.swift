import Foundation
import CryptoKit
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

    func testPairingBoundAuthorizerAcceptsSignedFreshProof() throws {
        let fixture = try WakeHostProofFixture()
        let request = try fixture.signedRequest()
        let sender = RecordingWakeHostPacketSender()

        let result = StreamingServer.performWakeHostRequest(
            request,
            authorizer: fixture.authorizer(),
            packetSender: sender
        )

        XCTAssertTrue(result.accepted)
        XCTAssertEqual(result.reason, "")
        XCTAssertEqual(sender.sentPackets.count, 1)
        XCTAssertEqual(sender.sentPackets.first?.count, WakeHostPacketBuilder.baseMagicPacketByteCount)
    }

    func testPairingBoundAuthorizerRejectsUnpairedDevice() throws {
        let fixture = try WakeHostProofFixture()
        let unpaired = try WakeHostProofFixture(deviceID: "unpaired-device")
        let request = try unpaired.signedRequest(hostIdentity: fixture.hostIdentity)

        let result = StreamingServer.performWakeHostRequest(
            request,
            authorizer: fixture.authorizer(),
            packetSender: RecordingWakeHostPacketSender()
        )

        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.reason, "unpaired_device")
    }

    func testPairingBoundAuthorizerRejectsExpiredProof() throws {
        let fixture = try WakeHostProofFixture(now: 1_000)
        let request = try fixture.signedRequest(issuedAt: 100, expiresAt: 200)

        let result = StreamingServer.performWakeHostRequest(
            request,
            authorizer: fixture.authorizer(),
            packetSender: RecordingWakeHostPacketSender()
        )

        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.reason, "wake_host_proof_expired")
    }

    func testPairingBoundAuthorizerRejectsReplay() throws {
        let fixture = try WakeHostProofFixture()
        let authorizer = fixture.authorizer()
        let request = try fixture.signedRequest()
        let firstSender = RecordingWakeHostPacketSender()
        let secondSender = RecordingWakeHostPacketSender()

        XCTAssertTrue(StreamingServer.performWakeHostRequest(
            request,
            authorizer: authorizer,
            packetSender: firstSender
        ).accepted)
        let replayed = StreamingServer.performWakeHostRequest(
            request,
            authorizer: authorizer,
            packetSender: secondSender
        )

        XCTAssertFalse(replayed.accepted)
        XCTAssertEqual(replayed.reason, "wake_host_replay")
        XCTAssertEqual(secondSender.sentPackets.count, 0)
    }

    func testPairingBoundAuthorizerRejectsSignatureForAnotherSession() throws {
        let fixture = try WakeHostProofFixture()
        let request = try fixture.signedRequest(sessionID: Data([0x10, 0x20, 0x30, 0x40]), sessionEpoch: 9)
        let replayedInOtherSession = WakeHostRequestContext(
            requestID: request.requestID,
            targetMACAddress: request.targetMACAddress,
            secureOnPassword: request.secureOnPassword,
            hostID: request.hostID,
            deviceID: request.deviceID,
            keyID: request.keyID,
            issuedAtUnixSeconds: request.issuedAtUnixSeconds,
            expiresAtUnixSeconds: request.expiresAtUnixSeconds,
            nonce: request.nonce,
            signature: request.signature,
            sessionID: Data([0x99, 0x88, 0x77, 0x66]),
            sessionEpoch: 9
        )

        let result = StreamingServer.performWakeHostRequest(
            replayedInOtherSession,
            authorizer: fixture.authorizer(),
            packetSender: RecordingWakeHostPacketSender()
        )

        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.reason, "invalid_wake_signature")
    }

    func testPairingBoundAuthorizerRejectsShortNonce() throws {
        let fixture = try WakeHostProofFixture()
        let request = try fixture.signedRequest(nonce: Data([0x01, 0x02, 0x03]))

        let result = StreamingServer.performWakeHostRequest(
            request,
            authorizer: fixture.authorizer(),
            packetSender: RecordingWakeHostPacketSender()
        )

        XCTAssertFalse(result.accepted)
        XCTAssertEqual(result.reason, "invalid_wake_nonce")
    }
}

private struct WakeHostProofFixture {
    let hostIdentity: PlatformPublicIdentity
    let peerIdentity: PlatformPublicIdentity
    private let deviceSigningKey: P256.Signing.PrivateKey
    private let now: UInt64

    init(deviceID: String = "paired-device", now: UInt64 = 1_000) throws {
        let hostSigningKey = P256.Signing.PrivateKey()
        let deviceSigningKey = P256.Signing.PrivateKey()
        let hostPublicKey = hostSigningKey.publicKey.x963Representation
        let devicePublicKey = deviceSigningKey.publicKey.x963Representation
        self.hostIdentity = PlatformPublicIdentity(
            deviceID: "host",
            keyID: InternetPairingCanonical.hexDigest(hostPublicKey),
            keyEpoch: PlatformPublicIdentity.initialKeyEpoch,
            signingPublicKey: hostPublicKey
        )
        self.peerIdentity = PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: InternetPairingCanonical.hexDigest(devicePublicKey),
            keyEpoch: PlatformPublicIdentity.initialKeyEpoch,
            signingPublicKey: devicePublicKey
        )
        self.deviceSigningKey = deviceSigningKey
        self.now = now
    }

    func authorizer() -> PairingBoundWakeHostAuthorizer {
        PairingBoundWakeHostAuthorizer(
            hostIdentity: hostIdentity,
            peerIdentity: peerIdentity,
            nonceStore: MemoryWakeHostNonceStore(),
            nowUnixSeconds: { now }
        )
    }

    func signedRequest(
        hostIdentity: PlatformPublicIdentity? = nil,
        issuedAt: UInt64 = 900,
        expiresAt: UInt64 = 1_100,
        nonce: Data = Data(Array(0..<16).map(UInt8.init)),
        sessionID: Data = Data([0x10, 0x20, 0x30, 0x40]),
        sessionEpoch: UInt64 = 7
    ) throws -> WakeHostRequestContext {
        let hostIdentity = hostIdentity ?? self.hostIdentity
        let unsigned = WakeHostRequestContext(
            requestID: Data([0x42]),
            targetMACAddress: Data([1, 2, 3, 4, 5, 6]),
            secureOnPassword: Data(),
            hostID: hostIdentity.deviceID,
            deviceID: peerIdentity.deviceID,
            keyID: peerIdentity.keyID,
            issuedAtUnixSeconds: issuedAt,
            expiresAtUnixSeconds: expiresAt,
            nonce: nonce,
            signature: Data(),
            sessionID: sessionID,
            sessionEpoch: sessionEpoch
        )
        return WakeHostRequestContext(
            requestID: unsigned.requestID,
            targetMACAddress: unsigned.targetMACAddress,
            secureOnPassword: unsigned.secureOnPassword,
            hostID: unsigned.hostID,
            deviceID: unsigned.deviceID,
            keyID: unsigned.keyID,
            issuedAtUnixSeconds: unsigned.issuedAtUnixSeconds,
            expiresAtUnixSeconds: unsigned.expiresAtUnixSeconds,
            nonce: unsigned.nonce,
            signature: try pairingRawDigestSignature(
                privateKey: deviceSigningKey,
                digest: PairingBoundWakeHostAuthorizer.proofDigest(for: unsigned)
            ),
            sessionID: unsigned.sessionID,
            sessionEpoch: unsigned.sessionEpoch
        )
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
