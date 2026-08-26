import CryptoKit
import Foundation
import XCTest
@testable import VibeScreenCore

final class LANSecureRecordTests: XCTestCase {
    func testSharedFixtureRecordsAuthenticateAcrossDirectionsAndChannels() throws {
        let fixture = try ChannelRecordFixture.load()
        let pair = try Self.makeFixturePair(fixture)

        let hostControl = Data(hex: fixture.records.hostControl.record)
        let deviceMedia = Data(hex: fixture.records.deviceMedia.record)
        let hostAudio = Data(hex: fixture.records.hostAudio.record)
        let deviceBulk = Data(hex: fixture.records.deviceBulk.record)

        XCTAssertEqual(
            try pair.device.open(hostControl, channel: .control),
            Data(hex: fixture.records.hostControl.payload)
        )
        XCTAssertEqual(
            try pair.host.open(deviceMedia, channel: .video),
            Data(hex: fixture.records.deviceMedia.payload)
        )
        XCTAssertEqual(
            try pair.device.open(hostAudio, channel: .audio),
            Data(hex: fixture.records.hostAudio.payload)
        )
        XCTAssertEqual(
            try pair.host.open(deviceBulk, channel: .bulkTransfer),
            Data(hex: fixture.records.deviceBulk.payload)
        )
        XCTAssertThrowsError(try pair.device.open(hostControl, channel: .video))
        XCTAssertThrowsError(try pair.host.open(deviceMedia, channel: .control))
    }

    func testGeneratedRecordsRejectReplayTamperAndWrongSession() throws {
        let pair = try Self.makePair()
        let wrong = try Self.makePair(sessionIdentifier: "lan-session-other")
        let record = try pair.host.seal(Data([7]), channel: .video)

        XCTAssertEqual(try pair.device.open(record, channel: .video), Data([7]))
        XCTAssertThrowsError(try pair.device.open(record, channel: .video))
        XCTAssertThrowsError(try wrong.device.open(record, channel: .video))

        var tampered = try pair.host.seal(Data([8]), channel: .video)
        tampered[tampered.index(before: tampered.endIndex)] ^= 1
        XCTAssertThrowsError(try pair.device.open(tampered, channel: .video))
    }

    func testControlAndBulkAreStrictWhileMediaAndAudioAllowBoundedReordering() throws {
        let pair = try Self.makePair()
        let controlOne = try pair.host.seal(Data([1]), channel: .control)
        let controlTwo = try pair.host.seal(Data([2]), channel: .control)
        let mediaOne = try pair.host.seal(Data([3]), channel: .video)
        let mediaTwo = try pair.host.seal(Data([4]), channel: .video)
        let audioOne = try pair.host.seal(Data([5]), channel: .audio)
        let audioTwo = try pair.host.seal(Data([6]), channel: .audio)
        let bulkOne = try pair.host.seal(Data([7]), channel: .bulkTransfer)
        let bulkTwo = try pair.host.seal(Data([8]), channel: .bulkTransfer)

        XCTAssertEqual(try pair.device.open(controlTwo, channel: .control), Data([2]))
        XCTAssertThrowsError(try pair.device.open(controlOne, channel: .control))
        XCTAssertEqual(try pair.device.open(mediaTwo, channel: .video), Data([4]))
        XCTAssertEqual(try pair.device.open(mediaOne, channel: .video), Data([3]))
        XCTAssertEqual(try pair.device.open(audioTwo, channel: .audio), Data([6]))
        XCTAssertEqual(try pair.device.open(audioOne, channel: .audio), Data([5]))
        XCTAssertEqual(try pair.device.open(bulkTwo, channel: .bulkTransfer), Data([8]))
        XCTAssertThrowsError(try pair.device.open(bulkOne, channel: .bulkTransfer))
    }

    func testNegotiationCodecsRequireExplicitLegacyFallback() throws {
        let publicKey = P256.KeyAgreement.PrivateKey().publicKey.x963Representation
        let request = try LANSecureRecordNegotiation.encodeRequest(
            publicKey: publicKey,
            allowLegacyFallback: false
        )
        let decodedRequest = try LANSecureRecordNegotiation.decodeRequest(request)
        XCTAssertEqual(decodedRequest.publicKey, publicKey)
        XCTAssertFalse(decodedRequest.allowLegacyFallback)

        XCTAssertThrowsError(try LANSecureRecordNegotiation.encodeResponse(
            publicKey: publicKey,
            encrypted: false,
            explicitLegacyFallback: false
        ))
        XCTAssertThrowsError(try LANSecureRecordNegotiation.encodeResponse(
            publicKey: publicKey,
            encrypted: true,
            explicitLegacyFallback: true
        ))

        let legacy = try LANSecureRecordNegotiation.encodeResponse(
            publicKey: publicKey,
            encrypted: false,
            explicitLegacyFallback: true
        )
        let decodedLegacy = try LANSecureRecordNegotiation.decodeResponse(legacy)
        XCTAssertFalse(decodedLegacy.encrypted)
        XCTAssertTrue(decodedLegacy.legacy)
    }

    func testStreamFramerCarriesEncryptedTransportFrames() throws {
        let pair = try Self.makePair()
        let controlFrame = try TransportFrame(channel: .control, payload: Data([1, 2, 3])).encoded()
        let mediaFrame = try TransportFrame(channel: .video, payload: Data([4, 5])).encoded()
        let protected = try LANSecureRecordStreamFramer.encode(try pair.device.seal(controlFrame, channel: .control))
            + LANSecureRecordStreamFramer.encode(try pair.host.seal(mediaFrame, channel: .video))

        var framer = LANSecureRecordStreamFramer()
        let decrypted = try framer.append(protected) { record in
            if let opened = try? pair.host.openDeclaredChannel(record) { return opened }
            return try pair.device.openDeclaredChannel(record)
        }

        XCTAssertEqual(decrypted, [
            TransportFrame(channel: .control, payload: controlFrame),
            TransportFrame(channel: .video, payload: mediaFrame),
        ])
    }

    func testRecordChannelMustMatchInnerFrameChannel() throws {
        let pair = try Self.makePair()
        let innerControl = try TransportFrame(channel: .control, payload: Data([0xaa])).encoded()
        let opened = try pair.host.openDeclaredChannel(
            try pair.device.seal(innerControl, channel: .video)
        )
        var transportFramer = TransportFramer()
        let decoded = try transportFramer.append(opened.payload)

        XCTAssertEqual(opened.channel, .video)
        XCTAssertEqual(decoded, [TransportFrame(channel: .control, payload: Data([0xaa]))])
        XCTAssertNotEqual(decoded.first?.channel, opened.channel)
    }

    func testRecordLengthAllowsMaximumInnerTransportFrame() throws {
        XCTAssertEqual(
            LANSecureRecordStreamFramer.maximumRecordBytes,
            TransportFramer.headerLength
                + TransportFramer.maximumPayloadBytes
                + LANSessionPacketCipher.recordOverhead
        )
    }

    private static func makePair(sessionIdentifier: String = "lan-session-1") throws -> (
        host: LANSecureRecordSession,
        device: LANSecureRecordSession
    ) {
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
        let hostSecret = try hostKey.sharedSecretFromKeyAgreement(
            with: P256.KeyAgreement.PublicKey(x963Representation: devicePublic)
        ).withUnsafeBytes { Data($0) }
        let deviceSecret = try deviceKey.sharedSecretFromKeyAgreement(
            with: P256.KeyAgreement.PublicKey(x963Representation: hostPublic)
        ).withUnsafeBytes { Data($0) }
        XCTAssertEqual(hostSecret, deviceSecret)
        return (
            host: try LANSecureRecordSession(
                role: .host,
                sessionIdentifier: sessionIdentifier,
                sharedSecret: hostSecret,
                bootstrapToken: token,
                context: context
            ),
            device: try LANSecureRecordSession(
                role: .device,
                sessionIdentifier: sessionIdentifier,
                sharedSecret: deviceSecret,
                bootstrapToken: token,
                context: context
            )
        )
    }

    private static func makeFixturePair(_ fixture: ChannelRecordFixture) throws -> (
        host: LANSecureRecordSession,
        device: LANSecureRecordSession
    ) {
        let sharedSecret = Data(hex: fixture.input.sharedSecret)
        let bootstrapSecret = Data(hex: fixture.input.bootstrapSecret)
        let context = Data(hex: fixture.input.context)
        return (
            host: try LANSecureRecordSession(
                role: .host,
                sessionIdentifier: fixture.session.id,
                sessionEpoch: fixture.session.epoch,
                sharedSecret: sharedSecret,
                bootstrapToken: bootstrapSecret,
                context: context
            ),
            device: try LANSecureRecordSession(
                role: .device,
                sessionIdentifier: fixture.session.id,
                sessionEpoch: fixture.session.epoch,
                sharedSecret: sharedSecret,
                bootstrapToken: bootstrapSecret,
                context: context
            )
        )
    }
}

private struct ChannelRecordFixture: Decodable {
    struct Session: Decodable { let id: String; let epoch: UInt64 }
    struct Input: Decodable {
        let sharedSecret: String
        let bootstrapSecret: String
        let context: String

        enum CodingKeys: String, CodingKey {
            case sharedSecret = "shared_secret"
            case bootstrapSecret = "bootstrap_secret"
            case context
        }
    }
    struct Record: Decodable { let payload: String; let record: String }
    struct Records: Decodable {
        let hostControl: Record
        let deviceMedia: Record
        let hostAudio: Record
        let deviceBulk: Record

        enum CodingKeys: String, CodingKey {
            case hostControl = "host_control"
            case deviceMedia = "device_media"
            case hostAudio = "host_audio"
            case deviceBulk = "device_bulk"
        }
    }

    let session: Session
    let input: Input
    let records: Records

    static func load() throws -> ChannelRecordFixture {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("contracts/fixtures/security/v1/channel-records.json")
        return try JSONDecoder().decode(ChannelRecordFixture.self, from: Data(contentsOf: url))
    }
}

private extension Data {
    init(hex: String) {
        var bytes: [UInt8] = []
        bytes.reserveCapacity(hex.count / 2)
        var index = hex.startIndex
        while index < hex.endIndex {
            let next = hex.index(index, offsetBy: 2)
            bytes.append(UInt8(hex[index..<next], radix: 16)!)
            index = next
        }
        self.init(bytes)
    }
}
