import Foundation
import VibeScreenProtocol

struct FreshSessionRecoveryBudget {
    private(set) var attempt = 0
    let maximumAttempts: Int

    init(policy: NetworkRecoveryPolicy = .standard) {
        maximumAttempts = policy.maximumAttempts
    }

    mutating func reset() {
        attempt = 0
    }

    mutating func nextAttempt() -> Int? {
        guard attempt < maximumAttempts else { return nil }
        attempt += 1
        return attempt
    }
}

final class InternetProductSession: EncodedFrameSink {
    typealias EngineFactory = () -> WebRTCEnginePort
    typealias SecuritySessionFactory = (
        InternetProductSessionConfiguration
    ) throws -> InternetProductSecuritySession
    typealias RevocationHandler = (
        InternetProductSessionConfiguration,
        UInt64
    ) throws -> PairedDeviceRevocationTombstone?

    private struct PendingFrameSubmission {
        let data: Data
        let timestamp: UInt64
        let isKeyframe: Bool
        let sessionEpoch: UInt64
        let generation: UInt64
    }

    private struct FrameAdmissionState {
        var generation: UInt64 = 0
        var sessionEpoch: UInt64 = 0
        var maximumFrameBytes = 0
        var accepting = false
        var drainScheduled = false
        var overloadFailureScheduled = false
        var pending: PendingFrameSubmission?
    }

    private struct ControlAdmissionState {
        var generation: UInt64 = 0
        var maximumEntries = 0
        var maximumBytes = 0
        var maximumMessageBytes = 0
        var accepting = false
        var entries = 0
        var bytes = 0
        var overloadFailureScheduled = false
    }

    var onStateChanged: ((InternetProductSessionState) -> Void)?
    var onError: ((InternetProductSessionError) -> Void)?
    var onTouchEvent: ((Float, Float, Int, Int, Float, Float) -> Void)?
    var onAuthenticatedTouchEvent: ((UInt64, UInt64, Float, Float, Int, Int, Float, Float) -> Bool)?
    var onAuthenticatedStylusEvent: ((
        UInt64, UInt64, UInt32, Float, Float, VSInputPhase, Double, Double, Double,
        VSStylusToolKind, UInt32, VSStylusContactState
    ) -> Bool)?
    var onAuthenticatedControllerEvent: ((UInt64, GameControllerInputEvent) -> Bool)?
    var onKeyframeRequired: (() -> Void)?
    var onFreshSessionRecoveryRequired: ((Int) -> Void)?
    var onRevoked: (() -> Void)?
    /// Composition must deliver this signed tombstone to the session authority
    /// and peer. Local persistence remains fail-closed even if propagation is delayed.
    var onRevocationPropagationRequired: ((PairedDeviceRevocationTombstone) -> Void)?

    private let queue = DispatchQueue(label: "dev.vibescreen.internet-product-session")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private let frameAdmissionLock = NSLock()
    private let controlAdmissionLock = NSLock()
    private let engineFactory: EngineFactory
    private let securitySessionFactory: SecuritySessionFactory
    private let revocationHandler: RevocationHandler
    private var freshSessionRecoveryBudget: FreshSessionRecoveryBudget
    private var state: InternetProductSessionState = .idle
    private var configuration: InternetProductSessionConfiguration?
    private var transport: WebRTCInternetTransport?
    private var codec: InternetProductProtocolCodec?
    private var activePath: InternetPathKind?
    private var sessionGeneration: UInt64 = 0
    private var heartbeatTimer: DispatchSourceTimer?
    private var negotiationTimer: DispatchSourceTimer?
    private var nextHeartbeatSequence: UInt64 = 1
    private var lastPeerActivityNanoseconds: UInt64 = 0
    private var peerSupportsTouch = false
    private var peerSupportsStylus = false
    private var peerSupportsStylusExtended = false
    private var peerSupportsController = false
    private var stylusSequenceState = StylusSequenceState()
    private var controllerSequenceState = GameControllerStateMachine()
    private var frameAdmission = FrameAdmissionState()
    private var controlAdmission = ControlAdmissionState()

    var currentSessionEpoch: UInt64 {
        performSync { codec?.sessionEpoch ?? 0 }
    }

    init(
        engineFactory: @escaping EngineFactory = { ProductionWebRTCEngine() },
        securitySessionFactory: SecuritySessionFactory? = nil,
        revocationHandler: RevocationHandler? = nil,
        freshSessionRecoveryPolicy: NetworkRecoveryPolicy = .standard
    ) {
        self.engineFactory = engineFactory
        self.securitySessionFactory = securitySessionFactory ?? Self.makeStoredSecuritySession
        self.revocationHandler = revocationHandler ?? Self.persistPeerRevocation
        self.freshSessionRecoveryBudget = FreshSessionRecoveryBudget(
            policy: freshSessionRecoveryPolicy
        )
        queue.setSpecific(key: queueKey, value: 1)
    }

    func start(configuration: InternetProductSessionConfiguration) throws {
        try performSync {
            guard state == .idle || isRecoverableState else {
                throw InternetProductSessionError.invalidConfiguration(
                    "Internet product session is already active."
                )
            }
            try configuration.validate()
            freshSessionRecoveryBudget.reset()
            try startFreshSession(configuration)
        }
    }

    func provideFreshSession(configuration: InternetProductSessionConfiguration) throws {
        try performSync {
            guard case .recovering = state else {
                throw InternetProductSessionError.invalidConfiguration(
                    "Fresh Internet credentials were supplied while recovery was not active."
                )
            }
            try configuration.validate()
            try startFreshSession(configuration)
        }
    }

    func close() {
        performSync {
            _ = advanceSessionGeneration()
            resetQueuedWork(generation: sessionGeneration, limits: nil)
            stopHeartbeat()
            stopNegotiationDeadline()
            let retiredTransport = transport
            transport = nil
            codec = nil
            activePath = nil
            peerSupportsTouch = false
            peerSupportsStylus = false
            peerSupportsStylusExtended = false
            peerSupportsController = false
            _ = stylusSequenceState.consumeReset()
            controllerSequenceState.reset()
            configuration = nil
            let changed = state != .closed
            state = .closed
            retiredTransport?.close()
            if changed { onStateChanged?(.closed) }
        }
    }

    func revoke(sequence: UInt64) throws {
        try performSync {
            guard let configuration else {
                throw InternetProductSessionError.invalidConfiguration(
                    "No paired Internet device is active."
                )
            }
            _ = advanceSessionGeneration()
            resetQueuedWork(generation: sessionGeneration, limits: nil)
            stopHeartbeat()
            stopNegotiationDeadline()
            let retiredTransport = transport
            transport = nil
            codec = nil
            activePath = nil
            peerSupportsTouch = false
            peerSupportsStylus = false
            peerSupportsStylusExtended = false
            peerSupportsController = false
            _ = stylusSequenceState.consumeReset()
            controllerSequenceState.reset()
            let changed = state != .revoked
            state = .revoked
            let revocationGeneration = sessionGeneration
            retiredTransport?.close()
            let tombstone: PairedDeviceRevocationTombstone?
            do {
                tombstone = try revocationHandler(configuration, sequence)
            } catch {
                if changed,
                   sessionGeneration == revocationGeneration,
                   state == .revoked {
                    onStateChanged?(.revoked)
                }
                onRevoked?()
                throw InternetProductSessionError.securityFailure(error.localizedDescription)
            }
            if changed,
               sessionGeneration == revocationGeneration,
               state == .revoked {
                onStateChanged?(.revoked)
            }
            if let tombstone { onRevocationPropagationRequired?(tombstone) }
            onRevoked?()
        }
    }

    func sendFrame(
        _ data: Data,
        timestamp: UInt64,
        isKeyframe: Bool,
        sessionEpoch: UInt64
    ) {
        let submittedBytes = data.count
        let scheduling = withFrameAdmissionLock { state -> (UInt64, Bool, Bool) in
            guard state.accepting else { return (state.generation, false, false) }
            guard state.sessionEpoch == sessionEpoch else {
                return (state.generation, false, false)
            }
            guard !data.isEmpty, data.count <= state.maximumFrameBytes else {
                let shouldFail = !state.overloadFailureScheduled
                state.overloadFailureScheduled = true
                return (state.generation, false, shouldFail)
            }
            state.pending = PendingFrameSubmission(
                data: data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch,
                generation: state.generation
            )
            guard !state.drainScheduled else { return (state.generation, false, false) }
            state.drainScheduled = true
            return (state.generation, true, false)
        }
        if scheduling.2 {
            queue.async { [weak self] in
                guard let self, self.sessionGeneration == scheduling.0 else { return }
                self.fail(.transportFailure(.payloadTooLarge(
                    channel: .media,
                    actual: submittedBytes,
                    maximum: self.configuration?.limits.maximumMediaFrameBytes ?? 0
                )))
            }
        } else if scheduling.1 {
            queue.async { [weak self] in self?.drainLatestFrame(generation: scheduling.0) }
        }
    }

    func snapshotState() -> InternetProductSessionState {
        performSync { state }
    }

    func updateRotation(_ rotationDegrees: Int) throws {
        try performSync {
            guard isStreaming, var codec else {
                throw InternetProductSessionError.invalidConfiguration(
                    "Internet rotation requires an active product session."
                )
            }
            let controls = try codec.updateRotation(rotationDegrees)
            self.codec = codec
            for control in controls { try sendControl(control) }
            setState(.awaitingVideoConfiguration)
        }
    }

    private func startFreshSession(_ configuration: InternetProductSessionConfiguration) throws {
        stopHeartbeat()
        stopNegotiationDeadline()
        guard advanceSessionGeneration() else {
            throw InternetProductSessionError.securityFailure(
                "Internet product session generation was exhausted."
            )
        }
        let generation = sessionGeneration
        resetQueuedWork(
            generation: generation,
            sessionEpoch: configuration.authoritativeSessionEpoch,
            limits: configuration.limits
        )
        let securitySession: InternetProductSecuritySession
        do {
            securitySession = try securitySessionFactory(configuration)
        } catch PlatformSecurityError.revoked {
            setState(.revoked)
            throw InternetProductSessionError.revoked
        } catch {
            throw InternetProductSessionError.securityFailure(error.localizedDescription)
        }
        guard securitySession.sessionEpoch == configuration.authoritativeSessionEpoch else {
            let mismatch = "Platform security did not reserve the authority-agreed session epoch."
            do {
                try securitySession.close()
            } catch {
                throw InternetProductSessionError.securityFailure(
                    "\(mismatch) Temporary cipher cleanup also failed: \(error.localizedDescription)"
                )
            }
            throw InternetProductSessionError.securityFailure(mismatch)
        }
        let codec = try InternetProductProtocolCodec(
            sessionIdentifier: configuration.transport.sessionIdentifier,
            sessionEpoch: securitySession.sessionEpoch,
            hostID: configuration.hostDeviceID,
            hostName: configuration.hostName,
            peerDeviceID: configuration.peerDeviceID,
            video: configuration.video,
            inputEnabled: configuration.inputEnabled,
            controllerAvailable: configuration.controllerAvailable,
            limits: configuration.limits
        )
        let transport = WebRTCInternetTransport(
            engine: engineFactory(),
            packetCipher: securitySession.packetCipher,
            limits: configuration.limits,
            recoveryStrategy: .freshSession
        )
        installCallbacks(on: transport, generation: generation)
        self.configuration = configuration
        self.codec = codec
        self.transport = transport
        activePath = nil
        peerSupportsTouch = false
        peerSupportsStylus = false
        peerSupportsStylusExtended = false
        peerSupportsController = false
        _ = stylusSequenceState.consumeReset()
        controllerSequenceState.reset()
        nextHeartbeatSequence = 1
        lastPeerActivityNanoseconds = DispatchTime.now().uptimeNanoseconds
        let connectingState = InternetProductSessionState.connecting
        let stateChanged = state != connectingState
        state = connectingState
        do {
            try transport.start(configuration: configuration.transport)
        } catch let error as InternetTransportError {
            fail(.transportFailure(error))
            throw InternetProductSessionError.transportFailure(error)
        } catch {
            let wrapped = InternetProductSessionError.securityFailure(error.localizedDescription)
            fail(wrapped)
            throw wrapped
        }
        guard generation == sessionGeneration,
              self.transport === transport,
              state == connectingState else { return }
        if stateChanged { onStateChanged?(connectingState) }
    }

    private func installCallbacks(
        on transport: WebRTCInternetTransport,
        generation: UInt64
    ) {
        transport.onStateChanged = { [weak self] state in
            self?.queue.async { self?.handleTransportState(state, generation: generation) }
        }
        transport.onError = { [weak self] error in
            self?.queue.async {
                guard let self, self.sessionGeneration == generation else { return }
                self.fail(.transportFailure(error))
            }
        }
        transport.onControlReceived = { [weak self] data in
            self?.enqueueInboundControl(data, generation: generation)
        }
        transport.onMediaReceived = { [weak self] _ in
            self?.scheduleInboundFailure(
                .protocolFailure(.unexpectedMessage(
                    "the host received an unsupported inbound media message"
                )),
                generation: generation
            )
        }
        transport.onKeyframeRequired = { [weak self] in
            self?.queue.async {
                guard let self, self.sessionGeneration == generation else { return }
                self.onKeyframeRequired?()
            }
        }
        transport.onFreshSessionRecoveryRequired = { [weak self] attempt in
            self?.queue.async { self?.beginFreshSessionRecovery(attempt: attempt, generation: generation) }
        }
    }

    private func handleTransportState(
        _ transportState: InternetTransportState,
        generation: UInt64
    ) {
        guard generation == sessionGeneration else { return }
        switch transportState {
        case .idle: break
        case .connecting: setState(.connecting)
        case .connected(let path):
            guard path != .unknown else {
                fail(.securityFailure(
                    "The selected ICE candidate path is still unknown; the session remains fail-closed."
                ))
                return
            }
            activePath = path
            if isStreaming {
                setState(.streaming(path))
                onKeyframeRequired?()
            } else if state == .connecting {
                setState(.authenticating)
            }
        case .recovering:
            // Fresh-session recovery is driven solely by
            // onFreshSessionRecoveryRequired, which publishes the session's
            // .recovering state through beginFreshSessionRecovery. Reacting to
            // the transport's own .recovering here would publish the state
            // twice and race the synchronous fresh-session install performed
            // inside the recovering-state callback.
            break
        case .failed(let reason): fail(.securityFailure(reason))
        case .closed:
            if state != .revoked { setState(.closed) }
        }
    }

    private func handleControl(_ data: Data, generation: UInt64) {
        guard generation == sessionGeneration, var codec else { return }
        do {
            let allowHello = state == .authenticating
            let envelope = try codec.decodeControl(data, allowUnscopedHello: allowHello)
            lastPeerActivityNanoseconds = DispatchTime.now().uptimeNanoseconds
            switch envelope.payload {
            case .clientHello(let hello) where state == .authenticating:
                try codec.validate(hello)
                peerSupportsTouch = codec.inputEnabled && hello.capabilities.contains(.touch)
                peerSupportsStylus = codec.inputEnabled && hello.capabilities.contains(.stylus)
                peerSupportsStylusExtended = peerSupportsStylus
                    && hello.capabilities.contains(.stylusExtended)
                peerSupportsController = codec.controllerAvailable
                    && hello.capabilities.contains(.controller)
                try sendControl(codec.hostHello())
                try sendControl(codec.sessionAccepted(
                    heartbeatIntervalMilliseconds: configuration?.heartbeatIntervalMilliseconds ?? 1_000,
                    peerSupportsTouch: peerSupportsTouch,
                    peerSupportsStylus: peerSupportsStylus,
                    peerSupportsStylusExtended: peerSupportsStylusExtended,
                    peerSupportsController: peerSupportsController
                ))
                try sendControl(codec.videoConfiguration())
                self.codec = codec
                setState(.awaitingVideoConfiguration)

            case .videoConfigResult(let result) where state == .awaitingVideoConfiguration:
                guard result.configEpoch == codec.video.configEpoch,
                      result.streamID == codec.video.streamID else {
                    throw InternetProductProtocolError.unexpectedMessage(
                        "waiting for the active video configuration acknowledgment"
                    )
                }
                guard result.accepted else {
                    throw InternetProductProtocolError.rejectedVideoConfiguration(
                        result.rejectionReason
                    )
                }
                self.codec = codec
                guard let path = activePath, path != .unknown else {
                    throw InternetProductProtocolError.unexpectedMessage(
                        "waiting for the authoritative selected ICE candidate path"
                    )
                }
                setState(.streaming(path))
                stopNegotiationDeadline()
                startHeartbeat()
                onKeyframeRequired?()

            case .ping(let ping):
                try sendControl(codec.pong(
                    sequence: ping.sequence,
                    correlationID: envelope.messageID
                ))
                self.codec = codec

            case .pong:
                self.codec = codec

            case .requestKeyframe where isStreaming:
                self.codec = codec
                onKeyframeRequired?()

            case .touchEvent(let touch) where isStreaming:
                self.codec = codec
                try routeTouch(touch, sessionEpoch: codec.sessionEpoch)

            case .stylusEvent(let stylus) where isStreaming:
                self.codec = codec
                try routeStylus(
                    stylus,
                    sessionEpoch: codec.sessionEpoch,
                    streamID: codec.video.streamID
                )

            case .controllerEvent(let controller) where isStreaming:
                self.codec = codec
                try routeController(
                    controller,
                    sessionEpoch: codec.sessionEpoch,
                    streamID: codec.video.streamID
                )

            case .disconnectNotice:
                self.codec = codec
                beginFreshSessionRecovery(attempt: 1, generation: generation)

            default:
                let payloadName: String
                switch envelope.payload {
                case .clientHello: payloadName = "ClientHello"
                case .videoConfigResult: payloadName = "VideoConfigResult"
                case .ping: payloadName = "Ping"
                case .pong: payloadName = "Pong"
                case .requestKeyframe: payloadName = "RequestKeyframe"
                case .touchEvent: payloadName = "TouchEvent"
                case .stylusEvent: payloadName = "StylusEvent"
                case .controllerEvent: payloadName = "ControllerEvent"
                case .disconnectNotice: payloadName = "DisconnectNotice"
                case nil: payloadName = "empty payload"
                default: payloadName = "unsupported payload"
                }
                throw InternetProductProtocolError.unexpectedMessage(
                    "\(payloadName) arrived while the product session is in state \(state)"
                )
            }
        } catch let error as InternetProductProtocolError {
            fail(.protocolFailure(error))
        } catch let error as InternetProductSessionError {
            fail(error)
        } catch {
            fail(.securityFailure(error.localizedDescription))
        }
    }

    private func routeTouch(_ touch: VSTouchEvent, sessionEpoch: UInt64) throws {
        guard peerSupportsTouch else {
            throw InternetProductProtocolError.missingCapability(.touch)
        }
        let x = touch.position.x
        let y = touch.position.y
        guard touch.inputID > 0,
              x.isFinite, y.isFinite,
              (0...1).contains(x), (0...1).contains(y) else {
            throw InternetProductProtocolError.invalidTouch
        }
        let action: Int
        switch touch.phase {
        case .began: action = 0
        case .changed: action = 1
        case .ended, .cancelled: action = 2
        default: throw InternetProductProtocolError.invalidTouch
        }
        let routed = onAuthenticatedTouchEvent?(
            sessionEpoch,
            touch.inputID,
            Float(x), Float(y), action, 1, 0, 0
        )
        if routed == nil {
            onTouchEvent?(Float(x), Float(y), action, 1, 0, 0)
        }
    }

    private func routeStylus(
        _ stylus: VSStylusEvent,
        sessionEpoch: UInt64,
        streamID: UInt64
    ) throws {
        guard peerSupportsStylus else {
            throw InternetProductProtocolError.missingCapability(.stylus)
        }
        let x = stylus.position.x
        let y = stylus.position.y
        let pressure = stylus.pressure
        let tiltX = stylus.tiltXDegrees
        let tiltY = stylus.tiltYDegrees
        let toolKind: VSStylusToolKind = stylus.hasToolKind ? stylus.toolKind : .pen
        let contactState: VSStylusContactState = stylus.hasContactState
            ? stylus.contactState
            : .contact
        let terminalPhase = stylus.phase == .ended || stylus.phase == .cancelled
        let targetMatches = !stylus.hasTarget
            || ((stylus.target.streamID == 0 || stylus.target.streamID == streamID)
                && (stylus.target.displayID.isEmpty
                    || stylus.target.displayID == "internet-display"))
        guard stylus.inputID > 0,
              stylus.hasPosition,
              x.isFinite, y.isFinite,
              (0...1).contains(x), (0...1).contains(y),
              pressure.isFinite, (0...1).contains(pressure),
              (!terminalPhase && contactState == .contact) || pressure == 0,
              tiltX.isFinite, tiltY.isFinite,
              (-90...90).contains(tiltX), (-90...90).contains(tiltY),
              hypot(tiltX, tiltY) <= 90,
              targetMatches,
              stylus.phase != .unspecified,
              validatesStylusExtension(
                  stylus,
                  toolKind: toolKind,
                  contactState: contactState
              ),
              stylusSequenceState.accepts(
                  pointerID: stylus.pointerID,
                  phase: stylus.phase,
                  toolKind: toolKind,
                  contactState: contactState
              ) else {
            throw InternetProductProtocolError.invalidStylus
        }
        _ = onAuthenticatedStylusEvent?(
            sessionEpoch,
            stylus.inputID,
            stylus.pointerID,
            Float(x),
            Float(y),
            stylus.phase,
            pressure,
            tiltX,
            tiltY,
            toolKind,
            stylus.buttonMask,
            contactState
        )
    }

    private func validatesStylusExtension(
        _ stylus: VSStylusEvent,
        toolKind: VSStylusToolKind,
        contactState: VSStylusContactState
    ) -> Bool {
        if !peerSupportsStylusExtended {
            return !stylus.hasToolKind && !stylus.hasContactState && stylus.buttonMask == 0
        }
        guard stylus.hasToolKind, stylus.hasContactState,
              toolKind == .pen || toolKind == .eraser,
              contactState == .contact || contactState == .proximity,
              stylus.buttonMask & ~UInt32(0b11) == 0 else { return false }
        return contactState != .proximity || stylus.pressure == 0
    }

    private func routeController(
        _ controller: VSControllerEvent,
        sessionEpoch: UInt64,
        streamID: UInt64
    ) throws {
        guard peerSupportsController else {
            throw InternetProductProtocolError.missingCapability(.controller)
        }
        let targetMatches = !controller.hasTarget
            || ((controller.target.streamID == 0 || controller.target.streamID == streamID)
                && (controller.target.displayID.isEmpty
                    || controller.target.displayID == "internet-display"))
        guard targetMatches else {
            throw InternetProductProtocolError.invalidController
        }
        let kind: GameControllerEventKind
        switch controller.kind {
        case .connected: kind = .connected
        case .state: kind = .state
        case .disconnected: kind = .disconnected
        default: throw InternetProductProtocolError.invalidController
        }
        let state = GameControllerState(
            buttonMask: controller.buttonMask,
            leftX: controller.leftStickX,
            leftY: controller.leftStickY,
            rightX: controller.rightStickX,
            rightY: controller.rightStickY,
            leftTrigger: controller.leftTrigger,
            rightTrigger: controller.rightTrigger,
            hatX: controller.hatX,
            hatY: controller.hatY
        )
        guard state.isValid else {
            throw InternetProductProtocolError.invalidController
        }
        let event = GameControllerInputEvent(
            inputID: controller.inputID,
            controllerID: controller.controllerID,
            controllerEpoch: controller.controllerEpoch,
            kind: kind,
            state: state
        )
        do {
            try controllerSequenceState.accept(event)
        } catch {
            throw InternetProductProtocolError.invalidController
        }
        guard onAuthenticatedControllerEvent?(sessionEpoch, event) == true else {
            throw InternetProductProtocolError.invalidController
        }
    }

    private func sendControl(_ payload: Data) throws {
        guard let transport else {
            throw InternetProductSessionError.invalidConfiguration(
                "Internet transport is unavailable."
            )
        }
        if case .failure(let error) = transport.sendControl(payload) {
            throw InternetProductSessionError.transportFailure(error)
        }
    }

    private func startHeartbeat() {
        stopHeartbeat()
        guard let configuration else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        let interval = DispatchTimeInterval.milliseconds(
            Int(configuration.heartbeatIntervalMilliseconds)
        )
        timer.schedule(deadline: .now() + interval, repeating: interval)
        timer.setEventHandler { [weak self] in self?.heartbeatTick() }
        heartbeatTimer = timer
        timer.resume()
    }

    private func heartbeatTick() {
        guard isStreaming, let configuration, var codec else { return }
        let now = DispatchTime.now().uptimeNanoseconds
        let timeoutNanoseconds = UInt64(configuration.heartbeatTimeoutMilliseconds) * 1_000_000
        guard now - lastPeerActivityNanoseconds <= timeoutNanoseconds else {
            beginFreshSessionRecovery(attempt: 1, generation: sessionGeneration)
            return
        }
        do {
            guard nextHeartbeatSequence < UInt64.max else {
                fail(.securityFailure("Internet heartbeat sequence was exhausted."))
                return
            }
            try sendControl(codec.ping(sequence: nextHeartbeatSequence))
            nextHeartbeatSequence += 1
            self.codec = codec
        } catch let error as InternetProductSessionError {
            fail(error)
        } catch {
            fail(.securityFailure(error.localizedDescription))
        }
    }

    private func beginFreshSessionRecovery(attempt: Int, generation: UInt64) {
        guard generation == sessionGeneration else { return }
        guard attempt > 0,
              let sessionAttempt = freshSessionRecoveryBudget.nextAttempt() else {
            fail(.securityFailure(
                "Fresh-session recovery exhausted after \(freshSessionRecoveryBudget.attempt) attempts."
            ))
            return
        }
        stopHeartbeat()
        stopNegotiationDeadline()
        guard advanceSessionGeneration() else {
            fail(.securityFailure("Internet product session generation was exhausted."))
            return
        }
        let recoveryGeneration = sessionGeneration
        resetQueuedWork(generation: recoveryGeneration, limits: nil)
        let retiredTransport = transport
        transport = nil
        codec = nil
        activePath = nil
        peerSupportsTouch = false
        peerSupportsStylus = false
        peerSupportsStylusExtended = false
        peerSupportsController = false
        _ = stylusSequenceState.consumeReset()
        controllerSequenceState.reset()
        let recoveringState = InternetProductSessionState.recovering(attempt: sessionAttempt)
        let stateChanged = state != recoveringState
        state = recoveringState
        retiredTransport?.close()
        if stateChanged { onStateChanged?(recoveringState) }
        guard sessionGeneration == recoveryGeneration,
              state == recoveringState else { return }
        onFreshSessionRecoveryRequired?(sessionAttempt)
    }

    private func resetQueuedWork(
        generation: UInt64,
        sessionEpoch: UInt64 = 0,
        limits: InternetTransportLimits?
    ) {
        withFrameAdmissionLock { state in
            state = FrameAdmissionState(
                generation: generation,
                sessionEpoch: sessionEpoch,
                maximumFrameBytes: limits?.maximumMediaFrameBytes ?? 0,
                accepting: limits != nil
            )
        }
        withControlAdmissionLock { state in
            state = ControlAdmissionState(
                generation: generation,
                maximumEntries: limits?.maximumBufferedControlMessages ?? 0,
                maximumBytes: limits?.maximumBufferedControlBytes ?? 0,
                maximumMessageBytes: limits?.maximumControlMessageBytes ?? 0,
                accepting: limits != nil
            )
        }
    }

    private func drainLatestFrame(generation: UInt64) {
        let submission = withFrameAdmissionLock { state -> PendingFrameSubmission? in
            guard state.generation == generation else { return nil }
            let pending = state.pending
            state.pending = nil
            return pending
        }
        guard let submission else { return finishFrameDrain(generation: generation) }
        guard submission.generation == sessionGeneration,
              case .streaming = state,
              let transport,
              var codec,
              submission.sessionEpoch == codec.sessionEpoch else {
            return finishFrameDrain(generation: generation)
        }
        do {
            let frame = try codec.mediaFrame(
                payload: submission.data,
                timestamp: submission.timestamp,
                isKeyframe: submission.isKeyframe
            )
            self.codec = codec
            if case .failure(let error) = transport.sendMedia(frame) {
                fail(.transportFailure(error))
            }
        } catch let error as InternetProductProtocolError {
            fail(.protocolFailure(error))
        } catch {
            fail(.securityFailure(error.localizedDescription))
        }
        finishFrameDrain(generation: generation)
    }

    private func finishFrameDrain(generation: UInt64) {
        let shouldContinue = withFrameAdmissionLock { state -> Bool in
            guard state.generation == generation else { return false }
            guard state.pending != nil else {
                state.drainScheduled = false
                return false
            }
            return true
        }
        if shouldContinue {
            queue.async { [weak self] in self?.drainLatestFrame(generation: generation) }
        }
    }

    private func enqueueInboundControl(_ data: Data, generation: UInt64) {
        let admission = withControlAdmissionLock {
            state -> (admitted: Bool, shouldFail: Bool, maximumBytes: Int) in
            guard state.accepting, state.generation == generation else {
                return (false, false, state.maximumBytes)
            }
            let exceedsLimit = data.isEmpty
                || data.count > state.maximumMessageBytes
                || data.count > state.maximumBytes
                || state.entries >= state.maximumEntries
                || state.bytes > state.maximumBytes - data.count
            guard !exceedsLimit else {
                let shouldFail = !state.overloadFailureScheduled
                state.overloadFailureScheduled = true
                return (false, shouldFail, state.maximumBytes)
            }
            state.entries += 1
            state.bytes += data.count
            return (true, false, state.maximumBytes)
        }
        if admission.admitted {
            queue.async { [weak self] in
                guard let self else { return }
                defer { self.releaseInboundControl(bytes: data.count, generation: generation) }
                self.handleControl(data, generation: generation)
            }
        } else if admission.shouldFail {
            scheduleInboundFailure(
                .transportFailure(.controlBacklogExceeded(
                    maximumBytes: admission.maximumBytes
                )),
                generation: generation,
                alreadyReserved: true
            )
        }
    }

    private func releaseInboundControl(bytes: Int, generation: UInt64) {
        withControlAdmissionLock { state in
            guard state.generation == generation else { return }
            state.entries = max(0, state.entries - 1)
            state.bytes = max(0, state.bytes - bytes)
        }
    }

    private func scheduleInboundFailure(
        _ error: InternetProductSessionError,
        generation: UInt64,
        alreadyReserved: Bool = false
    ) {
        let shouldSchedule = alreadyReserved || withControlAdmissionLock { state -> Bool in
            guard state.accepting, state.generation == generation,
                  !state.overloadFailureScheduled else { return false }
            state.overloadFailureScheduled = true
            return true
        }
        guard shouldSchedule else { return }
        queue.async { [weak self] in
            guard let self, self.sessionGeneration == generation else { return }
            self.fail(error)
        }
    }

    private func stopHeartbeat() {
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
    }

    private func scheduleNegotiationDeadline() {
        stopNegotiationDeadline()
        guard let configuration else { return }
        let generation = sessionGeneration
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .milliseconds(
            Int(configuration.negotiationTimeoutMilliseconds)
        ))
        timer.setEventHandler { [weak self] in
            guard let self, self.sessionGeneration == generation else { return }
            switch self.state {
            case .authenticating, .awaitingVideoConfiguration:
                self.fail(.protocolFailure(.unexpectedMessage(
                    "the peer did not finish Protocol v1 negotiation before the deadline"
                )))
            default: break
            }
        }
        negotiationTimer = timer
        timer.resume()
    }

    private func stopNegotiationDeadline() {
        negotiationTimer?.cancel()
        negotiationTimer = nil
    }

    private func fail(_ error: InternetProductSessionError) {
        guard state != .revoked, state != .closed else { return }
        if case .failed = state { return }
        stopHeartbeat()
        stopNegotiationDeadline()
        _ = advanceSessionGeneration()
        resetQueuedWork(generation: sessionGeneration, limits: nil)
        let failedTransport = transport
        transport = nil
        codec = nil
        activePath = nil
        peerSupportsTouch = false
        peerSupportsStylus = false
        peerSupportsStylusExtended = false
        peerSupportsController = false
        _ = stylusSequenceState.consumeReset()
        controllerSequenceState.reset()
        // Close the retired transport before publishing the terminal state so
        // any observer waking on .failed already sees the transport closed,
        // instead of racing the queue that would otherwise close it afterward.
        failedTransport?.close()
        setState(.failed(error.localizedDescription))
        onError?(error)
    }

    private func setState(_ newState: InternetProductSessionState) {
        guard state != newState else { return }
        state = newState
        if newState == .authenticating || newState == .awaitingVideoConfiguration {
            scheduleNegotiationDeadline()
        }
        onStateChanged?(newState)
    }

    private var isStreaming: Bool {
        if case .streaming = state { return true }
        return false
    }

    private var isRecoverableState: Bool {
        switch state {
        case .failed, .closed: return true
        default: return false
        }
    }

    @discardableResult
    private func advanceSessionGeneration() -> Bool {
        guard sessionGeneration < UInt64.max else { return false }
        sessionGeneration += 1
        return true
    }

    @discardableResult
    private func withFrameAdmissionLock<T>(
        _ operation: (inout FrameAdmissionState) -> T
    ) -> T {
        frameAdmissionLock.lock()
        defer { frameAdmissionLock.unlock() }
        return operation(&frameAdmission)
    }

    @discardableResult
    private func withControlAdmissionLock<T>(
        _ operation: (inout ControlAdmissionState) -> T
    ) -> T {
        controlAdmissionLock.lock()
        defer { controlAdmissionLock.unlock() }
        return operation(&controlAdmission)
    }

    @discardableResult
    private func performSync<T>(_ operation: () throws -> T) rethrows -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return try operation() }
        return try queue.sync(execute: operation)
    }

}
