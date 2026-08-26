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

private enum RejectedControlEnvelope: Error {
    case release
}

private final class LockedControlRecords: @unchecked Sendable {
    private let lock = NSLock()
    private var records: [(messageID: UInt64, payload: String)] = []

    func append(_ record: (messageID: UInt64, payload: String)) {
        lock.withLock { records.append(record) }
    }

    var snapshot: [(messageID: UInt64, payload: String)] {
        lock.withLock { records }
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

    var missingDependencies = SessionState()
    try missingDependencies.beginConnection()
    try missingDependencies.transportConnected()
    try missingDependencies.accept(
        selectedProtocol: 1,
        sessionID: Data([0xbb]),
        epoch: 8,
        localCapabilities: [.touch, .usbHidModifierByte, .stylusExtended],
        hostCapabilities: [.touch, .usbHidModifierByte, .stylusExtended]
    )
    try require(
        missingDependencies.negotiatedCapabilities == [.touch],
        "capability dependency filtering"
    )

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

func testUSBHIDModifierCompatibility() throws {
    try require(VSCapability.usbHidModifierByte.rawValue == 27, "modifier capability allocation")
    try require(VSCapability.peripheralInputFramework.rawValue == 30, "peripheral framework capability allocation")
    try require(
        USBHIDModifierWire.encode(standardMask: 0x01, standardByteNegotiated: true) == 0x01,
        "new-new Control layout"
    )
    try require(
        USBHIDModifierWire.encode(standardMask: 0x02, standardByteNegotiated: true) == 0x02,
        "new-new Shift layout"
    )
    try require(
        USBHIDModifierWire.encode(standardMask: 0x01, standardByteNegotiated: false) == 0x02,
        "new-old Control fallback"
    )
    try require(
        USBHIDModifierWire.encode(standardMask: 0x02, standardByteNegotiated: false) == 0x01,
        "new-old Shift fallback"
    )
    try require(
        USBHIDModifierWire.encode(standardMask: 0xF0, standardByteNegotiated: false) == 0x0F,
        "legacy right-side collapse"
    )
    try require(
        USBHIDModifierWire.encode(standardMask: 0x100, standardByteNegotiated: true) == nil,
        "reserved modifier bit accepted"
    )
}

func testNativeInputAndBoundedReconnect() throws {
    try require(
        !SessionClosureContext.manualDisconnect.reportsEnqueueErrors
            && SessionClosureContext.manualDisconnect.clearsErrorOnCompletion
            && SessionClosureContext.manualDisconnect.shouldEnqueueDisconnectNotice(
                hasSession: true,
                allReleasesAdmitted: false
            ),
        "manual disconnect error policy"
    )
    try require(
        SessionClosureContext.sessionFailure.reportsEnqueueErrors
            && !SessionClosureContext.sessionFailure.clearsErrorOnCompletion,
        "failure-session error policy"
    )
    try require(
        SessionClosureContext.manualDisconnect.errorOnCompletion(
            currentError: "release enqueue failed"
        ) == nil,
        "manual disconnect retained an enqueue error"
    )
    try require(
        SessionClosureContext.sessionFailure.errorOnCompletion(
            currentError: "transport failed"
        ) == "transport failed",
        "non-manual closure suppressed its error"
    )
    try require(
        SessionClosureContext.sessionFailure.errorAfterEnqueueFailure(
            currentError: "video stream ended",
            enqueueError: "queue inactive"
        ) == "video stream ended",
        "disconnect enqueue failure replaced the primary session error"
    )
    try require(
        SessionClosureContext.sessionFailure.errorAfterEnqueueFailure(
            currentError: nil,
            enqueueError: "queue inactive"
        ) == "queue inactive",
        "disconnect enqueue failure was not reported without a primary error"
    )
    try require(
        NativeInputAvailability(keyboard: true, pointer: true).advertisedCapabilities
            == [.touch, .keyboard, .pointer, .usbHidModifierByte],
        "native input capability declaration"
    )

    let voiceOverMask = USBHIDModifierWire.leftControl | USBHIDModifierWire.leftOption
    try require(
        NativeKeyCapturePolicy.ignoresVoiceOverChord(
            standardModifierMask: voiceOverMask,
            voiceOverRunning: true
        ),
        "VoiceOver Control+Option chord captured"
    )
    try require(
        !NativeKeyCapturePolicy.ignoresVoiceOverChord(
            standardModifierMask: voiceOverMask,
            voiceOverRunning: false
        ),
        "Control+Option ignored while VoiceOver is off"
    )
    try require(
        NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voiceOverMask,
            voiceOverRunning: true,
            pressed: true,
            keyWasCaptured: false
        ),
        "uncaptured VoiceOver key-down was forwarded"
    )
    try require(
        NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voiceOverMask,
            voiceOverRunning: true,
            pressed: false,
            keyWasCaptured: false
        ),
        "uncaptured VoiceOver key-up was forwarded"
    )

    var keyboardState = PressedKeyboardInputState()
    try require(
        !keyboardState.enqueuePress(
            usbHIDUsage: 0x04,
            wireModifierMask: USBHIDModifierWire.leftShift
        ) { false },
        "failed key press enqueue changed state"
    )
    try require(keyboardState.pressedKeys.isEmpty, "failed key press became active")
    try require(
        keyboardState.enqueuePress(
            usbHIDUsage: 0x04,
            wireModifierMask: USBHIDModifierWire.leftShift
        ) { true },
        "successful key press enqueue rejected"
    )
    try require(keyboardState.contains(usbHIDUsage: 0x04), "captured key lookup failed")
    try require(
        !NativeKeyCapturePolicy.shouldIgnoreEvent(
            standardModifierMask: voiceOverMask,
            voiceOverRunning: true,
            pressed: false,
            keyWasCaptured: keyboardState.contains(usbHIDUsage: 0x04)
        ),
        "VoiceOver chord swallowed an already captured key-up"
    )
    try require(
        !keyboardState.enqueueRelease(usbHIDUsage: 0x04) { key in
            key.wireModifierMask == USBHIDModifierWire.leftShift && false
        },
        "failed key release enqueue changed state"
    )
    try require(keyboardState.pressedKeys.count == 1, "failed key release cleared active state")
    try require(
        keyboardState.enqueueRelease(usbHIDUsage: 0x04) { key in
            key.wireModifierMask == USBHIDModifierWire.leftShift
        },
        "successful key release lost press-time modifier"
    )
    try require(keyboardState.pressedKeys.isEmpty, "successful key release stayed active")
    try require(!keyboardState.contains(usbHIDUsage: 0x04), "released key remained captured")

    try require(
        try NativeInputTargetResolver.target(selectedStreamID: nil, bindings: []) == nil,
        "unselected input unexpectedly required a target"
    )
    let routedTarget = try NativeInputTargetResolver.target(
        selectedStreamID: 7,
        bindings: [DisplayStreamBinding(displayID: "display-1", streamID: 7)]
    )
    try require(
        routedTarget?.displayID == "display-1" && routedTarget?.streamID == 7,
        "selected input target was not resolved"
    )
    do {
        _ = try NativeInputTargetResolver.target(
            selectedStreamID: 8,
            bindings: [DisplayStreamBinding(displayID: "display-1", streamID: 7)]
        )
        throw SelfTestError.failed("selected stream without a binding routed untargeted input")
    } catch NativeInputTargetError.selectedStreamBindingMissing(8) { }

    let position = NormalizedInputPosition(x: 0.25, y: 0.75)
    var continuousState = ContinuousInputState()
    try require(
        continuousState.enqueueUpdate(position: position) { phase, _ in phase == .began },
        "continuous input press enqueue failed"
    )
    try require(
        !continuousState.enqueueTerminal { _ in false } && continuousState.isActive,
        "failed continuous release cleared active state"
    )
    try require(
        continuousState.enqueueTerminal { _ in true } && !continuousState.isActive,
        "successful continuous release stayed active"
    )

    var coordinator = ReconnectCoordinator()
    let generation = coordinator.start()
    let delays = (0..<5).compactMap { _ in
        coordinator.schedule(generation: generation, failure: .transientTransport)?.delaySeconds
    }
    try require(delays == [0.25, 0.5, 1, 2, 3], "bounded reconnect schedule")
    try require(
        coordinator.schedule(generation: generation, failure: .heartbeat) == nil,
        "reconnect exceeded attempt bound"
    )

    var permanentCoordinator = ReconnectCoordinator()
    let permanentGeneration = permanentCoordinator.start()
    try require(
        permanentCoordinator.schedule(generation: permanentGeneration, failure: .permanent) == nil,
        "permanent failure scheduled reconnect"
    )
    try require(
        !permanentCoordinator.accepts(generation: permanentGeneration),
        "permanent failure left reconnect enabled"
    )
    try require(
        ReconnectFailure.classify(TCPTransportError.connectionClosed) == .transientTransport,
        "transport failure was not retryable"
    )
    try require(
        ReconnectFailure.classify(TCPTransportError.authenticationRequired) == .permanent,
        "authentication failure was retryable"
    )
}

@MainActor
func testPartialReleaseFailureStillFlushesDisconnectNotice() async throws {
    let records = LockedControlRecords()
    let owner = SessionOwner(connectionOwner: ConnectionOwner())
    let sessionID = Data([0x52])
    let outbox = ControlOutbox { _, frame, _ in
        let envelope = try EnvelopeCodec.deserialize(frame.payload)
        let payload: String
        switch envelope.payload {
        case .keyEvent(let event) where !event.pressed:
            payload = "key-up"
        case .disconnectNotice:
            payload = "disconnect"
        default:
            payload = "unexpected"
        }
        records.append((envelope.messageID, payload))
    }
    outbox.activate(owner: owner)

    let admittedRelease = try outbox.enqueue(owner: owner) { factory in
        factory.key(
            inputID: 1,
            usbHIDUsage: 0x04,
            pressed: false,
            modifierMask: USBHIDModifierWire.leftShift,
            text: "",
            sessionID: sessionID,
            sessionEpoch: 8
        )
    }
    do {
        _ = try outbox.enqueue(owner: owner) { _ in
            throw RejectedControlEnvelope.release
        }
        throw SelfTestError.failed("rejected release was admitted")
    } catch RejectedControlEnvelope.release { }

    let notice = try outbox.enqueue(owner: owner) { factory in
        factory.disconnectNotice(
            reasonCode: "client_disconnect",
            mayResume: false,
            sessionID: sessionID,
            sessionEpoch: 8
        )
    }
    try require(admittedRelease.messageID == 1 && notice.messageID == 2,
                "rejected release consumed FIFO ordering")
    _ = try await notice.wait()
    _ = try await admittedRelease.wait()
    let snapshot = records.snapshot
    try require(snapshot.map(\.messageID) == [1, 2],
                "admitted release was superseded by partial failure")
    try require(snapshot.map(\.payload) == ["key-up", "disconnect"],
                "disconnect notice did not follow admitted release")
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
        "video_config", "display_changed", "video_config_result", "touch", "stylus", "ping", "pong",
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

    guard let stylusPayload = envelopes["stylus"]?.payload,
          case let .stylusEvent(stylus) = stylusPayload else {
        throw SelfTestError.failed("Protocol v1 stylus fixture missing")
    }
    try require(
        stylus.inputID == 101 && stylus.pointerID == 7 && stylus.phase == .changed,
        "Protocol v1 stylus identity"
    )
    try require(stylus.position.x == 0.125 && stylus.position.y == 0.875, "Protocol v1 stylus position")
    try require(stylus.pressure == 0.625, "Protocol v1 stylus pressure")
    try require(stylus.tiltXDegrees == -12.5 && stylus.tiltYDegrees == 28.75, "Protocol v1 stylus tilt")
    try require(
        stylus.target.displayID == displayList.displayID && stylus.target.streamID == 42,
        "Protocol v1 stylus target"
    )

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
    try require(VideoDecoder.parameterSets(codec: .av1, from: accessUnit).isEmpty, "AV1 parameter sets must not be inferred from Annex-B NAL units")
    let decoder = VideoDecoder { _, _ in }
    do {
        try decoder.configure(codec: .av1, parameterSets: [])
        throw SelfTestError.failed("AV1 decoder configuration was accepted without an implementation")
    } catch VideoDecoderError.unsupportedCodec(.av1) {
        // Expected.
    }
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
    _ = try jitter.enqueue(packet(sequence: 1), streamID: 7, sessionEpoch: 9, configEpoch: 2, format: format)
    _ = try jitter.enqueue(packet(sequence: 0), streamID: 7, sessionEpoch: 9, configEpoch: 2, format: format)
    try require(jitter.drainReady().map(\.header.sequence) == [0, 1], "audio reorder")
    try require(
        jitter.enqueue(packet(sequence: 0), streamID: 7, sessionEpoch: 9, configEpoch: 2, format: format) == .stale,
        "late audio packet"
    )
    do {
        _ = try jitter.enqueue(packet(sequence: 2), streamID: 8, sessionEpoch: 9, configEpoch: 2, format: format)
        throw SelfTestError.failed("audio queue accepted wrong stream")
    } catch AudioStreamError.streamIDMismatch(expected: 8, received: 7) { }
    for sequence in 5...9 {
        _ = try jitter.enqueue(packet(sequence: UInt64(sequence)), streamID: 7, sessionEpoch: 9, configEpoch: 2, format: format)
    }
    try require(jitter.queuedPacketCount <= 3, "audio queue exceeded bound")
}

func testAudioPlaybackSessionFailClosed() throws {
    var config = VSAudioConfig()
    config.streamID = 7
    config.configEpoch = 2
    config.codec = .pcmS16Le
    config.sampleRateHz = 48_000
    config.channelCount = 2
    config.framesPerPacket = 4
    let format = try PCMStreamFormat(config: config)
    let payload = Data(repeating: 0x01, count: format.bytesPerPacket)

    func packet(sequence: UInt64, configEpoch: UInt64 = 2) throws -> AudioPacket {
        var header = VSAudioPacketHeader()
        header.streamID = 7
        header.sessionEpoch = 9
        header.configEpoch = configEpoch
        header.sequence = sequence
        header.frameCount = 4
        header.payloadLength = UInt32(payload.count)
        let bytes = try header.serializedData()
        return try AudioPacket(serializedFrame: encodeVarint(bytes.count) + bytes + payload)
    }

    var session = AudioPlaybackSession(maximumBufferedPackets: 3)
    try require(!session.isConfigured, "audio session started configured")
    try session.validate(config: config)
    try require(session.lastConfigEpoch == 0, "audio validation advanced config epoch")
    try session.accept(config: config, format: format)
    try require(session.isConfigured, "audio session did not accept config")
    try require(
        try session.enqueue(packet(sequence: 1), sessionEpoch: 9).isEmpty,
        "audio session drained across a gap"
    )
    try require(session.queuedPacketCount == 1, "audio session did not retain gap packet")
    try require(
        try session.enqueue(packet(sequence: 0), sessionEpoch: 9).map(\.header.sequence) == [0, 1],
        "audio session did not drain contiguous packets"
    )

    var nextConfig = config
    nextConfig.configEpoch = 3
    try session.accept(config: nextConfig, format: format)
    _ = try session.enqueue(packet(sequence: 2, configEpoch: 3), sessionEpoch: 9)
    session.failClosed()
    try require(!session.isConfigured, "audio fail-closed left config active")
    try require(session.queuedPacketCount == 0, "audio fail-closed left queued packets")
    do {
        try session.accept(config: nextConfig, format: format)
        throw SelfTestError.failed("audio fail-closed reset config epoch watermark")
    } catch AudioStreamError.nonIncreasingConfigEpoch(previous: 3, received: 3) { }
    try require(
        try session.enqueue(packet(sequence: 0), sessionEpoch: 9).isEmpty,
        "audio fail-closed admitted media without a config"
    )

    var newConfig = config
    newConfig.configEpoch = 4
    try session.accept(config: newConfig, format: format)
    do {
        _ = try session.enqueue(packet(sequence: 0, configEpoch: 3), sessionEpoch: 9)
        throw SelfTestError.failed("audio session accepted stale config epoch")
    } catch AudioStreamError.staleConfigEpoch { }

    do {
        try session.accept(config: newConfig, format: format)
        throw SelfTestError.failed("audio session accepted non-increasing config epoch")
    } catch AudioStreamError.nonIncreasingConfigEpoch(previous: 4, received: 4) { }

    session.reset()
    try session.accept(config: config, format: format)
    try require(session.lastConfigEpoch == 2, "audio reset did not clear config epoch watermark")

    var zeroStream = config
    zeroStream.streamID = 0
    do {
        _ = try PCMStreamFormat(config: zeroStream)
        throw SelfTestError.failed("audio config accepted zero stream")
    } catch AudioStreamError.invalidStreamID(0) { }

    var zeroEpoch = config
    zeroEpoch.configEpoch = 0
    do {
        _ = try PCMStreamFormat(config: zeroEpoch)
        throw SelfTestError.failed("audio config accepted zero config epoch")
    } catch AudioStreamError.invalidConfigEpoch(0) { }

    var oversizedPacket = config
    oversizedPacket.framesPerPacket = PCMStreamFormat.maximumFramesPerPacket + 1
    do {
        _ = try PCMStreamFormat(config: oversizedPacket)
        throw SelfTestError.failed("audio config accepted oversized frames-per-packet")
    } catch AudioStreamError.invalidFramesPerPacket(PCMStreamFormat.maximumFramesPerPacket + 1) { }

    try require(
        AudioStreamError.streamIDMismatch(expected: 7, received: 8).isDroppableMediaPacketError,
        "audio stream mismatch was not classified as droppable"
    )
    try require(
        AudioStreamError.staleSessionEpoch.isDroppableMediaPacketError,
        "stale audio session epoch was not classified as droppable"
    )
    try require(
        AudioStreamError.staleConfigEpoch.isDroppableMediaPacketError,
        "stale audio config epoch was not classified as droppable"
    )
    try require(
        AudioStreamError.invalidPCMByteCount.isDroppableMediaPacketError,
        "invalid audio packet byte count was not classified as droppable"
    )
    try require(
        AudioStreamError.invalidHeader.isDroppableMediaPacketError,
        "invalid audio packet header was not classified as droppable"
    )
    try require(
        AudioStreamError.payloadLengthMismatch.isDroppableMediaPacketError,
        "audio payload length mismatch was not classified as droppable"
    )
    try require(
        !AudioStreamError.nonIncreasingConfigEpoch(previous: 4, received: 4).isDroppableMediaPacketError,
        "audio config control-plane error was classified as droppable"
    )
}

func testClipboardAndManagedPolicy() throws {
    let managed = try ManagedPolicy(managedConfiguration: [
        "ClipboardAllowed": true,
        "FileTransferAllowed": false,
        "AudioAllowed": true,
        "WakeAllowed": false,
        "CustomGesturesAllowed": true,
        "HostActionsAllowed": false,
        "MaximumFileBytes": 1_024,
        "AllowedHosts": ["mac.local"],
    ])
    try require(managed.isManaged && !managed.fileTransferAllowed, "managed deny")
    try require(
        managed.customGesturesAllowed && !managed.hostActionsAllowed,
        "managed host actions deny must not disable custom gestures"
    )
    try require(managed.allowedHosts == ["mac.local"], "managed host list")
    let denyWins = managed.applying(remote: ManagedPolicy(
        isManaged: true,
        clipboardAllowed: false,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: false,
        hostActionsAllowed: true,
        maximumFileBytes: 4_096,
        allowedHosts: ["mac.local", "other"]
    ))
    try require(!denyWins.clipboardAllowed && !denyWins.fileTransferAllowed, "managed deny-wins")
    try require(
        !denyWins.customGesturesAllowed && !denyWins.hostActionsAllowed,
        "custom gestures and host actions must apply deny-wins independently"
    )
    let disjointHosts = managed.applying(remote: ManagedPolicy(
        isManaged: true,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: 4_096,
        allowedHosts: ["other.local"]
    ))
    try require(
        disjointHosts.allowedHostsRestricted
            && disjointHosts.allowedHosts.isEmpty
            && !disjointHosts.allows(host: "mac.local")
            && !disjointHosts.allows(host: "other.local"),
        "disjoint managed host allowlists must deny all hosts"
    )
    let restrictedEmpty = ManagedPolicy(
        isManaged: true,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: 4_096,
        allowedHosts: [],
        allowedHostsRestricted: true
    )
    let restrictedEmptyRoundTrip = ManagedPolicy(remoteStatus: restrictedEmpty.protocolStatus)
    try require(
        restrictedEmptyRoundTrip.allowedHostsRestricted
            && restrictedEmptyRoundTrip.allowedHosts.isEmpty
            && !restrictedEmptyRoundTrip.allows(host: "mac.local"),
        "restricted empty managed host allowlist must round-trip as deny-all"
    )

    let customGesturesDenied = try ManagedPolicy(managedConfiguration: [
        "ClipboardAllowed": true,
        "FileTransferAllowed": true,
        "AudioAllowed": true,
        "WakeAllowed": true,
        "CustomGesturesAllowed": false,
        "HostActionsAllowed": true,
        "MaximumFileBytes": 1_024,
        "AllowedHosts": [String](),
    ])
    try require(
        !customGesturesDenied.customGesturesAllowed && customGesturesDenied.hostActionsAllowed,
        "managed custom gestures deny must not disable host actions"
    )

    let remoteDeniedStatus = ManagedPolicy(
        isManaged: true,
        clipboardAllowed: false,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: false,
        maximumFileBytes: 128,
        allowedHosts: []
    ).protocolStatus
    var resolver = ManagedPolicyResolver(localPolicy: managed)
    resolver.setRemote(ManagedPolicy(remoteStatus: remoteDeniedStatus))
    try require(
        !resolver.effectivePolicy.clipboardAllowed
            && !resolver.effectivePolicy.hostActionsAllowed
            && resolver.effectivePolicy.maximumFileBytes == 128,
        "managed remote deny was not applied"
    )

    let remoteAllowedStatus = ManagedPolicy(
        isManaged: true,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: 4_096,
        allowedHosts: []
    ).protocolStatus
    resolver.setRemote(ManagedPolicy(remoteStatus: remoteAllowedStatus))
    try require(
        resolver.effectivePolicy.clipboardAllowed
            && !resolver.effectivePolicy.hostActionsAllowed
            && resolver.effectivePolicy.maximumFileBytes == 1_024,
        "updated remote allow did not recompute from the local policy"
    )

    resolver.clearRemote()
    try require(
        resolver.effectivePolicy == managed,
        "clearing the remote policy did not restore the local policy"
    )

    let largeLocalLimit = ManagedPolicy(
        isManaged: true,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: ManagedPolicy.defaultMaximumFileBytes + 1,
        allowedHosts: []
    )
    var unmanagedRemoteStatus = VSManagedPolicyStatus()
    unmanagedRemoteStatus.managed = false
    try require(
        largeLocalLimit.applying(remote: ManagedPolicy(remoteStatus: unmanagedRemoteStatus))
            == largeLocalLimit,
        "unmanaged remote policy tightened local limits"
    )

    var managedUnsetStatus = VSManagedPolicyStatus()
    managedUnsetStatus.managed = true
    let managedUnset = ManagedPolicy(remoteStatus: managedUnsetStatus)
    try require(
        !managedUnset.clipboardAllowed
            && !managedUnset.hostActionsAllowed
            && managedUnset.maximumFileBytes == 0,
        "managed remote defaults did not fail closed"
    )

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
    request.streamID = 1
    request.codec = .hevc
    request.encodedSize.width = 1_920
    request.encodedSize.height = 1_080
    request.framesPerSecond = 60
    request.bitrateKbps = 8_000
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
    case .rejected:
        throw SelfTestError.failed("valid unsupported HDR was rejected as malformed")
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
                owner: ConnectionOwner(),
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
                owner: ConnectionOwner(),
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
    try testUSBHIDModifierCompatibility()
    try testNativeInputAndBoundedReconnect()
    try await testPartialReleaseFailureStillFlushesDisconnectNotice()
    try testSharedProtocolFixture()
    try testProtocolV1GoldenFixtures()
    FileHandle.standardError.write(Data("RUN: codec/backoff\n".utf8))
    try testBackpressureAndCodecParsing()
    FileHandle.standardError.write(Data("RUN: multi-display/audio\n".utf8))
    try testMultiDisplaySessions()
    try testAudioQueue()
    try testAudioPlaybackSessionFailClosed()
    FileHandle.standardError.write(Data("RUN: clipboard/file/policy\n".utf8))
    try testClipboardAndManagedPolicy()
    try testFileTransfer()
    FileHandle.standardError.write(Data("RUN: HDR/gesture/wake/advanced-proto\n".utf8))
    try testHDRGesturesAndWake()
    try testAdvancedProtocolRoundTrip()
    FileHandle.standardError.write(Data("RUN: trusted-LAN startup codecs\n".utf8))
    try testTrustedLANStartupCodecs()
    try testTransportStartupCancellation()
    FileHandle.standardError.write(Data("RUN: owner/media/heartbeat generation gates\n".utf8))
    try runOwnerGenerationSelfTests()
    try runVideoMediaGateSelfTest()
    try runVideoConfigValidatorSelfTest()
    try runHeartbeatMonitorSelfTests()
    print("PASS: Phase 5A-5D core and trusted-LAN Protocol v1 startup")
} catch {
    FileHandle.standardError.write(Data("FAIL: \(error)\n".utf8))
    exit(EXIT_FAILURE)
}
