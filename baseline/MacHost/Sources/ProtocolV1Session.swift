import Foundation
import VibeScreenProtocol

struct ProtocolV1SessionConfiguration {
    static let version: UInt32 = 1

    let sessionID: Data
    let sessionEpoch: UInt64
    var displayWidth: Int
    var displayHeight: Int
    var rotation: Int
    var framesPerSecond: UInt32
    var bitrateKbps: UInt32
    var hostCapabilities: Set<VSCapability>
    var requiredClientCapabilities: Set<VSCapability>
    var supportedCodecs: [VSCodec]
    var hostID: String
    var hostName: String
    var displayID: String
    var displayName: String
    var displayIsVirtual: Bool
}

enum ProtocolV1SessionPhase: Equatable {
    case awaitingClientHello
    case preparingCodec(correlationID: UInt64)
    case awaitingDisplayStart
    case awaitingVideoConfig(configEpoch: UInt64, streamID: UInt64)
    case streaming(configEpoch: UInt64, streamID: UInt64)
    case failed
}

enum ProtocolV1SessionAction {
    case sendControl(Data)
    case codecNegotiated(StreamCodec)
    case connectionReady
    case touch(pointerID: UInt32, x: Float, y: Float, phase: VSInputPhase)
    case pointer(x: Float, y: Float, phase: VSInputPhase, buttonMask: UInt32)
    case scroll(deltaX: Double, deltaY: Double)
    case key(usage: UInt32, pressed: Bool, modifiers: UInt32, text: String)
    case heartbeat
    case requestKeyframe(force: Bool)
    case peerError(VSProtocolError)
    case close
}

final class ProtocolV1SessionCoordinator {
    private(set) var phase: ProtocolV1SessionPhase = .awaitingClientHello
    private(set) var selectedCodec: VSCodec = .unspecified
    private(set) var lastReceivedMessageID: UInt64 = 0
    private(set) var nextFrameID: UInt64 = 1

    private var configuration: ProtocolV1SessionConfiguration
    private var nextMessageID: UInt64 = 1
    private var negotiatedCapabilities: Set<VSCapability> = []
    private var advertisedVideoRotation = 0
    private let lock = NSLock()

    init(configuration: ProtocolV1SessionConfiguration) {
        precondition(!configuration.sessionID.isEmpty)
        precondition(configuration.sessionEpoch > 0)
        self.configuration = configuration
    }

    func updateDisplayGeometry(width: Int, height: Int, rotation: Int) {
        withSessionLock {
            configuration.displayWidth = width
            configuration.displayHeight = height
            configuration.rotation = rotation
        }
    }

    func makeDisplayChanged() -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard case .streaming = phase else { return [] }
            var changed = VSDisplayChanged()
            changed.display = displayDescriptor()
            changed.rotationDegrees = UInt32(clamping: configuration.rotation)
            advertisedVideoRotation = configuration.rotation
            return sendActions(payload: .displayChanged(changed), correlationID: 0)
        }
    }

    func handleControl(_ bytes: Data) -> [ProtocolV1SessionAction] {
        withSessionLock { handleControlLocked(bytes) }
    }

    func completeCodecNegotiation() -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard case .preparingCodec(let correlationID) = phase else { return [] }
            var hostHello = VSHostHello()
            hostHello.selectedProtocol = Self.protocolVersion
            hostHello.hostID = configuration.hostID
            hostHello.hostName = configuration.hostName
            hostHello.capabilities = configuration.hostCapabilities.sorted { $0.rawValue < $1.rawValue }
            hostHello.codecs = configuration.supportedCodecs

            var accepted = VSSessionAccepted()
            accepted.sessionID = configuration.sessionID
            accepted.sessionEpoch = configuration.sessionEpoch
            accepted.heartbeatIntervalMs = 1_000
            accepted.negotiatedCapabilities = negotiatedCapabilities.sorted { $0.rawValue < $1.rawValue }

            phase = .awaitingDisplayStart
            do {
                return [
                    .sendControl(try encode(
                        payload: .hostHello(hostHello),
                        correlationID: correlationID,
                        sessionScoped: false
                    )),
                    .sendControl(try encode(payload: .sessionAccepted(accepted), correlationID: correlationID))
                ]
            } catch {
                return serializationFailure()
            }
        }
    }

    private func handleControlLocked(_ bytes: Data) -> [ProtocolV1SessionAction] {
        let envelope: VSEnvelope
        do {
            envelope = try VSEnvelope(serializedBytes: bytes)
        } catch {
            return fail(
                code: .malformedMessage,
                message: "Control payload is not a valid Protocol v1 Envelope.",
                correlationID: 0
            )
        }
        guard envelope.protocolVersion == Self.protocolVersion else {
            return fail(
                code: .unsupportedVersion,
                message: "Only Protocol v1 is supported.",
                correlationID: envelope.messageID
            )
        }
        guard envelope.messageID > lastReceivedMessageID else {
            return fail(
                code: .invalidState,
                message: "message_id must increase monotonically.",
                correlationID: envelope.messageID
            )
        }
        guard envelope.payload != nil else {
            return fail(
                code: .malformedMessage,
                message: "Envelope payload is required.",
                correlationID: envelope.messageID
            )
        }
        lastReceivedMessageID = envelope.messageID

        if phase == .awaitingClientHello {
            guard envelope.sessionID.isEmpty, envelope.sessionEpoch == 0,
                  case .clientHello(let hello)? = envelope.payload else {
                return fail(
                    code: .invalidState,
                    message: "ClientHello must be the first control message.",
                    correlationID: envelope.messageID
                )
            }
            return acceptClientHello(hello, correlationID: envelope.messageID)
        }

        guard envelope.sessionID == configuration.sessionID,
              envelope.sessionEpoch == configuration.sessionEpoch else {
            return fail(
                code: .unauthorized,
                message: "Control message does not belong to the active session epoch.",
                correlationID: envelope.messageID
            )
        }

        switch envelope.payload {
        case .listDisplaysRequest:
            guard phase == .awaitingDisplayStart else {
                return invalidState("ListDisplays is not valid in the current state.", envelope.messageID)
            }
            var response = VSListDisplaysResponse()
            response.displays = [displayDescriptor()]
            return sendActions(
                payload: .listDisplaysResponse(response),
                correlationID: envelope.messageID
            )

        case .startDisplayRequest(let request):
            guard phase == .awaitingDisplayStart else {
                return invalidState("StartDisplay is not valid in the current state.", envelope.messageID)
            }
            guard request.mode == .existing,
                  request.sourceDisplayID.isEmpty || request.sourceDisplayID == configuration.displayID else {
                return fail(
                    code: .invalidState,
                    message: "The current host session only exposes its configured existing display.",
                    correlationID: envelope.messageID
                )
            }
            return startDisplay(correlationID: envelope.messageID)

        case .videoConfigResult(let result):
            guard case .awaitingVideoConfig(let configEpoch, let streamID) = phase,
                  result.configEpoch == configEpoch,
                  result.streamID == streamID else {
                return invalidState("VideoConfigResult does not match the pending configuration.", envelope.messageID)
            }
            guard result.accepted else {
                return fail(
                    code: .invalidState,
                    message: "Client rejected VideoConfig: \(result.rejectionReason)",
                    correlationID: envelope.messageID
                )
            }
            phase = .streaming(configEpoch: configEpoch, streamID: streamID)
            var actions: [ProtocolV1SessionAction] = []
            if advertisedVideoRotation != configuration.rotation {
                var changed = VSDisplayChanged()
                changed.display = displayDescriptor()
                changed.rotationDegrees = UInt32(clamping: configuration.rotation)
                do {
                    actions.append(.sendControl(try encode(payload: .displayChanged(changed), correlationID: 0)))
                } catch {
                    return serializationFailure()
                }
            }
            return actions + [.connectionReady, .requestKeyframe(force: true)]

        case .ping(let ping):
            var pong = VSPong()
            pong.sequence = ping.sequence
            let sends = sendActions(payload: .pong(pong), correlationID: envelope.messageID)
            guard !sends.contains(where: { if case .close = $0 { true } else { false } }) else {
                return sends
            }
            return sends + [.heartbeat]

        case .requestKeyframe:
            guard isStreaming else { return invalidState("Media is not streaming.", envelope.messageID) }
            return [.requestKeyframe(force: true)]

        case .touchEvent(let touch):
            guard negotiatedCapabilities.contains(.touch) else {
                return unsupportedCapability("Touch was not negotiated.", envelope.messageID)
            }
            guard isStreaming, touch.hasPosition,
                  (0...1).contains(touch.position.x),
                  (0...1).contains(touch.position.y),
                  touch.phase != .unspecified else {
                return invalidState("TouchEvent is invalid or media is not ready.", envelope.messageID)
            }
            return [.touch(
                pointerID: touch.pointerID,
                x: Float(touch.position.x),
                y: Float(touch.position.y),
                phase: touch.phase
            )]

        case .pointerEvent(let pointer):
            guard negotiatedCapabilities.contains(.pointer) else {
                return unsupportedCapability("Pointer input was not negotiated.", envelope.messageID)
            }
            guard isStreaming, pointer.hasPosition,
                  (0...1).contains(pointer.position.x),
                  (0...1).contains(pointer.position.y),
                  pointer.phase != .unspecified else {
                return invalidState("PointerEvent is invalid or media is not ready.", envelope.messageID)
            }
            return [.pointer(
                x: Float(pointer.position.x),
                y: Float(pointer.position.y),
                phase: pointer.phase,
                buttonMask: pointer.buttonMask
            )]

        case .scrollEvent(let scroll):
            guard negotiatedCapabilities.contains(.pointer) else {
                return unsupportedCapability("Pointer scrolling was not negotiated.", envelope.messageID)
            }
            guard isStreaming else { return invalidState("ScrollEvent arrived before media was ready.", envelope.messageID) }
            return [.scroll(deltaX: scroll.deltaX, deltaY: scroll.deltaY)]

        case .keyEvent(let key):
            guard negotiatedCapabilities.contains(.keyboard) else {
                return unsupportedCapability("Keyboard input was not negotiated.", envelope.messageID)
            }
            guard isStreaming else { return invalidState("KeyEvent arrived before media was ready.", envelope.messageID) }
            return [.key(usage: key.usbHidUsage, pressed: key.pressed, modifiers: key.modifierMask, text: key.text)]

        case .protocolError(let error):
            phase = .failed
            return [.peerError(error), .close]

        default:
            return invalidState("Payload is unsupported in the current host session.", envelope.messageID)
        }
    }

    func makeMediaFrame(payload: Data, timestamp: UInt64, keyframe: Bool) throws -> Data? {
        try withSessionLock {
            try makeMediaFrameLocked(payload: payload, timestamp: timestamp, keyframe: keyframe)
        }
    }

    private func makeMediaFrameLocked(payload: Data, timestamp: UInt64, keyframe: Bool) throws -> Data? {
        guard case .streaming(let configEpoch, let streamID) = phase else { return nil }
        guard nextFrameID < UInt64.max else { return nil }
        var header = VSMediaPacketHeader()
        header.streamID = streamID
        header.sessionEpoch = configuration.sessionEpoch
        header.configEpoch = configEpoch
        header.frameID = nextFrameID
        header.fragmentIndex = 0
        header.fragmentCount = 1
        header.captureTimestampNs = timestamp
        header.keyframe = keyframe
        header.codec = selectedCodec
        nextFrameID += 1
        return try ProtocolV1MediaPacketCodec.encode(header: header, payload: payload)
    }

    func rejectMalformedTransport(_ message: String) -> [ProtocolV1SessionAction] {
        withSessionLock {
            fail(code: .malformedMessage, message: message, correlationID: 0)
        }
    }

    func makeDisconnectNotice() throws -> Data {
        try withSessionLock {
            var notice = VSDisconnectNotice()
            notice.reasonCode = "host_shutdown"
            notice.mayResume = false
            return try encode(payload: .disconnectNotice(notice), correlationID: 0)
        }
    }

    private static let protocolVersion = ProtocolV1SessionConfiguration.version

    private var isStreaming: Bool {
        if case .streaming = phase { return true }
        return false
    }

    private func acceptClientHello(_ hello: VSClientHello, correlationID: UInt64) -> [ProtocolV1SessionAction] {
        guard hello.hasSupportedProtocols,
              hello.supportedProtocols.minimum <= Self.protocolVersion,
              hello.supportedProtocols.maximum >= Self.protocolVersion else {
            return fail(
                code: .unsupportedVersion,
                message: "Client does not offer Protocol v1.",
                correlationID: correlationID
            )
        }
        let offeredCapabilities = Set(hello.capabilities)
        let requiredCapabilities = Set(hello.requiredCapabilities)
        guard requiredCapabilities.isSubset(of: configuration.hostCapabilities) else {
            return fail(
                code: .unsupportedCapability,
                message: "Host does not implement a capability required by the client.",
                correlationID: correlationID
            )
        }
        guard configuration.requiredClientCapabilities.isSubset(of: offeredCapabilities) else {
            return fail(
                code: .unsupportedCapability,
                message: "Client is missing a required host capability.",
                correlationID: correlationID
            )
        }
        guard let codec = configuration.supportedCodecs.first(where: hello.codecs.contains) else {
            return fail(
                code: .unsupportedCapability,
                message: "Host and client have no common video codec.",
                correlationID: correlationID
            )
        }
        selectedCodec = codec
        let negotiatedCapabilities = configuration.hostCapabilities.intersection(offeredCapabilities)
        self.negotiatedCapabilities = negotiatedCapabilities

        phase = .preparingCodec(correlationID: correlationID)
        let streamCodec: StreamCodec = codec == .h264 ? .h264 : .hevc
        return [.codecNegotiated(streamCodec)]
    }

    private func startDisplay(correlationID: UInt64) -> [ProtocolV1SessionAction] {
        let streamID: UInt64 = 1
        let configEpoch: UInt64 = 1
        var response = VSStartDisplayResponse()
        response.accepted = true
        response.display = displayDescriptor()
        response.streamID = streamID

        var config = VSVideoConfig()
        config.configEpoch = configEpoch
        config.codec = selectedCodec
        config.encodedSize = dimensions()
        config.framesPerSecond = configuration.framesPerSecond
        config.bitrateKbps = configuration.bitrateKbps
        config.streamID = streamID
        config.rotationDegrees = UInt32(clamping: configuration.rotation)
        advertisedVideoRotation = configuration.rotation

        phase = .awaitingVideoConfig(configEpoch: configEpoch, streamID: streamID)
        do {
            return [
                .sendControl(try encode(payload: .startDisplayResponse(response), correlationID: correlationID)),
                .sendControl(try encode(payload: .videoConfig(config), correlationID: correlationID))
            ]
        } catch {
            return serializationFailure()
        }
    }

    private func displayDescriptor() -> VSDisplayDescriptor {
        var display = VSDisplayDescriptor()
        display.displayID = configuration.displayID
        display.name = configuration.displayName
        display.logicalSize = dimensions()
        display.scaleFactor = 1
        display.isPrimary = true
        display.isVirtual = configuration.displayIsVirtual
        return display
    }

    private func dimensions() -> VSDimensions {
        var dimensions = VSDimensions()
        dimensions.width = UInt32(max(0, configuration.displayWidth))
        dimensions.height = UInt32(max(0, configuration.displayHeight))
        return dimensions
    }

    private func encode(
        payload: VSEnvelope.OneOf_Payload,
        correlationID: UInt64,
        sessionScoped: Bool = true
    ) throws -> Data {
        var envelope = VSEnvelope()
        envelope.protocolVersion = Self.protocolVersion
        envelope.messageID = nextMessageID
        envelope.correlationID = correlationID
        if sessionScoped {
            envelope.sessionID = configuration.sessionID
            envelope.sessionEpoch = configuration.sessionEpoch
        }
        envelope.sentAtMonotonicNs = DispatchTime.now().uptimeNanoseconds
        envelope.payload = payload
        nextMessageID += 1
        return try envelope.serializedData()
    }

    private func invalidState(_ message: String, _ correlationID: UInt64) -> [ProtocolV1SessionAction] {
        fail(code: .invalidState, message: message, correlationID: correlationID)
    }

    private func unsupportedCapability(_ message: String, _ correlationID: UInt64) -> [ProtocolV1SessionAction] {
        fail(code: .unsupportedCapability, message: message, correlationID: correlationID)
    }

    private func fail(
        code: VSProtocolErrorCode,
        message: String,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        var error = VSProtocolError()
        error.code = code
        error.message = message
        error.retryable = false
        error.component = "macos-host-session"
        let sessionScoped = phase != .awaitingClientHello
        phase = .failed
        do {
            return [
                .sendControl(try encode(
                    payload: .protocolError(error),
                    correlationID: correlationID,
                    sessionScoped: sessionScoped
                )),
                .close
            ]
        } catch {
            return serializationFailure()
        }
    }

    private func sendActions(
        payload: VSEnvelope.OneOf_Payload,
        correlationID: UInt64,
        sessionScoped: Bool = true
    ) -> [ProtocolV1SessionAction] {
        do {
            return [.sendControl(try encode(
                payload: payload,
                correlationID: correlationID,
                sessionScoped: sessionScoped
            ))]
        } catch {
            return serializationFailure()
        }
    }

    private func serializationFailure() -> [ProtocolV1SessionAction] {
        phase = .failed
        return [.close]
    }

    private func withSessionLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
