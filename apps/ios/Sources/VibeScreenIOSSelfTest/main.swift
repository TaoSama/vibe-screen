import CryptoKit
import Foundation
import Network
import VibeScreenCore
import VibeScreenProtocol
import VibeScreenVideo

enum SelfTestError: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case let .failed(message): message
        }
    }
}

@discardableResult
func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws -> Bool {
    guard try condition() else { throw SelfTestError.failed(message) }
    return true
}

func testFraming() throws {
    let first = try TransportFrame(channel: .control, payload: Data([1, 2, 3])).encoded()
    let second = try TransportFrame(channel: .video, payload: Data([4, 5])).encoded()
    var framer = TransportFramer()
    try require(try framer.append(first.prefix(2)).isEmpty, "split header emitted early")
    let frames = try framer.append(Data(first.dropFirst(2)) + second)
    try require(frames == [
        TransportFrame(channel: .control, payload: Data([1, 2, 3])),
        TransportFrame(channel: .video, payload: Data([4, 5])),
    ], "split/coalesced framing mismatch")
}

func testSessionAndProtobuf() throws {
    var state = SessionState()
    try state.beginConnection()
    try state.transportConnected()
    try state.accept(
        selectedProtocol: 1,
        sessionID: Data([0xaa]),
        epoch: 7,
        localCapabilities: [.touch, .keyboard, .sessionResume],
        hostCapabilities: [.touch, .pointer, .sessionResume]
    )
    try require(state.negotiatedCapabilities == [.touch, .sessionResume], "capability intersection")
    try require(state.accepts(epoch: 7), "current epoch rejected")
    try require(!state.accepts(epoch: 6), "stale epoch accepted")

    var factory = EnvelopeFactory()
    let hello = factory.clientHello(
        deviceID: "ios-selftest",
        deviceName: "iPad",
        capabilities: [.touch, .keyboard, .sessionResume],
        codecs: [.h264, .hevc]
    )
    let decoded = try VSEnvelope(serializedBytes: hello.serializedData())
    try require(decoded.protocolVersion == 1, "wrong protocol version")
    try require(decoded.clientHello.codecs == [.h264, .hevc], "codec round trip")

    var header = VSMediaPacketHeader()
    header.streamID = 3
    header.sessionEpoch = 7
    header.codec = .h264
    header.payloadLength = 2
    let headerBytes = try header.serializedData()
    var mediaBytes = encodeVarint(headerBytes.count)
    mediaBytes.append(headerBytes)
    mediaBytes.append(contentsOf: [0x65, 0x01])
    let packet = try MediaPacket(serializedFrame: mediaBytes)
    try require(packet.header.streamID == 3, "media header round trip")
    try require(packet.payload == Data([0x65, 0x01]), "media payload boundary")
}

func testSharedProtocolFixture() throws {
    let fixtureURL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("contracts/fixtures/client-hello-v1.hex")
    let hex = try String(contentsOf: fixtureURL, encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let bytes = try decodeHex(hex)
    let envelope = try VSEnvelope(serializedBytes: bytes)

    try require(envelope.protocolVersion == 1, "golden protocol version")
    try require(envelope.messageID == 1, "golden message ID")
    try require(envelope.clientHello.supportedProtocols.minimum == 1, "golden minimum protocol")
    try require(envelope.clientHello.supportedProtocols.maximum == 1, "golden maximum protocol")
    try require(envelope.clientHello.deviceID == "protocol-golden", "golden device ID")
    try require(envelope.clientHello.deviceName == "Vibe Screen", "golden device name")
    try require(envelope.clientHello.capabilities == [.touch, .keyboard, .pointer], "golden capabilities")
    try require(envelope.clientHello.codecs == [.h264, .hevc], "golden codecs")
    try require(envelope.clientHello.transports == [.lan], "golden transport")
}

func protocolV1FixtureDirectory() -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("contracts/fixtures/messages/v1/bin", isDirectory: true)
}

func readProtocolV1Fixture(_ name: String) throws -> Data {
    try Data(contentsOf: protocolV1FixtureDirectory().appendingPathComponent(name))
}

func testProtocolV1GoldenFixtures() throws {
    let controlFixtureNames = [
        "client_hello", "host_hello", "session_accepted",
        "list_displays_request", "list_displays_response",
        "start_display_request", "start_display_response",
        "video_config", "display_changed", "video_config_result", "touch", "ping", "pong",
        "protocol_error",
    ]
    var envelopes: [String: VSEnvelope] = [:]
    for name in controlFixtureNames {
        let expected = try readProtocolV1Fixture("\(name).binpb")
        let envelope = try VSEnvelope(serializedBytes: expected)
        try require(try envelope.serializedData() == expected, "Protocol v1 exact round trip: \(name)")
        envelopes[name] = envelope
    }

    guard let clientHello = envelopes["client_hello"]?.clientHello else {
        throw SelfTestError.failed("Protocol v1 client hello fixture missing")
    }
    try require(clientHello.requiredCapabilities == [.touch], "Protocol v1 required capabilities")
    try require(clientHello.capabilities == [.touch, .keyboard, .pointer, .telemetry], "Protocol v1 capabilities")
    try require(clientHello.videoDecodeCapabilities.map(\.codec) == [.hevc, .h264], "Protocol v1 decode codecs")

    guard let displayList = envelopes["list_displays_response"]?.listDisplaysResponse.displays.first else {
        throw SelfTestError.failed("Protocol v1 display list fixture missing")
    }
    try require(displayList.displayID == "display-main", "Protocol v1 display ID")
    try require(displayList.logicalSize.width == 1_920 && displayList.logicalSize.height == 1_080, "Protocol v1 display size")
    try require(displayList.scaleFactor == 2 && displayList.isPrimary, "Protocol v1 display attributes")

    guard let startRequest = envelopes["start_display_request"]?.payload,
          case let .startDisplayRequest(request) = startRequest else {
        throw SelfTestError.failed("Protocol v1 start display request fixture missing")
    }
    try require(request.mode == .existing, "Protocol v1 start display mode")
    try require(request.sourceDisplayID == displayList.displayID, "Protocol v1 start display source")
    guard let startResponse = envelopes["start_display_response"]?.payload,
          case let .startDisplayResponse(response) = startResponse else {
        throw SelfTestError.failed("Protocol v1 start display response fixture missing")
    }
    try require(response.accepted && response.streamID == 42, "Protocol v1 start display response")
    try require(response.display.displayID == displayList.displayID, "Protocol v1 started display")

    guard let videoConfigPayload = envelopes["video_config"]?.payload,
          case let .videoConfig(videoConfig) = videoConfigPayload else {
        throw SelfTestError.failed("Protocol v1 video config fixture missing")
    }
    try require(videoConfig.configEpoch == 3 && videoConfig.streamID == 42, "Protocol v1 video routing")
    try require(videoConfig.codec == .hevc && videoConfig.framesPerSecond == 60, "Protocol v1 video format")
    try require(videoConfig.encodedSize.width == 1_920 && videoConfig.encodedSize.height == 1_080, "Protocol v1 video size")
    try require(videoConfig.rotationDegrees == 90, "Protocol v1 initial rotation")
    guard let displayChangedPayload = envelopes["display_changed"]?.payload,
          case let .displayChanged(displayChanged) = displayChangedPayload else {
        throw SelfTestError.failed("Protocol v1 display changed fixture missing")
    }
    try require(displayChanged.rotationDegrees == 270, "Protocol v1 runtime rotation")
    guard let videoResultPayload = envelopes["video_config_result"]?.payload,
          case let .videoConfigResult(videoResult) = videoResultPayload else {
        throw SelfTestError.failed("Protocol v1 video config result fixture missing")
    }
    try require(videoResult.accepted && videoResult.configEpoch == 3, "Protocol v1 video result")
    try require(videoResult.streamID == videoConfig.streamID, "Protocol v1 video result routing")

    guard let touchPayload = envelopes["touch"]?.payload,
          case let .touchEvent(touch) = touchPayload else {
        throw SelfTestError.failed("Protocol v1 touch fixture missing")
    }
    try require(touch.inputID == 100 && touch.pointerID == 1 && touch.phase == .began, "Protocol v1 touch identity")
    try require(touch.position.x == 0.25 && touch.position.y == 0.75, "Protocol v1 touch position")
    try require(touch.target.displayID == displayList.displayID && touch.target.streamID == 42, "Protocol v1 touch target")

    let expectedHeader = try readProtocolV1Fixture("media_packet_header.binpb")
    let expectedPacket = try readProtocolV1Fixture("media_packet.bin")
    let mediaPacket = try MediaPacket(serializedFrame: expectedPacket)
    let serializedHeader = try mediaPacket.header.serializedData()
    try require(serializedHeader == expectedHeader, "Protocol v1 media header exact round trip")
    try require(mediaPacket.header.streamID == 42 && mediaPacket.header.sessionEpoch == 7, "Protocol v1 media session routing")
    try require(mediaPacket.header.configEpoch == 3 && mediaPacket.header.codec == .hevc, "Protocol v1 media config")
    try require(mediaPacket.header.keyframe && mediaPacket.header.fragmentCount == 1, "Protocol v1 media frame metadata")
    var rebuiltPacket = encodeVarint(serializedHeader.count)
    rebuiltPacket.append(serializedHeader)
    rebuiltPacket.append(mediaPacket.payload)
    try require(rebuiltPacket == expectedPacket, "Protocol v1 media packet exact reconstruction")

    try require(try readProtocolV1Fixture("upgrade_offer.bin") == Data([0x0d]), "Protocol v1 upgrade offer")
    try require(
        try readProtocolV1Fixture("upgrade_acknowledgement.bin") == Data([0x0d, 0x01]),
        "Protocol v1 upgrade acknowledgement"
    )
}

func decodeHex(_ hex: String) throws -> Data {
    try require(hex.count.isMultiple(of: 2), "golden hex has odd length")
    var bytes = Data()
    var index = hex.startIndex
    while index < hex.endIndex {
        let end = hex.index(index, offsetBy: 2)
        guard let byte = UInt8(hex[index..<end], radix: 16) else {
            throw SelfTestError.failed("golden hex contains invalid byte")
        }
        bytes.append(byte)
        index = end
    }
    return bytes
}

func encodeVarint(_ value: Int) -> Data {
    var remaining = value
    var bytes = Data()
    repeat {
        var byte = UInt8(remaining & 0x7f)
        remaining >>= 7
        if remaining != 0 { byte |= 0x80 }
        bytes.append(byte)
    } while remaining != 0
    return bytes
}

func testBackpressureAndCodecParsing() throws {
    let backoff = ReconnectBackoff()
    try require(backoff.delaySeconds(forAttempt: 0) == 0.25, "initial reconnect delay")
    try require(
        backoff.delaySeconds(forAttempt: 99) == ReconnectBackoff.maximumDelaySeconds,
        "reconnect delay is not bounded"
    )

    let accessUnit = Data([0, 0, 1, 0x67, 1, 0, 0, 1, 0x68, 2, 0, 0, 1, 0x65, 3])
    try require(VideoDecoder.parameterSets(codec: .h264, from: accessUnit) == [
        Data([0x67, 1]),
        Data([0x68, 2]),
    ], "H.264 parameter-set extraction")
    try require(AnnexB.lengthPrefixedSample(from: accessUnit) == Data([
        0, 0, 0, 2, 0x67, 1,
        0, 0, 0, 2, 0x68, 2,
        0, 0, 0, 2, 0x65, 3,
    ]), "Annex-B conversion")
}

func testMultiDisplaySessions() throws {
    var registry = MultiDisplaySessionRegistry(maximumClients: 2, maximumStreamsPerClient: 2)
    let first = ClientSessionKey(sessionID: Data([1]), epoch: 1)
    let second = ClientSessionKey(sessionID: Data([2]), epoch: 4)
    try registry.register(first)
    try registry.register(second)
    try registry.bind(DisplayStreamBinding(displayID: "main", streamID: 10), to: first)
    try registry.bind(DisplayStreamBinding(displayID: "aux", streamID: 11), to: first)
    try require(registry.binding(streamID: 10, in: first)?.displayID == "main", "stream route")
    do {
        try registry.bind(DisplayStreamBinding(displayID: "third", streamID: 12), to: first)
        throw SelfTestError.failed("stream limit not enforced")
    } catch SessionRegistryError.streamLimitReached { }
    let newEpoch = ClientSessionKey(sessionID: Data([1]), epoch: 2)
    try registry.register(newEpoch)
    try require(registry.bindings(in: first).isEmpty, "old epoch resources survived")
    try require(registry.activeClientCount == 2, "client count after epoch replacement")
}

func testAudioQueue() throws {
    var config = VSAudioConfig()
    config.streamID = 7
    config.configEpoch = 2
    config.codec = .pcmS16Le
    config.sampleRateHz = 48_000
    config.channelCount = 2
    config.framesPerPacket = 4
    let format = try PCMStreamFormat(config: config)
    let payload = Data(repeating: 0x01, count: format.bytesPerPacket)
    func packet(sequence: UInt64) throws -> AudioPacket {
        var header = VSAudioPacketHeader()
        header.streamID = 7
        header.sessionEpoch = 9
        header.configEpoch = 2
        header.sequence = sequence
        header.frameCount = 4
        header.payloadLength = UInt32(payload.count)
        let bytes = try header.serializedData()
        return try AudioPacket(serializedFrame: encodeVarint(bytes.count) + bytes + payload)
    }
    var jitter = AudioJitterBuffer(firstSequence: 0, maximumPackets: 3)
    _ = try jitter.enqueue(packet(sequence: 1), sessionEpoch: 9, configEpoch: 2, format: format)
    _ = try jitter.enqueue(packet(sequence: 0), sessionEpoch: 9, configEpoch: 2, format: format)
    try require(jitter.drainReady().map(\.header.sequence) == [0, 1], "audio reorder")
    try require(
        jitter.enqueue(packet(sequence: 0), sessionEpoch: 9, configEpoch: 2, format: format) == .stale,
        "late audio packet"
    )
    for sequence in 5...9 {
        _ = try jitter.enqueue(packet(sequence: UInt64(sequence)), sessionEpoch: 9, configEpoch: 2, format: format)
    }
    try require(jitter.queuedPacketCount <= 3, "audio queue exceeded bound")
}

func testClipboardAndManagedPolicy() throws {
    let managed = try ManagedPolicy(managedConfiguration: [
        "ClipboardAllowed": true,
        "FileTransferAllowed": false,
        "AudioAllowed": true,
        "WakeAllowed": false,
        "CustomGesturesAllowed": true,
        "MaximumFileBytes": 1_024,
        "AllowedHosts": ["mac.local"],
    ])
    try require(managed.isManaged && !managed.fileTransferAllowed, "managed deny")
    try require(managed.allowedHosts == ["mac.local"], "managed host list")
    let denyWins = managed.applying(remote: ManagedPolicy(
        isManaged: true,
        clipboardAllowed: false,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        maximumFileBytes: 4_096,
        allowedHosts: ["mac.local", "other"]
    ))
    try require(!denyWins.clipboardAllowed && !denyWins.fileTransferAllowed, "managed deny-wins")

    var clipboard = ClipboardTransferCoordinator(maximumBytes: 32)
    let outgoing = try clipboard.prepareOutgoing(
        content: Data("hello".utf8),
        mimeType: "text/plain",
        originDeviceID: "ios",
        operation: .userInitiatedSend,
        policy: .unmanaged
    )
    do {
        _ = try clipboard.acceptIncoming(
            outgoing,
            operation: .userApprovedReceive,
            policy: .unmanaged
        )
        throw SelfTestError.failed("clipboard feedback loop accepted")
    } catch ClipboardTransferError.feedbackLoop { }
    var remote = outgoing
    remote.changeID = Data([9])
    remote.originDeviceID = "mac"
    let accepted = try clipboard.acceptIncoming(
        remote,
        operation: .userApprovedReceive,
        policy: .unmanaged
    )
    try require(accepted.content == Data("hello".utf8), "clipboard content")
    remote.changeID = Data([10])
    remote.sha256 = Data(repeating: 0, count: 32)
    do {
        _ = try clipboard.acceptIncoming(remote, operation: .userApprovedReceive, policy: .unmanaged)
        throw SelfTestError.failed("clipboard bad digest accepted")
    } catch ClipboardTransferError.digestMismatch { }
}

func testFileTransfer() throws {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent("vibescreen-selftest-\(UUID().uuidString)", isDirectory: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let manager = try IncomingFileTransferManager(
        policy: FileTransferPolicy(
            maximumFileBytes: 32,
            maximumChunkBytes: 3,
            maximumConcurrentTransfers: 1,
            maximumTotalTemporaryBytes: 32
        ),
        directory: directory
    )
    let content = Data("hello".utf8)
    var offer = VSFileOffer()
    offer.transferID = Data([1])
    offer.fileName = "hello.txt"
    offer.mimeType = "text/plain"
    offer.byteLength = UInt64(content.count)
    offer.sha256 = Data(SHA256.hash(data: content))
    let decision = try manager.accept(offer, managedPolicy: .unmanaged)
    try require(decision.accepted && decision.maximumChunkBytes == 3, "file accept")
    func chunk(offset: UInt64, data: Data) throws -> FileChunk {
        var header = VSFileChunkHeader()
        header.transferID = offer.transferID
        header.offset = offset
        header.payloadLength = UInt32(data.count)
        header.chunkSha256 = Data(SHA256.hash(data: data))
        header.final = offset + UInt64(data.count) == offer.byteLength
        let bytes = try header.serializedData()
        return try FileChunk(serializedFrame: encodeVarint(bytes.count) + bytes + data)
    }
    _ = try manager.append(chunk(offset: 0, data: content.prefix(3)))
    do {
        _ = try manager.append(chunk(offset: 4, data: content.suffix(2)))
        throw SelfTestError.failed("file offset gap accepted")
    } catch FileTransferError.unexpectedOffset { }
    _ = try manager.append(chunk(offset: 3, data: content.suffix(2)))
    let completed = try manager.finish(transferID: offer.transferID)
    try require(try Data(contentsOf: completed.stagingURL) == content, "file staging content")
    try require(manager.activeTransferCount == 0, "file resources released")
    try require(!IncomingFileTransferManager.isSafeFileName("../escape"), "unsafe filename")

    var validFrame = try chunk(offset: 0, data: content.prefix(3)).serializedFrame()
    validFrame[validFrame.index(before: validFrame.endIndex)] ^= 0xff
    do {
        _ = try FileChunk(serializedFrame: validFrame)
        throw SelfTestError.failed("file chunk digest mismatch accepted")
    } catch FileTransferError.chunkDigestMismatch { }

    var cancelledOffer = offer
    cancelledOffer.transferID = Data([2])
    _ = try manager.accept(cancelledOffer, managedPolicy: .unmanaged)
    var overflowOffer = offer
    overflowOffer.transferID = Data([3])
    do {
        _ = try manager.accept(overflowOffer, managedPolicy: .unmanaged)
        throw SelfTestError.failed("file concurrency limit not enforced")
    } catch FileTransferError.concurrentLimitReached { }
    manager.cancel(transferID: cancelledOffer.transferID)
    try require(manager.activeTransferCount == 0, "file cancel cleanup")
}

func testHDRGesturesAndWake() throws {
    var capability = VSVideoDecodeCapability()
    capability.codec = .h264
    capability.maximumWidth = 1_920
    capability.maximumHeight = 1_080
    capability.maximumFramesPerSecond = 60
    capability.bitDepths = [8]
    capability.transferFunctions = [.bt709]
    var request = VSVideoConfig()
    request.configEpoch = 4
    request.codec = .hevc
    request.encodedSize.width = 1_920
    request.encodedSize.height = 1_080
    request.framesPerSecond = 60
    request.colorDescription.bitDepth = 10
    request.colorDescription.primaries = .bt2020
    request.colorDescription.transferFunction = .pq
    switch VideoColorNegotiator(decodeCapabilities: [capability]).evaluate(request) {
    case .accepted:
        throw SelfTestError.failed("unsupported HDR accepted")
    case let .fallback(config, _):
        try require(config.codec == .h264, "HDR codec fallback")
        try require(config.colorDescription.bitDepth == 8, "HDR bit-depth fallback")
        try require(config.configEpoch == 5, "fallback config epoch")
    }

    let profile = GestureProfile(mappings: [
        GestureMapping(trigger: .doubleTap, action: .invokeHostAction("move-window")),
    ])
    let encoded = try JSONEncoder().encode(profile)
    try require(try JSONDecoder().decode(GestureProfile.self, from: encoded) == profile, "gesture persistence")
    _ = try profile.validated(availableHostActions: ["move-window"], policy: .unmanaged)
    do {
        _ = try profile.validated(availableHostActions: [], policy: .unmanaged)
        throw SelfTestError.failed("unknown host action accepted")
    } catch GestureMappingError.unavailableHostAction { }

    let packet = try WakeOnLAN.magicPacket(
        macAddress: "00:11:22:33:44:55",
        isPaired: true,
        policy: .unmanaged
    )
    try require(packet.count == 102, "Wake-on-LAN packet length")
    try require(packet.prefix(6) == Data(repeating: 0xff, count: 6), "Wake-on-LAN prefix")
}

func testAdvancedProtocolRoundTrip() throws {
    var offer = VSFileOffer()
    offer.transferID = Data([1, 2])
    offer.fileName = "report.pdf"
    offer.byteLength = 42
    var envelope = VSEnvelope()
    envelope.protocolVersion = 1
    envelope.fileOffer = offer
    let decoded = try VSEnvelope(serializedBytes: envelope.serializedData())
    try require(decoded.fileOffer.fileName == "report.pdf", "advanced envelope round trip")
    try require(VSCapability.managedConfiguration.rawValue == 22, "capability allocation")
}

func testTrustedLANStartupCodecs() throws {
    let encodedToken = String(repeating: "A", count: 43)
    let pairing = try TrustedLANPairing(
        urlString: "telemachus://127.0.0.1?t=\(encodedToken)&name=Test%20Mac"
    )
    try require(pairing.host == "127.0.0.1", "pairing host")
    try require(pairing.port == 54_321, "pairing default port")
    try require(pairing.token == Data(repeating: 0, count: 32), "pairing token")
    try require(pairing.hostName == "Test Mac", "pairing host name")

    do {
        _ = try TrustedLANPairing(
            urlString: "telemachus://127.0.0.1:54321?t=\(encodedToken)&t=\(encodedToken)&name=Mac"
        )
        throw SelfTestError.failed("duplicate pairing token accepted")
    } catch TrustedLANPairingError.invalidQuery { }
    do {
        _ = try TrustedLANPairing(
            urlString: "http://127.0.0.1:54321?t=\(encodedToken)&name=Mac"
        )
        throw SelfTestError.failed("wrong pairing scheme accepted")
    } catch TrustedLANPairingError.invalidScheme { }

    let request = try TrustedLANHandshake.request(token: pairing.token, deviceName: "iPhone")
    try require(request.prefix(4) == Data("SSWA".utf8), "SSWA request magic")
    try require(request.count == 37 + "iPhone".utf8.count, "SSWA request boundary")
    try require(request[36] == UInt8("iPhone".utf8.count), "SSWA device name length")
    try TrustedLANHandshake.validateResponse(Data("SSWR".utf8) + Data([0]))
    do {
        try TrustedLANHandshake.validateResponse(Data("SSWR".utf8) + Data([1]))
        throw SelfTestError.failed("SSWR rejection accepted")
    } catch TrustedLANHandshakeError.rejected(.invalidToken) { }
    do {
        try TrustedLANHandshake.validateResponse(Data("SSWX".utf8) + Data([0]))
        throw SelfTestError.failed("invalid SSWR magic accepted")
    } catch TrustedLANHandshakeError.invalidResponseMagic { }
    do {
        try TrustedLANHandshake.validateResponse(Data("SSWR".utf8))
        throw SelfTestError.failed("truncated SSWR accepted")
    } catch TrustedLANHandshakeError.invalidResponseLength { }

    try ProtocolV1Upgrade.validateAcknowledgement(Data([0x0D, 0x01]))
    do {
        try ProtocolV1Upgrade.validateAcknowledgement(Data([0x0D, 0x00]))
        throw SelfTestError.failed("invalid Protocol v1 acknowledgement accepted")
    } catch ProtocolV1UpgradeError.invalidAcknowledgement { }

    var factory = EnvelopeFactory(firstMessageID: 20)
    let ping = factory.ping(sequence: 7, sessionID: Data([1]), sessionEpoch: 3)
    let pong = factory.pong(
        sequence: 7,
        correlationID: ping.messageID,
        sessionID: Data([1]),
        sessionEpoch: 3
    )
    try require(ping.messageID == 20 && ping.ping.sequence == 7, "ping factory")
    try require(pong.messageID == 21 && pong.pong.sequence == 7, "pong factory message ID")
    try require(pong.correlationID == ping.messageID, "pong correlation")
    let disconnect = factory.disconnectNotice(
        reasonCode: "client_disconnect",
        mayResume: false,
        sessionID: Data([1]),
        sessionEpoch: 3
    )
    try require(
        disconnect.messageID == 22 && disconnect.disconnectNotice.reasonCode == "client_disconnect",
        "disconnect factory"
    )

    let sessionID = Data([0xAA])
    var validator = ClientControlEnvelopeValidator()
    var hostHello = VSEnvelope()
    hostHello.protocolVersion = 1
    hostHello.messageID = 1
    hostHello.hostHello.selectedProtocol = 1
    try validator.validate(hostHello)

    var accepted = VSSessionAccepted()
    accepted.sessionID = sessionID
    accepted.sessionEpoch = 7
    var acceptedEnvelope = VSEnvelope()
    acceptedEnvelope.protocolVersion = 1
    acceptedEnvelope.messageID = 2
    acceptedEnvelope.sessionID = sessionID
    acceptedEnvelope.sessionEpoch = 7
    acceptedEnvelope.sessionAccepted = accepted
    try validator.validate(acceptedEnvelope)

    var validPong = VSEnvelope()
    validPong.protocolVersion = 1
    validPong.messageID = 3
    validPong.sessionID = sessionID
    validPong.sessionEpoch = 7
    validPong.pong.sequence = 1
    try validator.validate(validPong)

    var duplicate = validPong
    duplicate.messageID = 3
    do {
        try validator.validate(duplicate)
        throw SelfTestError.failed("non-monotonic host message accepted")
    } catch ClientControlEnvelopeError.nonMonotonicMessageID { }

    var stale = validPong
    stale.messageID = 4
    stale.sessionEpoch = 6
    do {
        try validator.validate(stale)
        throw SelfTestError.failed("stale host session accepted")
    } catch ClientControlEnvelopeError.invalidSession { }

    var invalidState = SessionState()
    try invalidState.beginConnection()
    try invalidState.transportConnected()
    do {
        try invalidState.accept(
            selectedProtocol: 1,
            sessionID: Data(),
            epoch: 0,
            localCapabilities: [],
            hostCapabilities: []
        )
        throw SelfTestError.failed("empty host session accepted")
    } catch SessionStateError.invalidSessionIdentifier { }
}

func testTransportStartupCancellation() throws {
    let queue = DispatchQueue(label: "vibescreen-ios-selftest.transport")
    let listener = try NWListener(using: .tcp, on: .any)
    defer { listener.cancel() }
    let listenerReady = DispatchSemaphore(value: 0)
    let accepted = DispatchSemaphore(value: 0)
    listener.stateUpdateHandler = { state in
        if case .ready = state { listenerReady.signal() }
    }
    listener.newConnectionHandler = { connection in
        connection.start(queue: queue)
        accepted.signal()
    }
    listener.start(queue: queue)
    guard listenerReady.wait(timeout: .now() + 2) == .success,
          let port = listener.port?.rawValue else {
        throw SelfTestError.failed("transport cancellation listener did not start")
    }

    let transport = TCPTransport { _ in }
    let completed = DispatchSemaphore(value: 0)
    let result = LockedTransportResult()
    Task {
        do {
            try await transport.connect(
                host: "127.0.0.1",
                port: port,
                startup: .usbNoAuthentication,
                timeout: 5
            )
            result.finish(.success(()))
        } catch {
            result.finish(.failure(error))
        }
        completed.signal()
    }
    guard accepted.wait(timeout: .now() + 2) == .success else {
        throw SelfTestError.failed("transport cancellation connection was not accepted")
    }
    transport.disconnect()
    guard completed.wait(timeout: .now() + 2) == .success else {
        throw SelfTestError.failed("disconnect left transport startup suspended")
    }
    if case .success? = result.value {
        throw SelfTestError.failed("disconnected transport startup succeeded")
    }

    let cancelledTransport = TCPTransport { _ in }
    let cancelledCompleted = DispatchSemaphore(value: 0)
    let cancelledResult = LockedTransportResult()
    let task = Task {
        do {
            try await cancelledTransport.connect(
                host: "127.0.0.1",
                port: port,
                startup: .usbNoAuthentication,
                timeout: 5
            )
            cancelledResult.finish(.success(()))
        } catch {
            cancelledResult.finish(.failure(error))
        }
        cancelledCompleted.signal()
    }
    guard accepted.wait(timeout: .now() + 2) == .success else {
        throw SelfTestError.failed("cancelled transport connection was not accepted")
    }
    task.cancel()
    guard cancelledCompleted.wait(timeout: .now() + 2) == .success else {
        throw SelfTestError.failed("Task cancellation left transport startup suspended")
    }
    if case .success? = cancelledResult.value {
        throw SelfTestError.failed("cancelled transport startup succeeded")
    }
}

private final class LockedTransportResult: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Result<Void, Error>?

    var value: Result<Void, Error>? { lock.withLock { stored } }

    func finish(_ result: Result<Void, Error>) {
        lock.withLock { stored = result }
    }
}

do {
    FileHandle.standardError.write(Data("RUN: framing\n".utf8))
    try testFraming()
    FileHandle.standardError.write(Data("RUN: protocol/session\n".utf8))
    try testSessionAndProtobuf()
    try testSharedProtocolFixture()
    try testProtocolV1GoldenFixtures()
    FileHandle.standardError.write(Data("RUN: codec/backoff\n".utf8))
    try testBackpressureAndCodecParsing()
    FileHandle.standardError.write(Data("RUN: multi-display/audio\n".utf8))
    try testMultiDisplaySessions()
    try testAudioQueue()
    FileHandle.standardError.write(Data("RUN: clipboard/file/policy\n".utf8))
    try testClipboardAndManagedPolicy()
    try testFileTransfer()
    FileHandle.standardError.write(Data("RUN: HDR/gesture/wake/advanced-proto\n".utf8))
    try testHDRGesturesAndWake()
    try testAdvancedProtocolRoundTrip()
    FileHandle.standardError.write(Data("RUN: trusted-LAN startup codecs\n".utf8))
    try testTrustedLANStartupCodecs()
    try testTransportStartupCancellation()
    print("PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup")
} catch {
    FileHandle.standardError.write(Data("FAIL: \(error)\n".utf8))
    exit(EXIT_FAILURE)
}
