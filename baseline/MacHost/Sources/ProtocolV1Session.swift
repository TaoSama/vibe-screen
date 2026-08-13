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

    struct AdvancedAdapters: Equatable {
        static let unavailable = AdvancedAdapters()

        var audio = false
        var clipboard = false
        var fileTransfer = false
        var colorManagement = false
        var hostActions = false
        var wakeHost = false
    }

   static func productionHostCapabilities(touchEnabled: Bool) -> Set<VSCapability> {
       productionHostCapabilities(
           touchEnabled: touchEnabled,
           advanced: AdvancedAdapters(hostActions: touchEnabled)
       )
   }

   static func productionHostCapabilities(
       touchEnabled: Bool,
       advanced: AdvancedAdapters
   ) -> Set<VSCapability> {
        // Native pointer/keyboard ride the same input toggle as touch: they
        // require Accessibility to actually inject, but the capability is
        // advertised so a USB session can negotiate them. When input is
        // disabled entirely, only multi-display selection is offered.
        // Client video control tunes the host encoder, needs no Accessibility,
        // and is always offered so the client can adjust bitrate/fps/quality.
        var capabilities: Set<VSCapability> = [.multiDisplay, .clientVideoControl]
        if touchEnabled { capabilities.formUnion([.touch, .stylus, .stylusExtended, .keyboard, .pointer]) }
        if advanced.audio { capabilities.insert(.audio) }
        if advanced.clipboard { capabilities.insert(.clipboard) }
        if advanced.fileTransfer { capabilities.insert(.fileTransfer) }
        if advanced.colorManagement { capabilities.insert(.colorManagement) }
        if advanced.hostActions { capabilities.insert(.hostActions) }
        if advanced.wakeHost { capabilities.insert(.wakeHost) }
        return capabilities
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
   var resourceLimits = HostAdvancedLimits.production
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
    case stylus(
        inputID: UInt64,
        pointerID: UInt32,
        x: Float,
        y: Float,
        phase: VSInputPhase,
        pressure: Double,
        tiltXDegrees: Double,
        tiltYDegrees: Double,
        toolKind: VSStylusToolKind,
        buttonMask: UInt32,
        contactState: VSStylusContactState
    )
    case pointer(x: Float, y: Float, phase: VSInputPhase, buttonMask: UInt32)
    case scroll(deltaX: Double, deltaY: Double)
    case key(usage: UInt32, pressed: Bool, modifiers: UInt32, text: String)
    case heartbeat
    case requestKeyframe(force: Bool)
    case selectDisplay(id: String)
   case applyVideoPreferences(
       token: UInt64,
       bitrateKbps: UInt32,
       framesPerSecond: UInt32,
       qualityPreset: VSVideoQualityPreset,
       resetQualityToAuto: Bool
   )
    /// A negotiated client asked the host to run one catalog action. The action
    /// leaves the session lock as an intent so the AppDelegate can drive
    /// AppKit/Accessibility on the main actor; the host confirms the outcome
    /// through completeHostAction, which is the only place HostActionResult is
    /// emitted back on the session FIFO.
    case hostAction(actionID: String, invocationID: Data, target: VSInputTarget?)
   case clipboardContent(VSClipboardContent)
   case fileOffer(VSFileOffer)
   case fileCancel(transferID: Data)
   case wakeHost(VSWakeHostRequest)
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
    private var stylusSequenceState = StylusSequenceState()
    private var advertisedVideoRotation = 0
    private let lock = NSLock()
    /// Identifies the newest in-flight client video-preferences request. The
    /// bumped-epoch VideoConfig renegotiation is deferred until the host
    /// confirms the encoder actually adopted the requested settings, so a
    /// client can never accept a new VideoConfig while the encoder still runs
    /// the old configuration. A stale completion (superseded token or a phase
    /// change) is ignored.
    private var pendingVideoPreferencesToken: UInt64 = 0
    private var nextVideoPreferencesToken: UInt64 = 1
    /// Host-action invocations the host is currently running, keyed by the
    /// client's invocation_id and mapped to the request's Envelope message_id.
    /// The result echoes both the invocation_id (in the payload) and the
    /// request message_id (as the Envelope correlation_id), so a duplicate or
    /// unknown completion is a safe no-op. Bounded by
    /// maximumPendingHostActionInvocations.
    private var pendingHostActionInvocations: [Data: UInt64] = [:]
    private var pendingFileOffers: [Data: UInt64] = [:]
    private var activeFileTransfers: Set<Data> = []
    private var pendingWakeRequests: [Data: UInt64] = [:]
    private var audioConfigEpoch: UInt64 = 1
    private var audioAccepted = false
    private var nextAudioSequence: UInt64 = 0
    private var attemptedColorFallback = false
    private var negotiatedResourceLimits = VSResourceLimits()

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

    /// Confirm a client SetVideoPreferences request after the host encoder has
    /// actually adopted the new settings. A superseded token or a non-accepted
    /// result keeps the prior advertised configuration and emits nothing. On an
    /// accepted result the applied numeric values are adopted before the phase
    /// is inspected, so even if the session is mid-renegotiation
    /// (.awaitingVideoConfig) the next VideoConfig advertises the values the
    /// encoder actually runs instead of stale numbers. Only when the session is
    /// STREAMING does this also bump the config epoch and renegotiate, exactly
    /// like a display switch, so media stays gated until the client accepts.
    func completeVideoPreferences(
        token: UInt64,
        accepted: Bool,
        appliedBitrateKbps: UInt32,
        appliedFramesPerSecond: UInt32
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard token == pendingVideoPreferencesToken else { return [] }
            pendingVideoPreferencesToken = 0
            guard accepted else { return [] }
            // Adopt the applied values before the phase guard: the host already
            // reconfigured the encoder, so the advertised configuration must
            // track it even if a renegotiation is already in flight.
            configuration.bitrateKbps = appliedBitrateKbps
            configuration.framesPerSecond = appliedFramesPerSecond
            guard case .streaming(let configEpoch, let streamID) = phase else { return [] }
            return renegotiateSelectedDisplayLocked(
                displayID: "",
                configEpoch: configEpoch,
                streamID: streamID,
                correlationID: 0
            )
        }
    }

    /// Confirm a client HostActionInvoke after the host has run (or refused)
    /// the AppKit/Accessibility work on the main actor. Emits exactly one
    /// HostActionResult on the session FIFO for a tracked invocation and clears
    /// it; an unknown or duplicate invocation id is a safe no-op. The result is
    /// session-scoped so the client can match it against its outstanding
    /// invocation even across the auto-reconnect epoch guards. A rejection
    /// carries the host's localized error text; the session stays alive so the
    /// client can retry or fall back.
    func completeHostAction(
        invocationID: Data,
        accepted: Bool,
        rejectionReason: String
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard let requestMessageID = pendingHostActionInvocations.removeValue(forKey: invocationID) else { return [] }
            // The invocation was tracked, so emit its single result as long as
            // the control channel is still live. A tracked invocation can only
            // exist once the session reached STREAMING, but the session may have
            // since moved to AWAITING_VIDEO_CONFIG for an in-place display/video
            // reconfiguration when the host's MainActor completion lands. That
            // reconfig is not a terminal state, so the result must still be
            // delivered; only a closed/failed session drops it (and the
            // removeValue above already consumed the entry so no stale result
            // lingers).
            switch phase {
            case .streaming, .awaitingVideoConfig:
                break
            default:
                return []
            }
            var result = VSHostActionResult()
            result.invocationID = invocationID
            result.accepted = accepted
            result.rejectionReason = accepted ? "" : rejectionReason
            return sendActions(payload: .hostActionResult(result), correlationID: requestMessageID)
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

        let config = videoConfiguration(configEpoch: nextEpoch, streamID: streamID)
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
            hostHello.resourceLimits = hostResourceLimits()

            var accepted = VSSessionAccepted()
            accepted.sessionID = configuration.sessionID
            accepted.sessionEpoch = configuration.sessionEpoch
            accepted.heartbeatIntervalMs = 1_000
            accepted.negotiatedCapabilities = negotiatedCapabilities.sorted { $0.rawValue < $1.rawValue }
            accepted.negotiatedResourceLimits = negotiatedResourceLimits

            phase = .awaitingDisplayStart
            do {
                var actions: [ProtocolV1SessionAction] = [
                    .sendControl(try encode(
                        payload: .hostHello(hostHello),
                        correlationID: correlationID,
                        sessionScoped: false
                    )),
                    .sendControl(try encode(payload: .sessionAccepted(accepted), correlationID: correlationID))
                ]
                // Advertise the host action catalog immediately after the
                // session is accepted, but only when the client negotiated
                // HOST_ACTIONS. An ungated client never learns the catalog and
                // its invocations are rejected as unsupported.
                if negotiatedCapabilities.contains(.hostActions) {
                    var catalog = VSHostActionCatalog()
                    catalog.actions = Self.hostActionCatalog.map { entry in
                        var descriptor = VSHostActionDescriptor()
                        descriptor.actionID = entry.id
                        descriptor.localizedName = entry.name
                        descriptor.requiresConfirmation = entry.requiresConfirmation
                        return descriptor
                    }
                    actions.append(.sendControl(try encode(
                        payload: .hostActionCatalog(catalog),
                        correlationID: correlationID
                    )))
                }
                return actions
            } catch {
                return serializationFailure()
            }
        }
    }

    func completeFileOffer(
        transferID: Data,
        accepted: Bool,
        maximumChunkBytes: UInt32,
        rejectionReason: String
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard let correlationID = pendingFileOffers.removeValue(forKey: transferID),
                  case .streaming = phase else { return [] }
            var response = VSFileAccept()
            response.transferID = transferID
            let negotiatedMaximum = min(maximumChunkBytes, negotiatedResourceLimits.maximumFileChunkBytes)
            let canAccept = accepted && negotiatedMaximum > 0
            response.accepted = canAccept
            response.maximumChunkBytes = canAccept ? negotiatedMaximum : 0
            response.rejectionReason = canAccept ? "" : rejectionReason
            if canAccept { activeFileTransfers.insert(transferID) }
            return sendActions(payload: .fileAccept(response), correlationID: correlationID)
        }
    }

    func makeFileProgress(transferID: Data, receivedBytes: UInt64) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard case .streaming = phase, activeFileTransfers.contains(transferID) else { return [] }
            var progress = VSFileTransferProgress()
            progress.transferID = transferID
            progress.receivedBytes = receivedBytes
            return sendActions(payload: .fileTransferProgress(progress), correlationID: 0)
        }
    }

    func completeFileTransfer(
        transferID: Data,
        accepted: Bool,
        sha256: Data,
        rejectionReason: String
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard case .streaming = phase, activeFileTransfers.remove(transferID) != nil else { return [] }
            var result = VSFileTransferComplete()
            result.transferID = transferID
            result.accepted = accepted
            result.sha256 = accepted ? sha256 : Data()
            result.rejectionReason = accepted ? "" : rejectionReason
            return sendActions(payload: .fileTransferComplete(result), correlationID: 0)
        }
    }

    func acceptsFileChunk(transferID: Data, sessionEpoch: UInt64) -> Bool {
        withSessionLock {
            sessionEpoch == configuration.sessionEpoch &&
                negotiatedCapabilities.contains(.fileTransfer) &&
                activeFileTransfers.contains(transferID) &&
                isStreaming
        }
    }

    func completeWakeRequest(
        requestID: Data,
        accepted: Bool,
        rejectionReason: String
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard let correlationID = pendingWakeRequests.removeValue(forKey: requestID),
                  case .streaming = phase else { return [] }
            var result = VSWakeHostResult()
            result.requestID = requestID
            result.accepted = accepted
            result.rejectionReason = accepted ? "" : rejectionReason
            return sendActions(payload: .wakeHostResult(result), correlationID: correlationID)
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
            if !result.accepted,
               negotiatedCapabilities.contains(.colorManagement),
               !attemptedColorFallback,
               validSDRColor(result.selectedColorDescription),
               configEpoch < UInt64.max {
                attemptedColorFallback = true
                let nextEpoch = configEpoch + 1
                phase = .awaitingVideoConfig(configEpoch: nextEpoch, streamID: streamID)
                var fallback = videoConfiguration(configEpoch: nextEpoch, streamID: streamID)
                fallback.colorDescription = result.selectedColorDescription
                return sendActions(
                    payload: .videoConfig(fallback),
                    correlationID: envelope.messageID
                )
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
            if negotiatedCapabilities.contains(.audio) {
                audioAccepted = false
                nextAudioSequence = 0
                var audio = VSAudioConfig()
                audio.streamID = streamID
                audio.configEpoch = audioConfigEpoch
                audio.codec = .pcmS16Le
                audio.sampleRateHz = PCMAudioFormat.production.sampleRateHz
                audio.channelCount = PCMAudioFormat.production.channelCount
                audio.framesPerPacket = PCMAudioFormat.production.framesPerPacket
                do {
                    actions.append(.sendControl(try encode(payload: .audioConfig(audio), correlationID: 0)))
                } catch {
                    return serializationFailure()
                }
            }
            return actions + [.connectionReady, .requestKeyframe(force: true)]

        case .audioConfigResult(let result):
            guard negotiatedCapabilities.contains(.audio),
                  case .streaming(_, let streamID) = phase,
                  result.streamID == streamID,
                  result.configEpoch == audioConfigEpoch else {
                return invalidState("AudioConfigResult does not match the pending configuration.", envelope.messageID)
            }
            audioAccepted = result.accepted
            nextAudioSequence = 0
            return []

        case .clipboardContent(let content):
            guard negotiatedCapabilities.contains(.clipboard) else {
                return unsupportedCapability("Clipboard was not negotiated.", envelope.messageID)
            }
            guard case .streaming = phase else {
                return invalidState("ClipboardContent arrived before media was streaming.", envelope.messageID)
            }
            guard content.changeID.count == 16,
                  !content.originDeviceID.isEmpty,
                  content.originDeviceID.utf8.count <= 128,
                  content.content.count <= Int(negotiatedResourceLimits.maximumClipboardBytes),
                  content.sha256.count == 32 else {
                return invalidState("ClipboardContent exceeds negotiated boundaries.", envelope.messageID)
            }
            return [.clipboardContent(content)]

        case .fileOffer(let offer):
            guard negotiatedCapabilities.contains(.fileTransfer) else {
                return unsupportedCapability("File transfer was not negotiated.", envelope.messageID)
            }
            guard case .streaming = phase, offer.transferID.count == 16,
                  offer.byteLength > 0,
                  offer.byteLength <= negotiatedResourceLimits.maximumFileBytes,
                  offer.sha256.count == 32,
                  pendingFileOffers[offer.transferID] == nil,
                  pendingFileOffers.count < configuration.resourceLimits.maximumConcurrentFiles else {
                return invalidState("FileOffer is invalid or exceeds host limits.", envelope.messageID)
            }
            pendingFileOffers[offer.transferID] = envelope.messageID
            return [.fileOffer(offer)]

        case .fileTransferCancel(let cancel):
            guard negotiatedCapabilities.contains(.fileTransfer), case .streaming = phase else {
                return unsupportedCapability("File transfer was not negotiated.", envelope.messageID)
            }
            pendingFileOffers.removeValue(forKey: cancel.transferID)
            activeFileTransfers.remove(cancel.transferID)
            return [.fileCancel(transferID: cancel.transferID)]

        case .wakeHostRequest(let request):
            guard negotiatedCapabilities.contains(.wakeHost) else {
                return unsupportedCapability("Wake helper was not negotiated.", envelope.messageID)
            }
            guard case .streaming = phase, !request.requestID.isEmpty,
                  pendingWakeRequests[request.requestID] == nil,
                  pendingWakeRequests.count < 16 else {
                return invalidState("WakeHostRequest is invalid.", envelope.messageID)
            }
            pendingWakeRequests[request.requestID] = envelope.messageID
            return [.wakeHost(request)]

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

        case .stylusEvent(let stylus):
            guard negotiatedCapabilities.contains(.stylus) else {
                return unsupportedCapability("Stylus input was not negotiated.", envelope.messageID)
            }
            let pressure = stylus.pressure
            let tiltX = stylus.tiltXDegrees
            let tiltY = stylus.tiltYDegrees
            let extended = negotiatedCapabilities.contains(.stylusExtended)
            let toolKind: VSStylusToolKind = stylus.hasToolKind ? stylus.toolKind : .pen
            let contactState: VSStylusContactState = stylus.hasContactState
                ? stylus.contactState
                : .contact
            let terminalPhase = stylus.phase == .ended || stylus.phase == .cancelled
            guard isStreaming,
                  stylus.inputID > 0,
                  stylus.hasPosition,
                  stylus.position.x.isFinite,
                  stylus.position.y.isFinite,
                  (0...1).contains(stylus.position.x),
                  (0...1).contains(stylus.position.y),
                  pressure.isFinite,
                  (0...1).contains(pressure),
                  (!terminalPhase && contactState == .contact) || pressure == 0,
                  tiltX.isFinite,
                  tiltY.isFinite,
                  (-90...90).contains(tiltX),
                  (-90...90).contains(tiltY),
                  hypot(tiltX, tiltY) <= 90,
                  inputTargetMatchesActiveStream(stylus.hasTarget ? stylus.target : nil),
                  stylus.phase != .unspecified,
                  validatesStylusExtension(
                      stylus,
                      extended: extended,
                      toolKind: toolKind,
                      contactState: contactState
                  ),
                  stylusSequenceState.accepts(
                      pointerID: stylus.pointerID,
                      phase: stylus.phase,
                      toolKind: toolKind,
                      contactState: contactState
                  ) else {
                return invalidState("StylusEvent is invalid or media is not ready.", envelope.messageID)
            }
            return [.stylus(
                inputID: stylus.inputID,
                pointerID: stylus.pointerID,
                x: Float(stylus.position.x),
                y: Float(stylus.position.y),
                phase: stylus.phase,
                pressure: pressure,
                tiltXDegrees: tiltX,
                tiltYDegrees: tiltY,
                toolKind: toolKind,
                buttonMask: stylus.buttonMask,
                contactState: contactState
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
            guard case .streaming = phase else {
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
            // Do not mutate the advertised configuration or renegotiate yet.
            // The host applies the encoder change first and calls
            // completeVideoPreferences on success, which is the only place the
            // bumped-epoch VideoConfig is emitted. This keeps the advertised
            // VideoConfig from arriving before the encoder actually adopts the
            // settings, and keeps advertised == applied. Supersede any earlier
            // in-flight request so only the newest intent renegotiates.
            let token = nextVideoPreferencesToken
            nextVideoPreferencesToken &+= 1
            pendingVideoPreferencesToken = token
            // An explicit bitrate wins over the preset intent. A reset request
            // is honored only when no explicit bitrate is requested, matching
            // the "explicit bitrate overrides quality" contract.
            let resolvedPreset = prefs.bitrateKbps == 0 ? prefs.qualityPreset : .unspecified
            let resolvedReset = prefs.bitrateKbps == 0 ? prefs.resetQualityToAuto : false
            return [
                .applyVideoPreferences(
                    token: token,
                    bitrateKbps: clampedBitrate,
                    framesPerSecond: clampedFps,
                    qualityPreset: resolvedPreset,
                    resetQualityToAuto: resolvedReset
                )
            ]

        case .hostActionInvoke(let invoke):
            guard negotiatedCapabilities.contains(.hostActions) else {
                return unsupportedCapability("Host actions were not negotiated.", envelope.messageID)
            }
            guard case .streaming = phase else {
                return invalidState("HostActionInvoke arrived before media was streaming.", envelope.messageID)
            }
            guard Self.hostActionCatalog.contains(where: { $0.id == invoke.actionID }) else {
                return invalidState("HostActionInvoke referenced an unknown action id.", envelope.messageID)
            }
            guard !invoke.invocationID.isEmpty else {
                return invalidState("HostActionInvoke is missing an invocation id.", envelope.messageID)
            }
            // A targeted invoke must name the active stream. An empty
            // display_id + stream_id 0 means "unspecified" and is accepted; any
            // other target that does not match the currently captured display
            // and streaming stream is a stale/foreign target that must not act
            // on the active display.
            guard inputTargetMatchesActiveStream(invoke.hasTarget ? invoke.target : nil) else {
                return invalidState("HostActionInvoke target does not match the active display/stream.", envelope.messageID)
            }
            // An in-flight invocation with the same id is a client retransmit;
            // do not re-forward it. The host confirms the outcome later through
            // completeHostAction, which emits the single HostActionResult.
            guard pendingHostActionInvocations[invoke.invocationID] == nil else { return [] }
            // Bound the outstanding set so a client cannot grow it without limit
            // by never letting the host complete an invocation.
            guard pendingHostActionInvocations.count < Self.maximumPendingHostActionInvocations else {
                return invalidState("Too many host actions are awaiting confirmation.", envelope.messageID)
            }
            // Remember the request message_id so the eventual HostActionResult
            // carries it as the Envelope correlation_id.
            pendingHostActionInvocations[invoke.invocationID] = envelope.messageID
            return [.hostAction(
                actionID: invoke.actionID,
                invocationID: invoke.invocationID,
                target: invoke.hasTarget ? invoke.target : nil
            )]

        case .protocolError(let error):
            phase = .failed
            _ = stylusSequenceState.consumeReset()
            pendingHostActionInvocations.removeAll()
            pendingFileOffers.removeAll()
            activeFileTransfers.removeAll()
            pendingWakeRequests.removeAll()
            audioAccepted = false
            return [.peerError(error), .close]

        case .disconnectNotice:
            phase = .closed
            _ = stylusSequenceState.consumeReset()
            pendingHostActionInvocations.removeAll()
            pendingFileOffers.removeAll()
            activeFileTransfers.removeAll()
            pendingWakeRequests.removeAll()
            audioAccepted = false
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

    func makeAudioPacket(payload: Data, frameCount: UInt32) throws -> Data? {
        try withSessionLock {
            guard audioAccepted,
                  case .streaming(_, let streamID) = phase,
                  nextAudioSequence < UInt64.max,
                  frameCount == PCMAudioFormat.production.framesPerPacket,
                  payload.count == PCMAudioFormat.production.bytesPerPacket else { return nil }
            var header = VSAudioPacketHeader()
            header.streamID = streamID
            header.sessionEpoch = configuration.sessionEpoch
            header.configEpoch = audioConfigEpoch
            header.sequence = nextAudioSequence
            header.frameCount = frameCount
            nextAudioSequence += 1
            return try ProtocolV1AudioPacketCodec.encode(header: header, payload: payload)
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

    /// Stable window-migration action IDs. The client (Android and iOS) binds
    /// gestures/controls to these exact IDs, so they are part of the wire
    /// contract and must not drift. The localized names are host-facing labels
    /// the client may show verbatim.
    static let moveWindowActionID = "move-window"
    static let returnWindowsActionID = "return-windows"
    private static let hostActionCatalog: [(id: String, name: String, requiresConfirmation: Bool)] = [
        (moveWindowActionID, "Move Focused Window", false),
        (returnWindowsActionID, "Return Moved Windows", false)
    ]
    /// Upper bound on host-action invocations awaiting host confirmation. A
    /// misbehaving client that streams unique invocation_ids without waiting for
    /// results can never grow this set without bound: past the cap the invoke is
    /// rejected with invalidState and the protocol session fails closed. The
    /// window actions are effectively serial in practice, so a small cap is ample.
    private static let maximumPendingHostActionInvocations = 16

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

    private func validatesStylusExtension(
        _ stylus: VSStylusEvent,
        extended: Bool,
        toolKind: VSStylusToolKind,
        contactState: VSStylusContactState
    ) -> Bool {
        if !extended {
            return !stylus.hasToolKind && !stylus.hasContactState && stylus.buttonMask == 0
        }
        guard stylus.hasToolKind, stylus.hasContactState,
              toolKind == .pen || toolKind == .eraser,
              contactState == .contact || contactState == .proximity,
              stylus.buttonMask & ~UInt32(0b11) == 0 else { return false }
        return contactState != .proximity || stylus.pressure == 0
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
        guard requiredCapabilities.isSubset(of: offeredCapabilities) else {
            return fail(
                code: .unsupportedCapability,
                message: "ClientHello required capabilities were not included in its offer.",
                correlationID: correlationID
            )
        }
        guard requiredCapabilities.isSubset(of: configuration.hostCapabilities) else {
            return fail(
                code: .unsupportedCapability,
                message: "Host does not implement a capability required by the client.",
                correlationID: correlationID
            )
        }
        guard !requiredCapabilities.contains(.stylusExtended)
                || offeredCapabilities.contains(.stylus) else {
            return fail(
                code: .unsupportedCapability,
                message: "Extended stylus requires base stylus input.",
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
        var negotiatedCapabilities = configuration.hostCapabilities.intersection(offeredCapabilities)
        if !negotiatedCapabilities.contains(.stylus) {
            negotiatedCapabilities.remove(.stylusExtended)
        }
        if negotiatedCapabilities.contains(.audio), hello.resourceLimits.maximumAudioStreams == 0 {
            negotiatedCapabilities.remove(.audio)
        }
        if negotiatedCapabilities.contains(.clipboard), hello.resourceLimits.maximumClipboardBytes == 0 {
            negotiatedCapabilities.remove(.clipboard)
        }
        if negotiatedCapabilities.contains(.fileTransfer),
           (hello.resourceLimits.maximumFileBytes == 0 || hello.resourceLimits.maximumFileChunkBytes == 0) {
            negotiatedCapabilities.remove(.fileTransfer)
        }
        if requiredCapabilities.contains(.audio), !negotiatedCapabilities.contains(.audio) {
            return fail(code: .unsupportedCapability, message: "Audio requires a nonzero stream limit.", correlationID: correlationID)
        }
        if requiredCapabilities.contains(.fileTransfer), !negotiatedCapabilities.contains(.fileTransfer) {
            return fail(code: .unsupportedCapability, message: "File transfer requires nonzero limits.", correlationID: correlationID)
        }
        if requiredCapabilities.contains(.clipboard), !negotiatedCapabilities.contains(.clipboard) {
            return fail(code: .unsupportedCapability, message: "Clipboard requires a nonzero byte limit.", correlationID: correlationID)
        }
        self.negotiatedCapabilities = negotiatedCapabilities
        negotiatedResourceLimits = negotiateResourceLimits(hello.resourceLimits, capabilities: negotiatedCapabilities)

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

        let config = videoConfiguration(configEpoch: configEpoch, streamID: streamID)
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

    private func videoConfiguration(configEpoch: UInt64, streamID: UInt64) -> VSVideoConfig {
        var config = VSVideoConfig()
        config.configEpoch = configEpoch
        config.codec = selectedCodec
        config.encodedSize = dimensions()
        config.framesPerSecond = configuration.framesPerSecond
        config.bitrateKbps = configuration.bitrateKbps
        config.streamID = streamID
        config.rotationDegrees = UInt32(clamping: configuration.rotation)
        if negotiatedCapabilities.contains(.colorManagement) {
            config.colorDescription = HostVideoColor.sdr
        }
        return config
    }

    private func validSDRColor(_ color: VSColorDescription) -> Bool {
        color.bitDepth == 8 &&
            color.primaries == .bt709 &&
            (color.transferFunction == .bt709 || color.transferFunction == .srgb) &&
            color.matrixCoefficients == .bt709
    }

    private func hostResourceLimits() -> VSResourceLimits {
        var limits = VSResourceLimits()
        limits.maximumClients = 1
        limits.maximumDisplays = UInt32(max(1, configuredDisplays().count))
        limits.maximumVideoStreams = 1
        if configuration.hostCapabilities.contains(.audio) { limits.maximumAudioStreams = 1 }
        if configuration.hostCapabilities.contains(.clipboard) {
            limits.maximumClipboardBytes = UInt64(configuration.resourceLimits.maximumClipboardBytes)
        }
        if configuration.hostCapabilities.contains(.fileTransfer) {
            limits.maximumFileBytes = configuration.resourceLimits.maximumFileBytes
            limits.maximumFileChunkBytes = UInt32(configuration.resourceLimits.maximumFileChunkBytes)
        }
        return limits
    }

    private func negotiateResourceLimits(
        _ peer: VSResourceLimits,
        capabilities: Set<VSCapability>
    ) -> VSResourceLimits {
        let host = hostResourceLimits()
        var result = VSResourceLimits()
        result.maximumClients = 1
        result.maximumDisplays = minNonzero(host.maximumDisplays, peer.maximumDisplays)
        result.maximumVideoStreams = 1
        if capabilities.contains(.audio) { result.maximumAudioStreams = 1 }
        if capabilities.contains(.clipboard) {
            result.maximumClipboardBytes = minNonzero(host.maximumClipboardBytes, peer.maximumClipboardBytes)
        }
        if capabilities.contains(.fileTransfer) {
            result.maximumFileBytes = minNonzero(host.maximumFileBytes, peer.maximumFileBytes)
            result.maximumFileChunkBytes = minNonzero(
                host.maximumFileChunkBytes,
                peer.maximumFileChunkBytes
            )
        }
        return result
    }

    private func minNonzero<T: FixedWidthInteger>(_ first: T, _ second: T) -> T {
        guard first > 0, second > 0 else { return 0 }
        return min(first, second)
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
        _ = stylusSequenceState.consumeReset()
        pendingHostActionInvocations.removeAll()
        pendingFileOffers.removeAll()
        activeFileTransfers.removeAll()
        pendingWakeRequests.removeAll()
        audioAccepted = false
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
        _ = stylusSequenceState.consumeReset()
        audioAccepted = false
        return [.close]
    }

    private func withSessionLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
