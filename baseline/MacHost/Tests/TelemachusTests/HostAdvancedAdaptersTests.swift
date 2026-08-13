import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class HostAdvancedAdaptersTests: XCTestCase {
    func testCapabilitiesRequireInstalledAdaptersAndNeverImplyHDR() {
        let capabilities = ProtocolV1SessionConfiguration.productionHostCapabilities(
            touchEnabled: false,
            advanced: .init(
                audio: true,
                clipboard: true,
                fileTransfer: true,
                colorManagement: true,
                hostActions: false,
                wakeHost: false
            )
        )
        XCTAssertTrue(capabilities.isSuperset(of: [.audio, .clipboard, .fileTransfer, .colorManagement]))
        XCTAssertFalse(capabilities.contains(.hdrVideo))
        XCTAssertFalse(capabilities.contains(.wakeHost))
        XCTAssertFalse(capabilities.contains(.hostActions))
    }

    func testTransportAcceptsIndependentAudioAndBulkChannels() throws {
        let audio = try ProtocolV1TransportFrame(channel: .audio, payload: Data([1])).encoded()
        let bulk = try ProtocolV1TransportFrame(channel: .bulk, payload: Data([2, 3])).encoded()
        var framer = ProtocolV1Framer()
        XCTAssertEqual(
            try framer.append(audio + bulk),
            [
                ProtocolV1TransportFrame(channel: .audio, payload: Data([1])),
                ProtocolV1TransportFrame(channel: .bulk, payload: Data([2, 3]))
            ]
        )
    }

    func testPCMAudioCodecEnforcesProductionPacketSize() throws {
        var header = VSAudioPacketHeader()
        header.streamID = 1
        header.sessionEpoch = 2
        header.configEpoch = 1
        header.sequence = 3
        header.frameCount = PCMAudioFormat.production.framesPerPacket
        let payload = Data(repeating: 0x7f, count: PCMAudioFormat.production.bytesPerPacket)
        let encoded = try ProtocolV1AudioPacketCodec.encode(header: header, payload: payload)
        let decoded = try ProtocolV1AudioPacketCodec.decode(encoded)
        XCTAssertEqual(decoded.header.sequence, 3)
        XCTAssertEqual(decoded.payload, payload)
        XCTAssertThrowsError(try ProtocolV1AudioPacketCodec.encode(
            header: header,
            payload: Data(payload.dropLast())
        ))
    }

    func testFileAdapterRejectsUnsafeNamesAndVerifiesSequentialDigest() throws {
        XCTAssertFalse(HostIncomingFileAdapter.isSafeFileName("../secret"))
        XCTAssertFalse(HostIncomingFileAdapter.isSafeFileName("bad\nname"))
        XCTAssertTrue(HostIncomingFileAdapter.isSafeFileName("report.txt"))

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let adapter = try HostIncomingFileAdapter(destinationDirectory: directory)
        let payload = Data("bounded file".utf8)
        let transferID = Data(repeating: 0x21, count: 16)
        var offer = VSFileOffer()
        offer.transferID = transferID
        offer.fileName = "report.txt"
        offer.byteLength = UInt64(payload.count)
        offer.sha256 = Data(SHA256.hash(data: payload))
        XCTAssertTrue(try adapter.accept(offer).accepted)

        var header = VSFileChunkHeader()
        header.transferID = transferID
        header.offset = 0
        header.payloadLength = UInt32(payload.count)
        header.sessionEpoch = 9
        header.chunkSha256 = Data(SHA256.hash(data: payload))
        header.final = true
        let headerBytes = try header.serializedData()
        let frame = encodeVarint(headerBytes.count) + headerBytes + payload
        let chunk = try HostFileChunk(serializedFrame: frame, maximumChunkBytes: 64 * 1_024)
        XCTAssertEqual(try adapter.append(chunk, sessionEpoch: 9), UInt64(payload.count))
        let completed = try adapter.finish(transferID: transferID)
        XCTAssertEqual(try Data(contentsOf: completed.url), payload)
    }

    func testWakeAuthenticatorBindsIdentityTargetExpiryAndReplay() throws {
        let secret = Data(repeating: 0x44, count: 32)
        let target = Data([0x02, 0x11, 0x22, 0x33, 0x44, 0x55])
        var request = VSWakeHostRequest()
        request.requestID = Data(repeating: 1, count: 16)
        request.targetMacAddress = target
        request.hostID = "host"
        request.deviceID = "paired-device"
        request.keyID = "key-1"
        request.issuedAtUnixSeconds = 100
        request.expiresAtUnixSeconds = 130
        request.nonce = Data(repeating: 2, count: 32)
        request.signature = Data(HMAC<SHA256>.authenticationCode(
            for: HostWakeRequestAuthenticator.signingBytes(request),
            using: SymmetricKey(data: secret)
        ))
        var authenticator = HostWakeRequestAuthenticator(
            secret: secret,
            hostID: "host",
            deviceID: "paired-device",
            keyID: "key-1",
            targetMACAddress: target
        )
        XCTAssertNoThrow(try authenticator.validate(request, now: 110))
        XCTAssertThrowsError(try authenticator.validate(request, now: 111)) { error in
            XCTAssertEqual(error as? HostAdvancedAdapterError, .replayedWakeRequest)
        }
        var forged = request
        forged.nonce = Data(repeating: 3, count: 32)
        forged.deviceID = "other-device"
        XCTAssertThrowsError(try authenticator.validate(forged, now: 110))
    }

    func testAudioNegotiatesNonzeroLimitsAndGatesPacketsUntilAcknowledged() throws {
        let sessionID = Data(repeating: 0x31, count: 16)
        let session = ProtocolV1SessionCoordinator(configuration: .init(
            sessionID: sessionID,
            sessionEpoch: 9,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 0,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: false,
                advanced: .init(audio: true, colorManagement: true)
            ),
            requiredClientCapabilities: [],
            supportedCodecs: [.hevc],
            hostID: "host",
            hostName: "Mac",
            displayID: "display",
            displayName: "Display",
            displayIsVirtual: false
        ))
        var hello = VSClientHello()
        hello.supportedProtocols.minimum = 1
        hello.supportedProtocols.maximum = 1
        hello.capabilities = [.audio, .colorManagement]
        hello.codecs = [.hevc]
        hello.resourceLimits.maximumAudioStreams = 1
        _ = session.handleControl(try envelope(
            id: 1,
            sessionID: Data(),
            epoch: 0,
            payload: .clientHello(hello)
        ).serializedData())
        let helloResponses = try controls(session.completeCodecNegotiation())
        guard case .sessionAccepted(let accepted)? = helloResponses.last?.payload else {
            return XCTFail("expected SessionAccepted")
        }
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.audio))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumAudioStreams, 1)

        var start = VSStartDisplayRequest()
        start.mode = .existing
        start.sourceDisplayID = "display"
        let startResponses = try controls(session.handleControl(try envelope(
            id: 2,
            sessionID: sessionID,
            epoch: 9,
            payload: .startDisplayRequest(start)
        ).serializedData()))
        guard case .videoConfig(let video)? = startResponses.last?.payload else {
            return XCTFail("expected VideoConfig")
        }
        XCTAssertEqual(video.colorDescription, HostVideoColor.sdr)
        var videoResult = VSVideoConfigResult()
        videoResult.streamID = video.streamID
        videoResult.configEpoch = video.configEpoch
        videoResult.accepted = true
        let ready = try controls(session.handleControl(try envelope(
            id: 3,
            sessionID: sessionID,
            epoch: 9,
            payload: .videoConfigResult(videoResult)
        ).serializedData()))
        guard case .audioConfig(let audio)? = ready.first?.payload else {
            return XCTFail("expected AudioConfig")
        }
        let pcm = Data(repeating: 0, count: PCMAudioFormat.production.bytesPerPacket)
        XCTAssertNil(try session.makeAudioPacket(
            payload: pcm,
            frameCount: PCMAudioFormat.production.framesPerPacket
        ))
        var audioResult = VSAudioConfigResult()
        audioResult.streamID = audio.streamID
        audioResult.configEpoch = audio.configEpoch
        audioResult.accepted = true
        _ = session.handleControl(try envelope(
            id: 4,
            sessionID: sessionID,
            epoch: 9,
            payload: .audioConfigResult(audioResult)
        ).serializedData())
        XCTAssertNotNil(try session.makeAudioPacket(
            payload: pcm,
            frameCount: PCMAudioFormat.production.framesPerPacket
        ))
    }

    private func encodeVarint(_ value: Int) -> Data {
        var remaining = value
        var result = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining > 0 { byte |= 0x80 }
            result.append(byte)
        } while remaining > 0
        return result
    }

    private func envelope(
        id: UInt64,
        sessionID: Data,
        epoch: UInt64,
        payload: VSEnvelope.OneOf_Payload
    ) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = id
        envelope.sessionID = sessionID
        envelope.sessionEpoch = epoch
        envelope.payload = payload
        return envelope
    }

    private func controls(_ actions: [ProtocolV1SessionAction]) throws -> [VSEnvelope] {
        try actions.compactMap { action in
            guard case .sendControl(let data) = action else { return nil }
            return try VSEnvelope(serializedBytes: data)
        }
    }
}
