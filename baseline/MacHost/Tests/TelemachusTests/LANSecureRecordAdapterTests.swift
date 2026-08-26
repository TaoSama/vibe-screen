import CryptoKit
import XCTest
@testable import Telemachus

final class LANSecureRecordAdapterTests: XCTestCase {
    func testNegotiationRequestAndResponseRoundTrip() throws {
        let deviceKey = P256.KeyAgreement.PrivateKey()
        let hostKey = P256.KeyAgreement.PrivateKey()

        let request = try LANSecureRecordNegotiation.encodeRequest(
            publicKey: deviceKey.publicKey.x963Representation,
            allowLegacyFallback: false
        )
        let parsedRequest = try LANSecureRecordNegotiation.decodeRequest(request)
        XCTAssertEqual(parsedRequest.publicKey, deviceKey.publicKey.x963Representation)
        XCTAssertFalse(parsedRequest.allowLegacyFallback)

        let response = try LANSecureRecordNegotiation.encodeResponse(
            publicKey: hostKey.publicKey.x963Representation,
            encrypted: true,
            explicitLegacyFallback: false
        )
        let parsedResponse = try LANSecureRecordNegotiation.decodeResponse(response)
        XCTAssertEqual(parsedResponse.publicKey, hostKey.publicKey.x963Representation)
        XCTAssertTrue(parsedResponse.encrypted)
        XCTAssertFalse(parsedResponse.legacy)
    }

    func testLegacyFallbackMustBeExplicit() throws {
        let key = P256.KeyAgreement.PrivateKey()
        let publicKey = key.publicKey.x963Representation

        XCTAssertThrowsError(
            try LANSecureRecordNegotiation.encodeResponse(
                publicKey: publicKey,
                encrypted: false,
                explicitLegacyFallback: false
            )
        )
        XCTAssertThrowsError(
            try LANSecureRecordNegotiation.encodeResponse(
                publicKey: publicKey,
                encrypted: true,
                explicitLegacyFallback: true
            )
        )

        let legacy = try LANSecureRecordNegotiation.encodeResponse(
            publicKey: publicKey,
            encrypted: false,
            explicitLegacyFallback: true
        )
        let parsed = try LANSecureRecordNegotiation.decodeResponse(legacy)
        XCTAssertFalse(parsed.encrypted)
        XCTAssertTrue(parsed.legacy)
    }

    func testRecordsProtectControlAndMediaDirections() throws {
        let pair = try makePair()

        let control = try pair.device.seal(Data([1, 2, 3]), channel: .control)
        let media = try pair.host.seal(Data([4, 5, 6]), channel: .media)

        XCTAssertEqual(try pair.host.open(control, channel: .control), Data([1, 2, 3]))
        XCTAssertEqual(try pair.device.open(media, channel: .media), Data([4, 5, 6]))
        XCTAssertThrowsError(try pair.host.open(control, channel: .media))
        XCTAssertThrowsError(try pair.device.open(media, channel: .control))
    }

    func testReplayTamperAndWrongSessionFailClosed() throws {
        let pair = try makePair()
        let wrong = try makePair(sessionIdentifier: "lan-session-other")
        let record = try pair.host.seal(Data([7]), channel: .media)

        XCTAssertEqual(try pair.device.open(record, channel: .media), Data([7]))
        XCTAssertThrowsError(try pair.device.open(record, channel: .media))
        XCTAssertThrowsError(try wrong.device.open(record, channel: .media))

        var tampered = try pair.host.seal(Data([8]), channel: .media)
        tampered[tampered.count - 1] ^= 0x01
        XCTAssertThrowsError(try pair.device.open(tampered, channel: .media))
    }

    func testOpensTheDeclaredRecordChannel() throws {
        let pair = try makePair()
        let control = try pair.device.seal(Data([1]), channel: .control)
        let media = try pair.host.seal(Data([2]), channel: .media)
        let audio = try pair.host.seal(Data([3]), channel: .audio)
        let bulk = try pair.device.seal(Data([4]), channel: .bulk)

        XCTAssertEqual(PlatformSessionPacketCipher.declaredInternetChannel(in: control), .control)
        XCTAssertEqual(PlatformSessionPacketCipher.declaredInternetChannel(in: media), .media)
        XCTAssertEqual(PlatformSessionPacketCipher.declaredInternetChannel(in: audio), .audio)
        XCTAssertEqual(PlatformSessionPacketCipher.declaredInternetChannel(in: bulk), .bulk)
        XCTAssertEqual(try pair.host.openDeclaredChannel(control), Data([1]))
        XCTAssertEqual(try pair.device.openDeclaredChannel(media), Data([2]))
        XCTAssertEqual(try pair.device.openDeclaredChannel(audio), Data([3]))
        XCTAssertEqual(try pair.host.openDeclaredChannel(bulk), Data([4]))
    }

    func testRecordLengthAllowsMaximumInnerProtocolV1Frame() throws {
        XCTAssertEqual(
            LANSecureRecordStreamFramer.maximumRecordBytes,
            ProtocolV1Framer.headerBytes
                + ProtocolV1Framer.maximumPayloadBytes
                + PlatformSessionPacketCipher.recordOverhead
        )
    }

    private func makePair(
        sessionIdentifier: String = "lan-session-1"
    ) throws -> (host: LANSecureRecordSession, device: LANSecureRecordSession) {
        let token = Data((0..<32).map(UInt8.init))
        let hostKey = P256.KeyAgreement.PrivateKey()
        let deviceKey = P256.KeyAgreement.PrivateKey()
        let hostPublic = hostKey.publicKey.x963Representation
        let devicePublic = deviceKey.publicKey.x963Representation
        let context = LANSecureRecordSession.transcriptContext(
            sessionIdentifier: sessionIdentifier,
            hostPublicKey: hostPublic,
            devicePublicKey: devicePublic
        )
        let hostSecret = try hostKey.sharedSecretData(with: devicePublic)
        let deviceSecret = try deviceKey.sharedSecretData(with: hostPublic)
        XCTAssertEqual(hostSecret, deviceSecret)

        return (
            try LANSecureRecordSession(
                role: .host,
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: 1,
                sharedSecret: hostSecret,
                bootstrapToken: token,
                context: context
            ),
            try LANSecureRecordSession(
                role: .device,
                sessionIdentifier: sessionIdentifier,
                sessionEpoch: 1,
                sharedSecret: deviceSecret,
                bootstrapToken: token,
                context: context
            )
        )
    }
}
