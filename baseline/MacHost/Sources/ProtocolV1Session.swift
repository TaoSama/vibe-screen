import Foundation
import VibeScreenProtocol

/// A physical/virtual display the host can expose for client-driven selection.
struct ProtocolV1DisplayInfo: Equatable {
    let id: String
    let name: String
    let width: Int
    let height: Int
    let isPrimary: Bool
    let isVirtual: Bool
}

struct ProtocolV1SessionConfiguration {
    static let version: UInt32 = 1

   static func productionHostCapabilities(touchEnabled: Bool) -> Set<VSCapability> {
        // Native pointer/keyboard ride the same input toggle as touch: they
        // require Accessibility to actually inject, but the capability is
        // advertised so a USB session can negotiate them. When input is
        // disabled entirely, only multi-display selection is offered.
        // Client video control tunes the host encoder, needs no Accessibility,
        // and is always offered so the client can adjust bitrate/fps/quality.
        touchEnabled
            ? [.touch, .keyboard, .pointer, .multiDisplay, .clientVideoControl]
            : [.multiDisplay, .clientVideoControl]
   }

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
    /// Full catalog exposed by ListDisplays. When empty, the session
    /// synthesizes a single entry from the currently captured identity so the
    /// single-display path keeps ListDisplays count == 1.
    var displays: [ProtocolV1DisplayInfo] = []
}

enum ProtocolV1SessionPhase: Equatable {
    case awaitingClientHello
    case preparingCodec(correlationID: UInt64)
    case awaitingDisplayStart
    case awaitingVideoConfig(configEpoch: UInt64, streamID: UInt64)
    case streaming(configEpoch: UInt64, streamID: UInt64)
    case closed
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
    case selectDisplay(id: String)
    case applyVideoPreferences(bitrateKbps: UInt32, framesPerSecond: UInt32, qualityPreset: VSVideoQualityPreset)
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

    /// Runtime display switch initiated by the host after a client selection has
    /// recaptured a different source. Re-runs the StartDisplay negotiation with a
    /// bumped configEpoch so the client re-negotiates video for the new geometry.
    /// The DisplayChanged notice is emitted after the client accepts the new
    /// VideoConfig, reusing the awaitingVideoConfig -> streaming transition.
    func selectDisplayFromClient(displayID: String) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard case .streaming(let configEpoch, let streamID) = phase else { return [] }
            guard displayID.isEmpty || configuration.displayID == displayID
                    || configuredDisplays().contains(where: { $0.id == displayID }) else {
                return []
            }
            return renegotiateSelectedDisplayLocked(
                displayID: displayID,
                configEpoch: configEpoch,
                streamID: streamID,
                correlationID: 0
            )
        }
    }

    /// Shared runtime re-negotiation used by both a host-initiated switch
    /// (selectDisplayFromClient) and a client-initiated StartDisplayRequest that
    /// arrives while already streaming. Adopts the new display, bumps the
    /// configEpoch, moves to awaitingVideoConfig so media is gated until the
    /// client accepts, and returns the StartDisplayResponse + VideoConfig pair.
    private func renegotiateSelectedDisplayLocked(
        displayID: String,
        configEpoch: UInt64,
        streamID: UInt64,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        if !displayID.isEmpty { adoptDisplay(id: displayID) }
        let nextEpoch = configEpoch + 1
        var response = VSStartDisplayResponse()
        response.accepted = true
        response.display = displayDescriptor()
        response.streamID = streamID

        var config = VSVideoConfig()
        config.configEpoch = nextEpoch
        config.codec = selectedCodec
        config.encodedSize = dimensions()
        config.framesPerSecond = configuration.framesPerSecond
        config.bitrateKbps = configuration.bitrateKbps
        config.streamID = streamID
        config.rotationDegrees = UInt32(clamping: configuration.rotation)
        advertisedVideoRotation = configuration.rotation

        phase = .awaitingVideoConfig(configEpoch: nextEpoch, streamID: streamID)
        do {
            return [
                .sendControl(try encode(payload: .startDisplayResponse(response), correlationID: correlationID)),
                .sendControl(try encode(payload: .videoConfig(config), correlationID: correlationID))
            ]
        } catch {
            return serializationFailure()
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
            response.displays = configuredDisplayDescriptors()
            return sendActions(
                payload: .listDisplaysResponse(response),
                correlationID: envelope.messageID
            )

        case .startDisplayRequest(let request):
            guard request.mode == .existing else {
                return fail(
                    code: .invalidState,
                    message: "The host session only supports selecting an existing display.",
                    correlationID: envelope.messageID
                )
            }
            // A StartDisplayRequest arriving while already streaming is a
            // client-initiated runtime display switch. Treat it as an in-place
            // re-selection on the same session: ask the host to switch capture
            // and re-run the StartDisplay/VideoConfig negotiation with a bumped
            // epoch so media stays gated until the client accepts. This is the
            // client half of the display-switch flow; without it the client's
            // selectDisplay() StartDisplayRequest was rejected with invalidState
            // and the session tore down (the on-device flap).
            if case .streaming(let configEpoch, let streamID) = phase {
                let requestedID = request.sourceDisplayID
                if requestedID.isEmpty || requestedID == configuration.displayID {
                    // Re-selecting the active display: re-negotiate in place
                    // without a capture switch.
                    return renegotiateSelectedDisplayLocked(
                        displayID: "",
                        configEpoch: configEpoch,
                        streamID: streamID,
                        correlationID: envelope.messageID
                    )
                }
                guard configuredDisplays().contains(where: { $0.id == requestedID }) else {
                    return fail(
                        code: .invalidState,
                        message: "StartDisplay referenced an unknown or offline display.",
                        correlationID: envelope.messageID
                    )
                }
                return [.selectDisplay(id: requestedID)] + renegotiateSelectedDisplayLocked(
                    displayID: requestedID,
                    configEpoch: configEpoch,
                    streamID: streamID,
                    correlationID: envelope.messageID
                )
            }
            guard phase == .awaitingDisplayStart else {
                return invalidState("StartDisplay is not valid in the current state.", envelope.messageID)
            }
            let requestedID = request.sourceDisplayID
            if requestedID.isEmpty || requestedID == configuration.displayID {
                return startDisplay(correlationID: envelope.messageID)
            }
            guard configuredDisplays().contains(where: { $0.id == requestedID }) else {
                return fail(
                    code: .invalidState,
                    message: "StartDisplay referenced an unknown or offline display.",
                    correlationID: envelope.messageID
                )
            }
            // A different, known display was requested before streaming began:
            // adopt it as the captured identity, ask the host to switch capture,
            // and start it as the active display.
            adoptDisplay(id: requestedID)
            return [.selectDisplay(id: requestedID)] + startDisplay(correlationID: envelope.messageID)

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
                  inputTargetMatchesActiveStream(touch.hasTarget ? touch.target : nil),
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

        case .setVideoPreferences(let prefs):
            guard negotiatedCapabilities.contains(.clientVideoControl) else {
                return unsupportedCapability("Client video control was not negotiated.", envelope.messageID)
            }
            guard case .streaming(let configEpoch, let streamID) = phase else {
                return invalidState("SetVideoPreferences arrived before media was streaming.", envelope.messageID)
            }
            // Clamp the requested values into the host's supported range. A zero
            // field means "leave unchanged", so it maps back to the current
            // configuration before clamping. The client cannot drive the host
            // outside these bounds regardless of what it requests.
            let requestedBitrate = prefs.bitrateKbps == 0
                ? configuration.bitrateKbps
                : prefs.bitrateKbps
            let requestedFps = prefs.framesPerSecond == 0
                ? configuration.framesPerSecond
                : prefs.framesPerSecond
            let clampedBitrate = min(
                max(requestedBitrate, Self.minimumClientBitrateKbps),
                Self.maximumClientBitrateKbps
            )
            let clampedFps = min(
                max(requestedFps, Self.minimumClientFramesPerSecond),
                Self.maximumClientFramesPerSecond
            )
            configuration.bitrateKbps = clampedBitrate
            configuration.framesPerSecond = clampedFps
            // Re-advertise the applied video configuration on the same session
            // with a bumped config epoch (reusing the runtime renegotiation
            // path), and ask the host to reconfigure its encoder to match. The
            // apply action carries the clamped values plus the quality intent so
            // the host maps a preset to encoder quality when no explicit bitrate
            // was requested.
            let apply = ProtocolV1SessionAction.applyVideoPreferences(
                bitrateKbps: clampedBitrate,
                framesPerSecond: clampedFps,
                qualityPreset: prefs.bitrateKbps == 0 ? prefs.qualityPreset : .unspecified
            )
            return [apply] + renegotiateSelectedDisplayLocked(
                displayID: "",
                configEpoch: configEpoch,
                streamID: streamID,
                correlationID: envelope.messageID
            )

        case .protocolError(let error):
            phase = .failed
            return [.peerError(error), .close]

        case .disconnectNotice:
            phase = .closed
            return [.close]

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

    // Bounds the host applies to a client SetVideoPreferences request. The
    // client can express intent but never drive the encoder outside this range.
    private static let minimumClientBitrateKbps: UInt32 = 1_000
    private static let maximumClientBitrateKbps: UInt32 = 100_000
    private static let minimumClientFramesPerSecond: UInt32 = 24
    private static let maximumClientFramesPerSecond: UInt32 = 120

    private var isStreaming: Bool {
        if case .streaming = phase { return true }
        return false
    }

    private func inputTargetMatchesActiveStream(_ target: VSInputTarget?) -> Bool {
        guard case .streaming(_, let streamID) = phase else { return false }
        guard let target else { return true }
        if target.displayID.isEmpty && target.streamID == 0 { return true }
        return target.displayID == configuration.displayID && target.streamID == streamID
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
        display.isPrimary = activeDisplayInfo()?.isPrimary ?? true
        display.isVirtual = configuration.displayIsVirtual
        return display
    }

    /// The full catalog to advertise. Falls back to a single synthesized entry
    /// built from the currently captured identity when no catalog was supplied.
    private func configuredDisplays() -> [ProtocolV1DisplayInfo] {
        if configuration.displays.isEmpty {
            return [ProtocolV1DisplayInfo(
                id: configuration.displayID,
                name: configuration.displayName,
                width: max(0, configuration.displayWidth),
                height: max(0, configuration.displayHeight),
                isPrimary: true,
                isVirtual: configuration.displayIsVirtual
            )]
        }
        return configuration.displays
    }

    private func activeDisplayInfo() -> ProtocolV1DisplayInfo? {
        configuredDisplays().first { $0.id == configuration.displayID }
    }

    private func configuredDisplayDescriptors() -> [VSDisplayDescriptor] {
        configuredDisplays().map { info in
            var descriptor = VSDisplayDescriptor()
            descriptor.displayID = info.id
            // The active display's descriptor must equal displayDescriptor() so
            // the client's expected-display matching still holds.
            if info.id == configuration.displayID {
                descriptor.name = configuration.displayName
                descriptor.logicalSize = dimensions()
                descriptor.isVirtual = configuration.displayIsVirtual
            } else {
                descriptor.name = info.name
                var size = VSDimensions()
                size.width = UInt32(max(0, info.width))
                size.height = UInt32(max(0, info.height))
                descriptor.logicalSize = size
                descriptor.isVirtual = info.isVirtual
            }
            descriptor.scaleFactor = 1
            descriptor.isPrimary = info.isPrimary
            return descriptor
        }
    }

    /// Adopt a known catalog display as the captured identity so subsequent
    /// descriptors and geometry reflect the selected source.
    private func adoptDisplay(id: String) {
        guard let info = configuration.displays.first(where: { $0.id == id }) else { return }
        configuration.displayID = info.id
        configuration.displayName = info.name
        configuration.displayWidth = info.width
        configuration.displayHeight = info.height
        configuration.displayIsVirtual = info.isVirtual
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
