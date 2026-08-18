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

struct ManagedPolicy: Equatable {
    static let defaultMaximumFileBytes: UInt64 = 512 * 1_024 * 1_024
    static let defaultMaximumAudioStreams: UInt32 = 1
    static let defaultMaximumClipboardBytes: UInt64 = 1 * 1_024 * 1_024
    static let defaultMaximumFileChunkBytes: UInt32 = 64 * 1_024

    let isManaged: Bool
    let clipboardAllowed: Bool
    let fileTransferAllowed: Bool
    let audioAllowed: Bool
    let wakeAllowed: Bool
    let customGesturesAllowed: Bool
    let hostActionsAllowed: Bool
    let maximumFileBytes: UInt64
    let allowedHosts: Set<String>

    static let unmanaged = ManagedPolicy(
        isManaged: false,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: defaultMaximumFileBytes,
        allowedHosts: []
    )

    init(
        isManaged: Bool,
        clipboardAllowed: Bool,
        fileTransferAllowed: Bool,
        audioAllowed: Bool,
        wakeAllowed: Bool,
        customGesturesAllowed: Bool,
        hostActionsAllowed: Bool,
        maximumFileBytes: UInt64,
        allowedHosts: Set<String>
    ) {
        self.isManaged = isManaged
        self.clipboardAllowed = clipboardAllowed
        self.fileTransferAllowed = fileTransferAllowed
        self.audioAllowed = audioAllowed
        self.wakeAllowed = wakeAllowed
        self.customGesturesAllowed = customGesturesAllowed
        self.hostActionsAllowed = hostActionsAllowed
        self.maximumFileBytes = maximumFileBytes
        self.allowedHosts = allowedHosts
    }

    init(remoteStatus: VSManagedPolicyStatus) {
        guard remoteStatus.managed else {
            self = .unmanaged
            return
        }
        self.init(
            isManaged: true,
            clipboardAllowed: remoteStatus.clipboardAllowed,
            fileTransferAllowed: remoteStatus.fileTransferAllowed,
            audioAllowed: remoteStatus.audioAllowed,
            wakeAllowed: remoteStatus.wakeAllowed,
            customGesturesAllowed: remoteStatus.customGesturesAllowed,
            hostActionsAllowed: remoteStatus.hostActionsAllowed,
            maximumFileBytes: remoteStatus.maximumFileBytes,
            allowedHosts: Set(remoteStatus.allowedHosts.filter { !$0.isEmpty })
        )
    }

    var protocolStatus: VSManagedPolicyStatus {
        var status = VSManagedPolicyStatus()
        status.managed = isManaged
        status.clipboardAllowed = clipboardAllowed
        status.fileTransferAllowed = fileTransferAllowed
        status.audioAllowed = audioAllowed
        status.wakeAllowed = wakeAllowed
        status.customGesturesAllowed = customGesturesAllowed
        status.hostActionsAllowed = hostActionsAllowed
        status.maximumFileBytes = maximumFileBytes
        status.allowedHosts = allowedHosts.sorted()
        return status
    }

    func applying(remote: ManagedPolicy) -> ManagedPolicy {
        guard remote.isManaged else { return self }
        return ManagedPolicy(
            isManaged: true,
            clipboardAllowed: clipboardAllowed && remote.clipboardAllowed,
            fileTransferAllowed: fileTransferAllowed && remote.fileTransferAllowed,
            audioAllowed: audioAllowed && remote.audioAllowed,
            wakeAllowed: wakeAllowed && remote.wakeAllowed,
            customGesturesAllowed: customGesturesAllowed && remote.customGesturesAllowed,
            hostActionsAllowed: hostActionsAllowed && remote.hostActionsAllowed,
            maximumFileBytes: min(maximumFileBytes, remote.maximumFileBytes),
            allowedHosts: allowedHosts.isEmpty ? remote.allowedHosts :
                (remote.allowedHosts.isEmpty ? allowedHosts : allowedHosts.intersection(remote.allowedHosts))
        )
    }

    func allows(hostID: String) -> Bool {
        allowedHosts.isEmpty || allowedHosts.contains(hostID)
    }

    static let advertisedCapabilities: Set<VSCapability> = [.managedConfiguration]

    func applyingResourceLimits(to limits: inout VSResourceLimits) {
        limits.maximumAudioStreams = audioAllowed ? limits.maximumAudioStreams : 0
        limits.maximumClipboardBytes = clipboardAllowed ? limits.maximumClipboardBytes : 0
        limits.maximumFileBytes = fileTransferAllowed ? min(limits.maximumFileBytes, maximumFileBytes) : 0
        limits.maximumFileChunkBytes = fileTransferAllowed ? limits.maximumFileChunkBytes : 0
    }
}

struct ManagedPolicyResolver: Equatable {
    private(set) var localPolicy: ManagedPolicy
    private(set) var remotePolicy: ManagedPolicy?

    var effectivePolicy: ManagedPolicy {
        remotePolicy.map { localPolicy.applying(remote: $0) } ?? localPolicy
    }

    init(localPolicy: ManagedPolicy = .unmanaged, remotePolicy: ManagedPolicy? = nil) {
        self.localPolicy = localPolicy
        self.remotePolicy = remotePolicy
    }

    mutating func setRemote(_ policy: ManagedPolicy?) {
        remotePolicy = policy
    }

    mutating func clearRemote() {
        remotePolicy = nil
    }
}

struct ProtocolV1SessionConfiguration {
    static let version: UInt32 = 1

    static func productionHostCapabilities(
        touchEnabled: Bool,
        controllerAvailable: Bool = false,
        managedPolicy: ManagedPolicy = .unmanaged
    ) -> Set<VSCapability> {
        // Native pointer/keyboard ride the same input toggle as touch: they
        // require Accessibility to actually inject, but the capability is
        // advertised so a USB session can negotiate them. When input is
        // disabled entirely, only multi-display selection is offered.
        // Client video control tunes the host encoder, needs no Accessibility,
        // and is always offered so the client can adjust bitrate/fps/quality.
        // Clipboard does not require Accessibility, but local managed policy
        // can deny it before HostHello so the peer's intersection check still
        // matches SessionAccepted.
        var capabilities: Set<VSCapability> = touchEnabled
            ? [.touch, .stylus, .stylusExtended, .keyboard, .pointer, .multiDisplay, .clientVideoControl, .usbHidModifierByte, .managedConfiguration]
            : [.multiDisplay, .clientVideoControl, .managedConfiguration]
        capabilities.formUnion(ManagedPolicy.advertisedCapabilities)
        if managedPolicy.clipboardAllowed { capabilities.insert(.clipboard) }
        if touchEnabled && managedPolicy.hostActionsAllowed { capabilities.insert(.hostActions) }
        if controllerAvailable { capabilities.insert(.controller) }
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
   /// Full catalog exposed by ListDisplays. When empty, the session
   /// synthesizes a single entry from the currently captured identity so the
   /// single-display path keeps ListDisplays count == 1.
   var displays: [ProtocolV1DisplayInfo] = []
    var managedPolicy: ManagedPolicy = .unmanaged
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
    case controller(event: GameControllerInputEvent, correlationID: UInt64)
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
    /// A remote peer offered clipboard content. The server forwards the
    /// metadata to the UI so the user can approve a content request.
    case clipboardOffer(ClipboardOfferMetadata)
    /// A remote peer sent clipboard content that matched a pending request.
    /// The server forwards the validated text to the UI for pasteboard write.
    case clipboardContent(ValidatedClipboardContent)
    /// A remote peer sent clipboard content without a matching pending
    /// offer/request. The server forwards it to the UI as an unsolicited
    /// transfer that still requires explicit local approval.
    case clipboardDirectContent(ValidatedClipboardContent)
   case peerError(VSProtocolError)
   case close
}

final class ProtocolV1SessionCoordinator {
    private struct PendingControllerConnection {
        let controllerID: String
        let controllerEpoch: UInt64
        let correlationID: UInt64
    }

    private(set) var phase: ProtocolV1SessionPhase = .awaitingClientHello
    private(set) var selectedCodec: VSCodec = .unspecified
    private(set) var lastReceivedMessageID: UInt64 = 0
    private(set) var nextFrameID: UInt64 = 1

    private var configuration: ProtocolV1SessionConfiguration
    private var nextMessageID: UInt64 = 1
    private var baseNegotiatedCapabilities: Set<VSCapability> = []
    private var negotiatedCapabilities: Set<VSCapability> = []
    private var stylusSequenceState = StylusSequenceState()
    private var controllerSequenceState = GameControllerStateMachine()
    private var pendingControllerConnections: [UInt64: PendingControllerConnection] = [:]
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
    private var managedPolicyResolver: ManagedPolicyResolver
    /// Host-action invocations the host is currently running, keyed by the
    /// client's invocation_id and mapped to the request's Envelope message_id.
    /// The result echoes both the invocation_id (in the payload) and the
    /// request message_id (as the Envelope correlation_id), so a duplicate or
    /// unknown completion is a safe no-op. Bounded by
    /// maximumPendingHostActionInvocations.
    private var pendingHostActionInvocations: [Data: UInt64] = [:]

    /// The remote peer's device identity captured from ClientHello. Every
    /// incoming clipboard offer/content must carry this exact, non-empty
    /// origin; otherwise the message is rejected.
    private var clientDeviceID: String = ""
    /// The negotiated clipboard byte limit: min(host local cap, peer's
    /// non-zero maximum_clipboard_bytes). Zero means clipboard was not
    /// negotiated.
    private var negotiatedMaximumClipboardBytes: Int = 0
    /// Session-scoped clipboard state. Created only when the client
    /// negotiated CAPABILITY_CLIPBOARD; nil otherwise so all clipboard
    /// messages are rejected for legacy/non-negotiated peers.
    private var clipboardCore: ClipboardCore?
    /// Remote managed-policy status for clipboard. MacHost has no local MDM
    /// policy integration in this slice, so local policy is permissive. A
    /// managed remote status with clipboard_allowed=false denies clipboard
    /// transfer for the active session and clears any staged clipboard state.
    private var remoteManagedClipboardAllowed = true

    init(configuration: ProtocolV1SessionConfiguration) {
        precondition(!configuration.sessionID.isEmpty)
        precondition(configuration.sessionEpoch > 0)
        self.configuration = configuration
        self.managedPolicyResolver = ManagedPolicyResolver(localPolicy: configuration.managedPolicy)
    }

    var effectiveManagedPolicy: ManagedPolicy {
        withSessionLock { managedPolicyResolver.effectivePolicy }
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

    /// Completes one native controller CONNECTED delivery. The pending entry
    /// owns the request correlation so callers cannot acknowledge a different
    /// lifecycle, and removal before encoding makes duplicate completions a
    /// safe no-op. The table is bounded by the four admitted controller slots.
    func completeControllerConnection(
        _ event: GameControllerInputEvent
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard event.kind == .connected,
                  let pending = pendingControllerConnections[event.inputID],
                  pending.controllerID == event.controllerID,
                  pending.controllerEpoch == event.controllerEpoch else { return [] }
            pendingControllerConnections.removeValue(forKey: event.inputID)
            switch phase {
            case .streaming, .awaitingVideoConfig:
                break
            default:
                return []
            }
            var acknowledgement = VSInputAck()
            acknowledgement.inputID = event.inputID
            acknowledgement.accepted = true
            return sendActions(
                payload: .inputAck(acknowledgement),
                correlationID: pending.correlationID
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
            // Echo the negotiated resource limits back to the client so both
            // sides agree on the clipboard byte ceiling. HostHello carries the
            // host's view; SessionAccepted carries the jointly negotiated
            // value. They are identical for clipboard.
            var hostLimits = VSResourceLimits()
            hostLimits.maximumClipboardBytes = UInt64(negotiatedMaximumClipboardBytes)
            hostHello.resourceLimits = hostLimits

            var accepted = VSSessionAccepted()
            accepted.sessionID = configuration.sessionID
            accepted.sessionEpoch = configuration.sessionEpoch
            accepted.heartbeatIntervalMs = 1_000
            accepted.negotiatedCapabilities = negotiatedCapabilities.sorted { $0.rawValue < $1.rawValue }
            accepted.negotiatedResourceLimits = negotiatedResourceLimits()

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
                if negotiatedCapabilities.contains(.managedConfiguration) {
                    actions.append(.sendControl(try encode(
                        payload: .managedPolicyStatus(managedPolicyResolver.localPolicy.protocolStatus),
                        correlationID: correlationID
                    )))
                }
                return actions
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
            guard acceptsInputPhase(touch.phase), touch.hasPosition,
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
            guard acceptsInputPhase(stylus.phase),
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
            guard acceptsInputPhase(pointer.phase), pointer.hasPosition,
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
            let standardByteNegotiated = negotiatedCapabilities.contains(.usbHidModifierByte)
            guard acceptsKeyEvent(pressed: key.pressed),
                  StreamInputWire.validatesModifierMask(
                    key.modifierMask,
                    standardByteNegotiated: standardByteNegotiated
                  ) else {
                return invalidState("KeyEvent is invalid or media is not ready.", envelope.messageID)
            }
            return [.key(
                usage: key.usbHidUsage,
                pressed: key.pressed,
                modifiers: StreamInputWire.standardModifierMask(
                    fromWireMask: key.modifierMask,
                    standardByteNegotiated: standardByteNegotiated
                ),
                text: key.text
            )]

        case .controllerEvent(let controller):
            guard negotiatedCapabilities.contains(.controller) else {
                return unsupportedCapability("Controller input was not negotiated.", envelope.messageID)
            }
            // During a video reconfiguration the stream is not yet accepted,
            // so only the neutral DISCONNECTED lifecycle marker is allowed.
            // This mirrors touch ended/cancelled and key release, which are
            // the terminal input events permitted while media is gated.
            guard acceptsControllerKind(controller.kind),
                  inputTargetMatchesActiveStream(controller.hasTarget ? controller.target : nil),
                  let event = GameControllerInputEvent(wireEvent: controller) else {
                return invalidState("ControllerEvent is invalid or media is not ready.", envelope.messageID)
            }
            if event.kind != .connected,
               pendingControllerConnections.values.contains(where: { pending in
                   pending.controllerID == event.controllerID
                       && pending.controllerEpoch == event.controllerEpoch
               }) {
                return invalidState(
                    "Controller STATE or DISCONNECTED arrived before CONNECTED was acknowledged.",
                    envelope.messageID
                )
            }
            // The state machine owns lifecycle admission and the monotonic
            // controller input_id. A fifth concurrent CONNECTED is the only
            // soft rejection; it consumes input_id while preserving all four
            // admitted controller lifecycles.
            let admission: GameControllerAdmissionResult
            do {
                admission = try controllerSequenceState.accept(event)
            } catch {
                return invalidState("ControllerEvent violates the controller state machine.", envelope.messageID)
            }
            switch admission {
            case .accepted:
                if event.kind == .connected {
                    guard pendingControllerConnections.count
                            < GameControllerContract.maximumActiveControllers,
                          pendingControllerConnections[event.inputID] == nil else {
                        return invalidState(
                            "Controller CONNECTED acknowledgement state is inconsistent.",
                            envelope.messageID
                        )
                    }
                    pendingControllerConnections[event.inputID] = PendingControllerConnection(
                        controllerID: event.controllerID,
                        controllerEpoch: event.controllerEpoch,
                        correlationID: envelope.messageID
                    )
                }
                return [.controller(event: event, correlationID: envelope.messageID)]
            case .rejectedMaximumActiveControllers:
                var ack = VSInputAck()
                ack.inputID = event.inputID
                ack.accepted = false
                ack.rejectionReason = GameControllerContract.maximumActiveControllersRejectionReason
                return sendActions(payload: .inputAck(ack), correlationID: envelope.messageID)
            }

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
            guard managedPolicyResolver.effectivePolicy.hostActionsAllowed else {
                return unsupportedCapability("Host actions are denied by managed policy.", envelope.messageID)
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

        case .clipboardOffer(let offer):
            return handleIncomingClipboardOffer(offer, correlationID: envelope.messageID)

        case .clipboardRequest(let request):
            return handleIncomingClipboardRequest(request, correlationID: envelope.messageID)

        case .clipboardContent(let content):
            return handleIncomingClipboardContent(content, correlationID: envelope.messageID)

        case .managedPolicyStatus(let status):
            return handleManagedPolicyStatus(status, correlationID: envelope.messageID)

        case .protocolError(let error):
            phase = .failed
            _ = stylusSequenceState.consumeReset()
            resetControllerState()
            pendingHostActionInvocations.removeAll()
            clipboardCore?.reset()
            remoteManagedClipboardAllowed = true
            managedPolicyResolver.clearRemote()
            return [.peerError(error), .close]

        case .disconnectNotice:
            phase = .closed
            _ = stylusSequenceState.consumeReset()
            resetControllerState()
            pendingHostActionInvocations.removeAll()
            clipboardCore?.reset()
            remoteManagedClipboardAllowed = true
            managedPolicyResolver.clearRemote()
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

    func rejectControllerInjection(
        _ message: String,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        withSessionLock {
            fail(
                code: .invalidState,
                message: message,
                correlationID: correlationID
            )
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

    private func acceptsInputPhase(_ inputPhase: VSInputPhase) -> Bool {
        switch phase {
        case .streaming:
            return true
        case .awaitingVideoConfig:
            return inputPhase == .ended || inputPhase == .cancelled
        default:
            return false
        }
    }

    private func acceptsKeyEvent(pressed: Bool) -> Bool {
        switch phase {
        case .streaming:
            return true
        case .awaitingVideoConfig:
            return !pressed
        default:
            return false
        }
    }

    /// Controller lifecycle events are gated by the streaming phase. During a
    /// video reconfiguration only the neutral DISCONNECTED marker is allowed,
    /// matching the touch ended/cancelled and key-release termination
    /// semantics so a client can cleanly tear down a controller while the
    /// host renegotiates the video stream.
    private func acceptsControllerKind(_ kind: VSControllerEventKind) -> Bool {
        switch phase {
        case .streaming:
            return true
        case .awaitingVideoConfig:
            return kind == .disconnected
        default:
            return false
        }
    }

    /// Whether the peer negotiated CAPABILITY_CLIPBOARD. Exposed so the UI
    /// layer can decide whether to show clipboard controls without reaching
    /// into the session's private capability set.
    var hasClipboardCapability: Bool {
        withSessionLock {
            negotiatedCapabilities.contains(.clipboard) && remoteManagedClipboardAllowed
        }
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
        let streamID: UInt64
        switch phase {
        case .streaming(_, let activeStreamID), .awaitingVideoConfig(_, let activeStreamID):
            streamID = activeStreamID
        default:
            return false
        }
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
        guard !offeredCapabilities.contains(.usbHidModifierByte)
                || offeredCapabilities.contains(.keyboard) else {
            return fail(
                code: .unsupportedCapability,
                message: "USB HID modifier-byte capability requires keyboard input.",
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
        var baseNegotiatedCapabilities = configuration.hostCapabilities.intersection(offeredCapabilities)
        if !baseNegotiatedCapabilities.contains(.stylus) {
            baseNegotiatedCapabilities.remove(.stylusExtended)
        }
        if !baseNegotiatedCapabilities.contains(.keyboard) {
            baseNegotiatedCapabilities.remove(.usbHidModifierByte)
        }
        self.baseNegotiatedCapabilities = baseNegotiatedCapabilities
        self.negotiatedCapabilities = policyFilteredCapabilities(
            baseNegotiatedCapabilities,
            policy: managedPolicyResolver.effectivePolicy
        )
        remoteManagedClipboardAllowed = managedPolicyResolver.effectivePolicy.clipboardAllowed

        // Capture the peer's device identity. Every incoming clipboard
        // offer/content must originate from this exact device; an empty or
        // mismatched origin is rejected. When clipboard is negotiated the
        // device ID must be non-empty so origin validation is meaningful.
        clientDeviceID = hello.deviceID
        if self.negotiatedCapabilities.contains(.clipboard) {
            guard !clientDeviceID.isEmpty else {
                return fail(
                    code: .invalidState,
                    message: "ClientHello.device_id is required when clipboard is negotiated.",
                    correlationID: correlationID
                )
            }
        }

        // Negotiate the clipboard byte limit. The host caps at 1 MiB; the
        // peer's non-zero maximum_clipboard_bytes further constrains it. A
        // zero peer limit means "unbounded from the peer side", so the host
        // cap wins. When clipboard was not negotiated the limit stays zero
        // and no ClipboardCore is created.
        if self.negotiatedCapabilities.contains(.clipboard) {
            let peerLimit = hello.resourceLimits.maximumClipboardBytes
            let hostLimit = UInt64(ClipboardCore.localMaximumBytes)
            negotiatedMaximumClipboardBytes = peerLimit == 0
                ? Int(hostLimit)
                : Int(min(hostLimit, peerLimit))
            clipboardCore = ClipboardCore(
                maximumBytes: negotiatedMaximumClipboardBytes,
                localDeviceID: configuration.hostID,
                remoteDeviceID: clientDeviceID
            )
        } else {
            negotiatedMaximumClipboardBytes = 0
            clipboardCore = nil
        }

        phase = .preparingCodec(correlationID: correlationID)
        let streamCodec: StreamCodec = codec == .h264 ? .h264 : .hevc
        return [.codecNegotiated(streamCodec)]
    }

    private func negotiatedResourceLimits() -> VSResourceLimits {
        var limits = VSResourceLimits()
        limits.maximumClients = 1
        limits.maximumDisplays = UInt32(max(1, configuredDisplays().count))
        limits.maximumVideoStreams = 1
        limits.maximumAudioStreams = ManagedPolicy.defaultMaximumAudioStreams
        limits.maximumClipboardBytes = negotiatedMaximumClipboardBytes > 0
            ? UInt64(negotiatedMaximumClipboardBytes)
            : ManagedPolicy.defaultMaximumClipboardBytes
        limits.maximumFileBytes = ManagedPolicy.defaultMaximumFileBytes
        limits.maximumFileChunkBytes = ManagedPolicy.defaultMaximumFileChunkBytes
        managedPolicyResolver.effectivePolicy.applyingResourceLimits(to: &limits)
        return limits
    }

    private func policyFilteredCapabilities(
        _ capabilities: Set<VSCapability>,
        policy: ManagedPolicy
    ) -> Set<VSCapability> {
        var filtered = capabilities
        if !policy.clipboardAllowed { filtered.remove(.clipboard) }
        if !policy.fileTransferAllowed { filtered.remove(.fileTransfer) }
        if !policy.audioAllowed { filtered.remove(.audio) }
        if !policy.wakeAllowed { filtered.remove(.wakeHost) }
        if !policy.hostActionsAllowed { filtered.remove(.hostActions) }
        return filtered
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

    private static func unmanagedPolicyStatus() -> VSManagedPolicyStatus {
        var status = VSManagedPolicyStatus()
        status.managed = false
        status.clipboardAllowed = true
        status.fileTransferAllowed = true
        status.audioAllowed = true
        status.wakeAllowed = true
        status.customGesturesAllowed = true
        status.hostActionsAllowed = true
        return status
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

    // MARK: - Clipboard

    /// Explicit user share: cache a single snapshot of the given string and
    /// emit a ClipboardOffer. The caller must read the pasteboard on the main
    /// thread before calling this; the core never touches NSPasteboard.
    /// Returns an empty action list when clipboard was not negotiated.
    func shareClipboard(text: String) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard let core = clipboardCore else { return [] }
            guard remoteManagedClipboardAllowed else { return [] }
            guard isStreaming else { return [] }
            do {
                let offer = try core.prepareOffer(text: text)
                return sendActions(payload: .clipboardOffer(offer), correlationID: 0)
            } catch {
                // This is a local UI operation. Invalid or stale local input
                // must not emit a peer-facing ProtocolError or close an
                // otherwise healthy stream.
                return []
            }
        }
    }

    /// UI-approved request for the full content of a previously received
    /// clipboard offer. Returns an empty action list when the change ID is
    /// unknown or clipboard was not negotiated.
    func requestClipboardContent(changeID: Data) -> [ProtocolV1SessionAction] {
        withSessionLock {
            guard let core = clipboardCore else { return [] }
            guard remoteManagedClipboardAllowed else { return [] }
            guard isStreaming else { return [] }
            do {
                let request = try core.requestContent(for: changeID)
                return sendActions(payload: .clipboardRequest(request), correlationID: 0)
            } catch {
                // Unknown/stale local approval is a no-op. Only malformed
                // messages received from the peer fail the session.
                return []
            }
        }
    }

    /// Release an exact request that the UI timed out waiting for. The offer
    /// remains available for a user-initiated retry. A false result means the
    /// request was already consumed, replaced, or never existed.
    func expireClipboardRequest(changeID: Data) -> Bool {
        withSessionLock {
            guard isStreaming, remoteManagedClipboardAllowed, let core = clipboardCore else { return false }
            return core.expireRequest(for: changeID)
        }
    }

    private func handleManagedPolicyStatus(
        _ status: VSManagedPolicyStatus,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        guard baseNegotiatedCapabilities.contains(.managedConfiguration) else {
            return unsupportedCapability("Managed policy was not negotiated.", correlationID)
        }
        managedPolicyResolver.setRemote(ManagedPolicy(remoteStatus: status))
        let effectivePolicy = managedPolicyResolver.effectivePolicy
        guard effectivePolicy.allows(hostID: configuration.hostID) else {
            return fail(
                code: .unauthorized,
                message: "Managed policy does not allow this host.",
                correlationID: correlationID
            )
        }
        remoteManagedClipboardAllowed = effectivePolicy.clipboardAllowed
        if !remoteManagedClipboardAllowed {
            clipboardCore?.reset()
        }
        negotiatedCapabilities = policyFilteredCapabilities(baseNegotiatedCapabilities, policy: effectivePolicy)
        if !effectivePolicy.hostActionsAllowed {
            pendingHostActionInvocations.removeAll()
        }
        return []
    }

    private func handleIncomingClipboardOffer(
        _ offer: VSClipboardOffer,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        guard let core = clipboardCore else {
            return unsupportedCapability("Clipboard was not negotiated.", correlationID)
        }
        guard remoteManagedClipboardAllowed else {
            return unsupportedCapability("Clipboard is disabled by managed policy.", correlationID)
        }
        guard isStreaming else {
            return invalidState("ClipboardOffer arrived before media was streaming.", correlationID)
        }
        do {
            let metadata = try core.handleOffer(offer)
            return [.clipboardOffer(metadata)]
        } catch let error as ClipboardCoreError {
            return clipboardFail(error, correlationID: correlationID)
        } catch {
            return serializationFailure()
        }
    }

    private func handleIncomingClipboardRequest(
        _ request: VSClipboardRequest,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        guard let core = clipboardCore else {
            return unsupportedCapability("Clipboard was not negotiated.", correlationID)
        }
        guard remoteManagedClipboardAllowed else {
            return unsupportedCapability("Clipboard is disabled by managed policy.", correlationID)
        }
        guard isStreaming else {
            return invalidState("ClipboardRequest arrived before media was streaming.", correlationID)
        }
        // A malformed change ID (wrong length) is a protocol violation and
        // fails the session. A well-formed but unknown or already-consumed
        // change ID is a legal no-op: the peer may retransmit a request for
        // content we no longer have, and we simply ignore it.
        guard request.changeID.count == ClipboardCore.changeIDByteCount else {
            return invalidState("ClipboardRequest.change_id has an invalid length.", correlationID)
        }
        guard let content = core.makeContent(for: request.changeID) else {
            return []
        }
        return sendActions(payload: .clipboardContent(content), correlationID: correlationID)
    }

    private func handleIncomingClipboardContent(
        _ content: VSClipboardContent,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        guard let core = clipboardCore else {
            return unsupportedCapability("Clipboard was not negotiated.", correlationID)
        }
        guard remoteManagedClipboardAllowed else {
            return unsupportedCapability("Clipboard is disabled by managed policy.", correlationID)
        }
        guard isStreaming else {
            return invalidState("ClipboardContent arrived before media was streaming.", correlationID)
        }
        do {
            let result = try core.handleContent(content)
            if result.isDirect {
                return [.clipboardDirectContent(result.validated)]
            }
            return [.clipboardContent(result.validated)]
        } catch let error as ClipboardCoreError {
            return clipboardFail(error, correlationID: correlationID)
        } catch {
            return serializationFailure()
        }
    }

    /// Map a ClipboardCoreError to the appropriate Protocol v1 error code and
    /// fail the session. Resource-exhaustion errors (too many pending
    /// offers/requests) map to resourceExhausted; everything else maps to
    /// invalidState or unsupportedCapability.
    private func clipboardFail(
        _ error: ClipboardCoreError,
        correlationID: UInt64
    ) -> [ProtocolV1SessionAction] {
        switch error {
        case .capabilityNotNegotiated:
            return unsupportedCapability("Clipboard was not negotiated.", correlationID)
        case .tooManyPendingOffers, .tooManyPendingRequests:
            return fail(
                code: .resourceExhausted,
                message: "Clipboard pending state exceeded the bounded limit.",
                correlationID: correlationID
            )
        default:
            return invalidState("Clipboard validation failed: \(error)", correlationID)
        }
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
        resetControllerState()
        pendingHostActionInvocations.removeAll()
        clipboardCore?.reset()
        remoteManagedClipboardAllowed = true
        managedPolicyResolver.clearRemote()
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
        resetControllerState()
        clipboardCore?.reset()
        remoteManagedClipboardAllowed = true
        managedPolicyResolver.clearRemote()
        return [.close]
    }

    private var isNegotiated: Bool {
        switch phase {
        case .awaitingDisplayStart, .awaitingVideoConfig, .streaming:
            return true
        default:
            return false
        }
    }

    private func resetControllerState() {
        controllerSequenceState.reset()
        pendingControllerConnections.removeAll()
    }

    private func withSessionLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
