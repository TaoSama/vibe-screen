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
                colorManagement: false,
                hostActions: false,
                wakeHost: false
            )
        )
        XCTAssertTrue(capabilities.isSuperset(of: [.audio, .clipboard, .fileTransfer]))
        XCTAssertFalse(capabilities.contains(.colorManagement))
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

    func testBulkAdmissionIsBoundedAndZeroNonFinalChunkIsRejected() throws {
        let gate = BulkTransferAdmissionGate(maximumItems: 2, maximumBytes: 10)
        XCTAssertTrue(gate.admit(bytes: 4))
        XCTAssertTrue(gate.admit(bytes: 6))
        XCTAssertFalse(gate.admit(bytes: 1))
        XCTAssertEqual(gate.usage.items, 2)
        XCTAssertEqual(gate.usage.bytes, 10)
        gate.release(bytes: 4)
        XCTAssertTrue(gate.admit(bytes: 1))

        var header = VSFileChunkHeader()
        header.transferID = Data(repeating: 1, count: 16)
        header.sessionEpoch = 9
        header.chunkSha256 = Data(SHA256.hash(data: Data()))
        header.final = false
        let headerBytes = try header.serializedData()
        XCTAssertThrowsError(try HostFileChunk(
            serializedFrame: encodeVarint(headerBytes.count) + headerBytes,
            maximumChunkBytes: 64 * 1_024
        )) { error in
            XCTAssertEqual(error as? HostAdvancedAdapterError, .invalidFinalChunk)
        }
    }

    func testClipboardOfferRequestContentWorksInBothDirections() throws {
        let sessionID = Data(repeating: 0x42, count: 16)
        let session = ProtocolV1SessionCoordinator(configuration: .init(
            sessionID: sessionID,
            sessionEpoch: 7,
            displayWidth: 1280,
            displayHeight: 720,
            rotation: 0,
            framesPerSecond: 60,
            bitrateKbps: 10_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: false,
                advanced: .init(clipboard: true)
            ),
            requiredClientCapabilities: [],
            supportedCodecs: [.h264],
            hostID: "host",
            hostName: "Mac",
            displayID: "display",
            displayName: "Display",
            displayIsVirtual: false
        ))
        var hello = VSClientHello()
        hello.supportedProtocols.minimum = 1
        hello.supportedProtocols.maximum = 1
        hello.capabilities = [.clipboard]
        hello.codecs = [.h264]
        hello.resourceLimits.maximumClipboardBytes = 1_024
        _ = session.handleControl(try envelope(
            id: 1, sessionID: Data(), epoch: 0, payload: .clientHello(hello)
        ).serializedData())
        _ = session.completeCodecNegotiation()
        var start = VSStartDisplayRequest()
        start.mode = .existing
        start.sourceDisplayID = "display"
        let startResponses = try controls(session.handleControl(try envelope(
            id: 2, sessionID: sessionID, epoch: 7, payload: .startDisplayRequest(start)
        ).serializedData()))
        guard case .videoConfig(let video)? = startResponses.last?.payload else {
            return XCTFail("expected VideoConfig")
        }
        var result = VSVideoConfigResult()
        result.streamID = video.streamID
        result.configEpoch = video.configEpoch
        result.accepted = true
        _ = session.handleControl(try envelope(
            id: 3, sessionID: sessionID, epoch: 7, payload: .videoConfigResult(result)
        ).serializedData())

        let outgoing = clipboardContent(changeByte: 1, text: "host snapshot")
        guard case .clipboardOffer(let outgoingOffer)? = try controls(
            session.offerClipboard(outgoing)
        ).first?.payload else { return XCTFail("expected outgoing offer") }
        var request = VSClipboardRequest()
        request.changeID = outgoingOffer.changeID
        guard case .clipboardContent(let sentContent)? = try controls(session.handleControl(
            try envelope(
                id: 4, sessionID: sessionID, epoch: 7, payload: .clipboardRequest(request)
            ).serializedData()
        )).first?.payload else { return XCTFail("expected requested content") }
        XCTAssertEqual(sentContent, outgoing)

        let incoming = clipboardContent(changeByte: 2, text: "client snapshot")
        var incomingOffer = VSClipboardOffer()
        incomingOffer.changeID = incoming.changeID
        incomingOffer.originDeviceID = incoming.originDeviceID
        incomingOffer.mimeType = incoming.mimeType
        incomingOffer.byteLength = UInt64(incoming.content.count)
        incomingOffer.sha256 = incoming.sha256
        let offerActions = session.handleControl(try envelope(
            id: 5, sessionID: sessionID, epoch: 7, payload: .clipboardOffer(incomingOffer)
        ).serializedData())
        XCTAssertTrue(offerActions.contains {
            if case .clipboardOffer(let offer) = $0 { return offer == incomingOffer }
            return false
        })
        guard case .clipboardRequest(let approvedRequest)? = try controls(
            session.completeClipboardOffer(changeID: incoming.changeID, accepted: true)
        ).first?.payload else { return XCTFail("expected approved request") }
        XCTAssertEqual(approvedRequest.changeID, incoming.changeID)
        let contentActions = session.handleControl(try envelope(
            id: 6, sessionID: sessionID, epoch: 7, payload: .clipboardContent(incoming)
        ).serializedData())
        XCTAssertTrue(contentActions.contains {
            if case .clipboardContent(let content) = $0 { return content == incoming }
            return false
        })
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
        guard let firstPacket = try session.makeAudioPacket(
            payload: pcm,
            frameCount: PCMAudioFormat.production.framesPerPacket
        ) else { return XCTFail("expected first audio packet") }
        XCTAssertEqual(try ProtocolV1AudioPacketCodec.decode(firstPacket).header.sequence, 0)

        let reconfiguration = try controls(session.selectDisplayFromClient(displayID: ""))
        guard case .videoConfig(let nextVideo)? = reconfiguration.last?.payload else {
            return XCTFail("expected reconfigured VideoConfig")
        }
        XCTAssertGreaterThan(nextVideo.configEpoch, video.configEpoch)
        var nextVideoResult = VSVideoConfigResult()
        nextVideoResult.streamID = nextVideo.streamID
        nextVideoResult.configEpoch = nextVideo.configEpoch
        nextVideoResult.accepted = true
        let nextReady = try controls(session.handleControl(try envelope(
            id: 5,
            sessionID: sessionID,
            epoch: 9,
            payload: .videoConfigResult(nextVideoResult)
        ).serializedData()))
        guard case .audioConfig(let nextAudio)? = nextReady.first?.payload else {
            return XCTFail("expected second AudioConfig")
        }
        XCTAssertGreaterThan(nextAudio.configEpoch, audio.configEpoch)
        XCTAssertNil(try session.makeAudioPacket(
            payload: pcm,
            frameCount: PCMAudioFormat.production.framesPerPacket
        ))
        var nextAudioResult = VSAudioConfigResult()
        nextAudioResult.streamID = nextAudio.streamID
        nextAudioResult.configEpoch = nextAudio.configEpoch
        nextAudioResult.accepted = true
        _ = session.handleControl(try envelope(
            id: 6,
            sessionID: sessionID,
            epoch: 9,
            payload: .audioConfigResult(nextAudioResult)
        ).serializedData())
        guard let secondPacket = try session.makeAudioPacket(
            payload: pcm,
            frameCount: PCMAudioFormat.production.framesPerPacket
        ) else { return XCTFail("expected second-domain audio packet") }
        let secondHeader = try ProtocolV1AudioPacketCodec.decode(secondPacket).header
        XCTAssertEqual(secondHeader.configEpoch, nextAudio.configEpoch)
        XCTAssertEqual(secondHeader.sequence, 0)
    }

    func testColorFallbackRetriesOnlyOnceForAConfigurationGeneration() throws {
        let sessionID = Data(repeating: 0x51, count: 16)
        let session = ProtocolV1SessionCoordinator(configuration: .init(
            sessionID: sessionID,
            sessionEpoch: 11,
            displayWidth: 1920,
            displayHeight: 1080,
            rotation: 0,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            hostCapabilities: ProtocolV1SessionConfiguration.productionHostCapabilities(
                touchEnabled: false,
                advanced: .init(colorManagement: true)
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
        hello.capabilities = [.colorManagement]
        hello.codecs = [.hevc]
        _ = session.handleControl(try envelope(
            id: 1, sessionID: Data(), epoch: 0, payload: .clientHello(hello)
        ).serializedData())
        _ = session.completeCodecNegotiation()
        var start = VSStartDisplayRequest()
        start.mode = .existing
        start.sourceDisplayID = "display"
        let startResponses = try controls(session.handleControl(try envelope(
            id: 2, sessionID: sessionID, epoch: 11, payload: .startDisplayRequest(start)
        ).serializedData()))
        guard case .videoConfig(let initial)? = startResponses.last?.payload else {
            return XCTFail("expected VideoConfig")
        }
        var rejection = VSVideoConfigResult()
        rejection.streamID = initial.streamID
        rejection.configEpoch = initial.configEpoch
        rejection.accepted = false
        rejection.selectedColorDescription = HostVideoColor.sdr
        let fallbackResponses = try controls(session.handleControl(try envelope(
            id: 3, sessionID: sessionID, epoch: 11, payload: .videoConfigResult(rejection)
        ).serializedData()))
        guard case .videoConfig(let fallback)? = fallbackResponses.first?.payload else {
            return XCTFail("expected one SDR fallback")
        }
        XCTAssertGreaterThan(fallback.configEpoch, initial.configEpoch)
        rejection.configEpoch = fallback.configEpoch
        let secondRejection = try controls(session.handleControl(try envelope(
            id: 4, sessionID: sessionID, epoch: 11, payload: .videoConfigResult(rejection)
        ).serializedData()))
        XCTAssertFalse(secondRejection.contains {
            if case .videoConfig? = $0.payload { return true }
            return false
        })
        XCTAssertTrue(secondRejection.contains {
            if case .protocolError? = $0.payload { return true }
            return false
        })
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

    private func clipboardContent(changeByte: UInt8, text: String) -> VSClipboardContent {
        let data = Data(text.utf8)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: changeByte, count: 16)
        content.originDeviceID = changeByte == 1 ? "macos-host" : "ios-client"
        content.mimeType = "text/plain"
        content.content = data
        content.sha256 = Data(SHA256.hash(data: data))
        return content
    }

    private func controls(_ actions: [ProtocolV1SessionAction]) throws -> [VSEnvelope] {
        try actions.compactMap { action in
            guard case .sendControl(let data) = action else { return nil }
            return try VSEnvelope(serializedBytes: data)
        }
    }
}
