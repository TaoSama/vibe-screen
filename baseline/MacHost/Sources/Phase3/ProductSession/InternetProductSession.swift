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
    private static let terminalProtocolErrorDrainTimeoutMilliseconds = 500
    private static let rawBulkAdmissionTransferID = Data("internet-bulk-v1".utf8)
    private static let freshSessionRecoveryTimeoutMilliseconds: UInt32 = 120_000

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

    private struct PendingRuntimeVideoConfiguration {
        let committed: InternetProductVideoConfiguration
        let proposed: InternetProductVideoConfiguration
        let adaptiveToken: InternetAdaptiveRequestToken?
        let adaptiveProfile: AdaptiveMediaProfile?
        var awaitingHostRollback = false
    }

    var onStateChanged: ((InternetProductSessionState) -> Void)?
    var onError: ((InternetProductSessionError) -> Void)?
    var onTouchEvent: ((Float, Float, Int, Int, Float, Float) -> Void)?
    var onAuthenticatedTouchEvent: ((UInt64, UInt64, Float, Float, Int, Int, Float, Float) -> Bool)?
    var onAuthenticatedStylusEvent: ((
        UInt64, UInt64, UInt32, Float, Float, VSInputPhase, Double, Double, Double,
        VSStylusToolKind, UInt32, VSStylusContactState
    ) -> Bool)?
    var onAuthenticatedControllerEvent: ((
        _ sessionEpoch: UInt64,
        _ sessionGeneration: UInt64,
        _ event: GameControllerInputEvent
    ) -> Bool)?
    var onKeyframeRequired: (() -> Void)?
    var onFreshSessionRecoveryRequired: ((Int) -> Void)?
    var onAdaptiveProfileRequested: ((
        InternetAdaptiveRequestToken,
        AdaptiveMediaProfile,
        InternetProductVideoConfiguration,
        InternetProductVideoConfiguration
    ) -> Void)?
    var onAdaptiveProfileRollbackRequested: ((
        InternetAdaptiveRequestToken,
        InternetProductVideoConfiguration,
        InternetProductVideoConfiguration
    ) -> Void)?
    var onAdaptiveProfileCommitted: ((
        InternetAdaptiveRequestToken,
        InternetProductVideoConfiguration
    ) -> Void)?
    var onAudioRecordReceived: ((Data) -> Void)?
    var onBulkRecordReceived: ((Data) -> Void)?
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
    private var terminalProtocolFailureGeneration: UInt64?
    private var nextHeartbeatSequence: UInt64 = 1
    private var lastPeerActivityNanoseconds: UInt64 = 0
    private var peerSupportsTouch = false
    private var peerSupportsStylus = false
    private var peerSupportsStylusExtended = false
    private var peerSupportsController = false
    private var stylusSequenceState = StylusSequenceState()
    private var adaptiveRequestSequence = InternetAdaptiveRequestSequence()
    private var pendingAdaptiveRequest: InternetAdaptiveRequestToken?
    private var pendingAdaptiveProfile: AdaptiveMediaProfile?
    private var queuedAdaptiveProfile: AdaptiveMediaProfile?
    private var committedVideoConfiguration: InternetProductVideoConfiguration?
    private var pendingRuntimeVideoConfiguration: PendingRuntimeVideoConfiguration?
    private var deferredRotationDegrees: Int?
    private var frameAdmission = FrameAdmissionState()
    private var controlAdmission = ControlAdmissionState()
    private var advancedChannelGate: AdvancedChannelSecurityGate?
    private var advancedChannelGateInitializationError: AdvancedChannelSecurityError?

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
            freshSessionRecoveryBudget.reset()
        }
    }

    func close() {
        performSync {
            _ = advanceSessionGeneration()
            terminalProtocolFailureGeneration = nil
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
            resetAdaptiveVideoState()
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
            terminalProtocolFailureGeneration = nil
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
            resetAdaptiveVideoState()
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

    @discardableResult
    func sendAudioRecord(_ payload: Data) -> Bool {
        let streamID = performSync { codec?.video.streamID ?? 0 }
        return sendAdvancedRecord(
            payload,
            binding: .audio(displayID: "internet-display", streamID: streamID)
        )
    }

    @discardableResult
    func sendBulkRecord(_ payload: Data, transferID: Data) -> Bool {
        sendAdvancedRecord(payload, binding: .bulk(transferID: transferID))
    }

    func snapshotState() -> InternetProductSessionState {
        performSync { state }
    }

    func updateRotation(_ rotationDegrees: Int) throws {
        try performSync {
            guard [0, 90, 180, 270].contains(rotationDegrees) else {
                throw InternetProductSessionError.invalidConfiguration(
                    "Internet rotation must be 0, 90, 180, or 270 degrees."
                )
            }
            if pendingAdaptiveRequest != nil
                || pendingRuntimeVideoConfiguration != nil
                || state == .awaitingVideoConfiguration {
                deferredRotationDegrees = rotationDegrees
                return
            }
            guard isStreaming, var codec,
                  let committed = committedVideoConfiguration else {
                throw InternetProductSessionError.invalidConfiguration(
                    "Internet rotation requires an active product session."
                )
            }
            let controls = try codec.updateRotation(rotationDegrees)
            let proposed = codec.video
            do {
                for control in controls { try sendControl(control) }
            } catch {
                codec.restoreVideoConfiguration(committed)
                self.codec = codec
                let sessionError = (error as? InternetProductSessionError)
                    ?? .securityFailure(error.localizedDescription)
                fail(sessionError)
                throw sessionError
            }
            self.codec = codec
            pendingRuntimeVideoConfiguration = PendingRuntimeVideoConfiguration(
                committed: committed,
                proposed: proposed,
                adaptiveToken: nil,
                adaptiveProfile: nil
            )
            setState(.awaitingVideoConfiguration)
        }
    }

    @discardableResult
    func completeAdaptiveProfile(
        token: InternetAdaptiveRequestToken,
        appliedVideo: InternetProductVideoConfiguration
    ) throws -> Bool {
        try performSync {
            guard pendingAdaptiveRequest == token,
                  let adaptiveProfile = pendingAdaptiveProfile,
                  token.generation == sessionGeneration,
                  pendingRuntimeVideoConfiguration == nil,
                  isStreaming,
                  let committed = committedVideoConfiguration,
                  let baseline = configuration?.video,
                  var codec else { return false }
            guard appliedVideo.codec == committed.codec,
                  appliedVideo.streamID == committed.streamID,
                  appliedVideo.width >= 2, appliedVideo.width <= baseline.width,
                  appliedVideo.height >= 2, appliedVideo.height <= baseline.height,
                  appliedVideo.width.isMultiple(of: 2),
                  appliedVideo.height.isMultiple(of: 2),
                  appliedVideo.framesPerSecond > 0,
                  appliedVideo.framesPerSecond <= baseline.framesPerSecond,
                  appliedVideo.bitrateKbps >= 1_000,
                  appliedVideo.bitrateKbps <= baseline.bitrateKbps else {
                // Keep ownership until the caller restores the committed host
                // configuration, then let rejectAdaptiveProfile resume queued
                // work from the acknowledged state.
                throw InternetProductSessionError.invalidConfiguration(
                    "Adaptive video exceeded the user baseline or encoder limits."
                )
            }

            let controls: [Data]
            let proposed: InternetProductVideoConfiguration
            do {
                controls = try codec.updateVideoConfiguration(
                    width: appliedVideo.width,
                    height: appliedVideo.height,
                    framesPerSecond: appliedVideo.framesPerSecond,
                    bitrateKbps: appliedVideo.bitrateKbps,
                    rotationDegrees: committed.rotationDegrees
                )
                proposed = codec.video
                for control in controls { try sendControl(control) }
            } catch {
                codec.restoreVideoConfiguration(committed)
                self.codec = codec
                pendingAdaptiveRequest = nil
                pendingAdaptiveProfile = nil
                transport?.rejectAdaptiveProfile(adaptiveProfile)
                stopNegotiationDeadline()
                let sessionError = (error as? InternetProductSessionError)
                    ?? .securityFailure(error.localizedDescription)
                fail(sessionError)
                throw sessionError
            }
            self.codec = codec
            pendingAdaptiveRequest = nil
            pendingAdaptiveProfile = nil
            pendingRuntimeVideoConfiguration = PendingRuntimeVideoConfiguration(
                committed: committed,
                proposed: proposed,
                adaptiveToken: token,
                adaptiveProfile: adaptiveProfile
            )
            setState(.awaitingVideoConfiguration)
            return true
        }
    }

    @discardableResult
    func rejectAdaptiveProfile(token: InternetAdaptiveRequestToken) -> Bool {
        performSync {
            guard pendingAdaptiveRequest == token,
                  let adaptiveProfile = pendingAdaptiveProfile,
                  token.generation == sessionGeneration,
                  pendingRuntimeVideoConfiguration == nil,
                  isStreaming else { return false }
            pendingAdaptiveRequest = nil
            pendingAdaptiveProfile = nil
            transport?.rejectAdaptiveProfile(adaptiveProfile)
            stopNegotiationDeadline()
            resumeQueuedAdaptiveWork(generation: sessionGeneration)
            return true
        }
    }

    @discardableResult
    func completeAdaptiveRollback(
        token: InternetAdaptiveRequestToken,
        succeeded: Bool
    ) -> Bool {
        performSync {
            guard let pending = pendingRuntimeVideoConfiguration,
                  pending.adaptiveToken == token,
                  pending.awaitingHostRollback,
                  token.generation == sessionGeneration else { return false }
            guard succeeded else {
                if let profile = pending.adaptiveProfile {
                    transport?.rejectAdaptiveProfile(profile)
                }
                pendingRuntimeVideoConfiguration = nil
                fail(.invalidConfiguration(
                    "The host could not restore the last acknowledged adaptive video configuration."
                ))
                return true
            }
            if let profile = pending.adaptiveProfile {
                transport?.rejectAdaptiveProfile(profile)
            }
            pendingRuntimeVideoConfiguration = nil
            finishRuntimeVideoTransaction(generation: sessionGeneration)
            return true
        }
    }

    @discardableResult
    func failAdaptiveProfile(token: InternetAdaptiveRequestToken, reason: String) -> Bool {
        performSync {
            let ownsPendingApply = pendingAdaptiveRequest == token
            let ownsPendingRollback = pendingRuntimeVideoConfiguration?.adaptiveToken == token
            guard token.generation == sessionGeneration,
                  ownsPendingApply || ownsPendingRollback else { return false }
            let profile = pendingAdaptiveProfile
                ?? pendingRuntimeVideoConfiguration?.adaptiveProfile
            pendingAdaptiveRequest = nil
            pendingAdaptiveProfile = nil
            pendingRuntimeVideoConfiguration = nil
            if let profile {
                transport?.rejectAdaptiveProfile(profile)
            }
            fail(.invalidConfiguration(reason))
            return true
        }
    }

    private func startFreshSession(_ configuration: InternetProductSessionConfiguration) throws {
        stopHeartbeat()
        stopNegotiationDeadline()
        terminalProtocolFailureGeneration = nil
        guard advanceSessionGeneration() else {
            throw InternetProductSessionError.securityFailure(
                "Internet product session generation was exhausted."
            )
        }
        let generation = sessionGeneration
        resetQueuedWork(
            generation: generation,
            sessionEpoch: configuration.authoritativeSessionEpoch,
            sessionIdentifier: configuration.transport.sessionIdentifier,
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
            limits: configuration.limits
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
        resetAdaptiveVideoState()
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
        transport.onAudioRecordReceived = { [weak self] data in
            self?.queue.async { self?.handleAudioRecord(data, generation: generation) }
        }
        transport.onBulkRecordReceived = { [weak self] data in
            self?.queue.async { self?.handleBulkRecord(data, generation: generation) }
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
        transport.onAdaptiveProfileChanged = { [weak self, weak transport] profile in
            self?.queue.async {
                guard let self, let transport,
                      self.sessionGeneration == generation,
                      self.transport === transport else { return }
                if self.pendingAdaptiveRequest != nil
                    || self.pendingRuntimeVideoConfiguration != nil
                    || self.state == .awaitingVideoConfiguration {
                    self.queuedAdaptiveProfile = profile
                    return
                }
                guard self.isStreaming else {
                    switch self.state {
                    case .connecting, .authenticating:
                        self.queuedAdaptiveProfile = profile
                    default:
                        break
                    }
                    return
                }
                self.beginAdaptiveProfileRequest(profile, generation: generation)
            }
        }
    }

    private func handleTransportState(
        _ transportState: InternetTransportState,
        generation: UInt64
    ) {
        guard generation == sessionGeneration else { return }
        if terminalProtocolFailureGeneration == generation {
            if case .failed(let reason) = transportState {
                fail(.securityFailure(reason))
            }
            return
        }
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
        guard generation == sessionGeneration,
              terminalProtocolFailureGeneration == nil,
              var codec else { return }
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
                if let pending = pendingRuntimeVideoConfiguration,
                   pending.awaitingHostRollback {
                    self.codec = codec
                    return
                }
                if pendingRuntimeVideoConfiguration != nil,
                   (result.configEpoch != codec.video.configEpoch
                    || result.streamID != codec.video.streamID) {
                    self.codec = codec
                    return
                }
                guard result.configEpoch == codec.video.configEpoch,
                      result.streamID == codec.video.streamID else {
                    throw InternetProductProtocolError.unexpectedMessage(
                        "waiting for the active video configuration acknowledgment"
                    )
                }
                if !result.accepted, let pending = pendingRuntimeVideoConfiguration {
                    guard let token = pending.adaptiveToken else {
                        throw InternetProductProtocolError.rejectedVideoConfiguration(
                            result.rejectionReason
                        )
                    }
                    self.codec = codec
                    beginAdaptiveRollback(token: token)
                    return
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
                let completedRuntimeTransaction = pendingRuntimeVideoConfiguration
                committedVideoConfiguration = codec.video
                pendingRuntimeVideoConfiguration = nil
                if let token = completedRuntimeTransaction?.adaptiveToken {
                    if let profile = completedRuntimeTransaction?.adaptiveProfile {
                        transport?.commitAdaptiveProfile(profile)
                    }
                    onAdaptiveProfileCommitted?(token, codec.video)
                }
                if completedRuntimeTransaction != nil
                    || deferredRotationDegrees != nil
                    || queuedAdaptiveProfile != nil {
                    resumeQueuedAdaptiveWork(generation: generation)
                }

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

            case .controllerEvent(let controller) where isStreaming
                || (state == .awaitingVideoConfiguration && controller.kind == .disconnected):
                try routeController(
                    controller,
                    sessionEpoch: codec.sessionEpoch,
                    requestMessageID: envelope.messageID,
                    generation: generation,
                    codec: &codec
                )

            case .disconnectNotice(let notice):
                self.codec = codec
                if notice.mayResume {
                    beginFreshSessionRecovery(attempt: 1, generation: generation)
                } else {
                    close()
                }

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
        requestMessageID: UInt64,
        generation: UInt64,
        codec: inout InternetProductProtocolCodec
    ) throws {
        guard peerSupportsController else {
            throw InternetProductProtocolError.missingCapability(.controller)
        }
        let targetMatches = !controller.hasTarget
            || ((controller.target.streamID == 0
                    || controller.target.streamID == codec.video.streamID)
                && (controller.target.displayID.isEmpty
                    || controller.target.displayID == "internet-display"))
        guard targetMatches else {
            throw InternetProductProtocolError.invalidController
        }

        switch try codec.authorizeController(controller) {
        case .accepted(let event):
            // Commit admission before entering composition code. A callback may
            // synchronously close the session; handleControl must never restore
            // this retired codec after that reentrant close.
            self.codec = codec
            guard generation == sessionGeneration else { return }
            let nativeAccepted = onAuthenticatedControllerEvent?(
                sessionEpoch,
                generation,
                event
            ) == true
            guard generation == sessionGeneration, var activeCodec = self.codec else { return }
            guard nativeAccepted else {
                let failure = InternetProductSessionError.protocolFailure(.invalidController)
                let errorPayload = try activeCodec.protocolError(
                    code: .invalidState,
                    message: "Controller injection failed: native controller handler was unavailable or rejected the event.",
                    correlationID: requestMessageID
                )
                self.codec = activeCodec
                beginTerminalProtocolFailure(
                    errorPayload,
                    failure: failure,
                    generation: generation
                )
                return
            }
            if event.kind == .connected {
                let acknowledgement = try activeCodec.inputAck(
                    inputID: event.inputID,
                    accepted: true,
                    correlationID: requestMessageID
                )
                self.codec = activeCodec
                try sendControl(acknowledgement)
            }

        case .rejected(let inputID, let reason):
            let acknowledgement = try codec.inputAck(
                inputID: inputID,
                accepted: false,
                rejectionReason: reason,
                correlationID: requestMessageID
            )
            self.codec = codec
            try sendControl(acknowledgement)
        }
    }

    private func beginAdaptiveProfileRequest(
        _ profile: AdaptiveMediaProfile,
        generation: UInt64
    ) {
        guard generation == sessionGeneration,
              pendingAdaptiveRequest == nil,
              pendingRuntimeVideoConfiguration == nil,
              isStreaming,
              let committed = committedVideoConfiguration,
              let baseline = configuration?.video,
              let requestID = adaptiveRequestSequence.take(),
              let plan = InternetAdaptiveVideoPlan(baseline: baseline, profile: profile) else {
            return
        }
        let proposed = InternetProductVideoConfiguration(
            codec: committed.codec,
            width: plan.width,
            height: plan.height,
            framesPerSecond: plan.framesPerSecond,
            bitrateKbps: plan.bitrateKbps,
            streamID: committed.streamID,
            configEpoch: committed.configEpoch,
            rotationDegrees: committed.rotationDegrees
        )
        if proposed.width == committed.width,
           proposed.height == committed.height,
           proposed.framesPerSecond == committed.framesPerSecond,
           proposed.bitrateKbps == committed.bitrateKbps,
           proposed.rotationDegrees == committed.rotationDegrees {
            transport?.commitAdaptiveProfile(profile)
            return
        }
        let token = InternetAdaptiveRequestToken(
            generation: generation,
            requestID: requestID
        )
        pendingAdaptiveRequest = token
        pendingAdaptiveProfile = profile
        guard let onAdaptiveProfileRequested else {
            pendingAdaptiveRequest = nil
            pendingAdaptiveProfile = nil
            transport?.rejectAdaptiveProfile(profile)
            return
        }
        scheduleNegotiationDeadline()
        onAdaptiveProfileRequested(token, profile, committed, baseline)
    }

    private func resumeQueuedAdaptiveWork(generation: UInt64) {
        guard generation == sessionGeneration else { return }
        if let rotationDegrees = deferredRotationDegrees {
            deferredRotationDegrees = nil
            do {
                try updateRotation(rotationDegrees)
            } catch let error as InternetProductSessionError {
                fail(error)
            } catch let error as InternetProductProtocolError {
                fail(.protocolFailure(error))
            } catch {
                fail(.securityFailure(error.localizedDescription))
            }
            return
        }
        if let queuedAdaptiveProfile {
            self.queuedAdaptiveProfile = nil
            beginAdaptiveProfileRequest(queuedAdaptiveProfile, generation: generation)
        }
    }

    private func finishRuntimeVideoTransaction(generation: UInt64) {
        guard generation == sessionGeneration,
              let path = activePath, path != .unknown else {
            fail(.securityFailure(
                "The selected ICE candidate path became unavailable during adaptive rollback."
            ))
            return
        }
        stopNegotiationDeadline()
        setState(.streaming(path))
        startHeartbeat()
        onKeyframeRequired?()
        resumeQueuedAdaptiveWork(generation: generation)
    }

    private func beginAdaptiveRollback(token: InternetAdaptiveRequestToken) {
        guard var pending = pendingRuntimeVideoConfiguration,
              pending.adaptiveToken == token,
              !pending.awaitingHostRollback,
              var codec else { return }
        codec.restoreVideoConfiguration(pending.committed)
        self.codec = codec
        pending.awaitingHostRollback = true
        pendingRuntimeVideoConfiguration = pending
        scheduleNegotiationDeadline()
        guard let onAdaptiveProfileRollbackRequested else {
            pendingRuntimeVideoConfiguration = nil
            fail(.invalidConfiguration(
                "The host has no adaptive video rollback handler."
            ))
            return
        }
        onAdaptiveProfileRollbackRequested(token, pending.committed, pending.proposed)
    }

    private func resetAdaptiveVideoState() {
        pendingAdaptiveRequest = nil
        pendingAdaptiveProfile = nil
        queuedAdaptiveProfile = nil
        committedVideoConfiguration = nil
        pendingRuntimeVideoConfiguration = nil
        deferredRotationDegrees = nil
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

    private func sendAdvancedRecord(_ payload: Data, binding: AdvancedChannelBinding) -> Bool {
        do {
            return try performSync {
                guard isStreaming, let transport else { return false }
                let admission = try reserveAdvancedRecord(payloadBytes: payload.count, binding: binding)
                let result: Result<Void, InternetTransportError>
                switch binding {
                case .audio:
                    result = transport.sendAudioRecord(payload)
                case .bulk:
                    result = transport.sendBulkRecord(payload)
                }
                switch result {
                case .success:
                    try finishAdvancedAdmission(admission)
                    return true
                case .failure(let error):
                    try finishAdvancedAdmission(admission)
                    fail(.transportFailure(error))
                    return false
                }
            }
        } catch let error as InternetProductSessionError {
            performSync { fail(error) }
            return false
        } catch let error as AdvancedChannelSecurityError {
            performSync { fail(advancedChannelFailure(error, binding: binding, actualBytes: payload.count)) }
            return false
        } catch {
            performSync { fail(.securityFailure(error.localizedDescription)) }
            return false
        }
    }

    private func handleAudioRecord(_ payload: Data, generation: UInt64) {
        guard sessionGeneration == generation, isStreaming else { return }
        handleAdvancedRecord(payload, binding: .audio(displayID: "internet-display", streamID: codec?.video.streamID ?? 0)) {
            onAudioRecordReceived?($0)
        }
    }

    private func handleBulkRecord(_ payload: Data, generation: UInt64) {
        guard sessionGeneration == generation, isStreaming else { return }
        handleAdvancedRecord(payload, binding: .bulk(transferID: Self.rawBulkAdmissionTransferID)) {
            onBulkRecordReceived?($0)
        }
    }

    private func handleAdvancedRecord(
        _ payload: Data,
        binding: AdvancedChannelBinding,
        deliver: (Data) -> Void
    ) {
        do {
            let admission = try reserveAdvancedRecord(payloadBytes: payload.count, binding: binding)
            defer { try? finishAdvancedAdmission(admission) }
            deliver(payload)
        } catch let error as AdvancedChannelSecurityError {
            fail(advancedChannelFailure(error, binding: binding, actualBytes: payload.count))
        } catch {
            fail(.securityFailure(error.localizedDescription))
        }
    }

    private func reserveAdvancedRecord(
        payloadBytes: Int,
        binding: AdvancedChannelBinding
    ) throws -> AdvancedChannelAdmission {
        guard let configuration else {
            throw AdvancedChannelSecurityError.staleOwner
        }
        guard let gate = advancedChannelGate else {
            throw advancedChannelGateInitializationError ?? AdvancedChannelSecurityError.staleOwner
        }
        return try gate.reserve(
            payloadBytes: payloadBytes,
            binding: binding,
            owner: advancedChannelOwner(
                generation: sessionGeneration,
                sessionEpoch: currentSessionEpoch,
                sessionIdentifier: configuration.transport.sessionIdentifier
            )
        )
    }

    private func finishAdvancedAdmission(_ admission: AdvancedChannelAdmission) throws {
        try advancedChannelGate?.finish(admission)
    }

    private func advancedChannelOwner(
        generation: UInt64,
        sessionEpoch: UInt64,
        sessionIdentifier: String
    ) -> AdvancedChannelOwner {
        AdvancedChannelOwner(
            sessionIdentifier: sessionIdentifier,
            sessionEpoch: sessionEpoch,
            generation: generation
        )
    }

    private func advancedChannelFailure(
        _ error: AdvancedChannelSecurityError,
        binding: AdvancedChannelBinding,
        actualBytes: Int
    ) -> InternetProductSessionError {
        let transportChannel: InternetTransportChannel = {
            switch binding {
            case .audio: return .audio
            case .bulk: return .bulk
            }
        }()
        switch error {
        case .emptyPayload:
            return .transportFailure(.emptyPayload(channel: transportChannel))
        case .payloadTooLarge(let maximum):
            return .transportFailure(.payloadTooLarge(
                channel: transportChannel,
                actual: actualBytes,
                maximum: maximum
            ))
        case .backlogExceeded(let maximum):
            switch binding {
            case .audio:
                return .securityFailure("Advanced Internet audio channel backlog exceeded \(maximum) bytes.")
            case .bulk:
                return .transportFailure(.bulkBacklogExceeded(maximumBytes: maximum))
            }
        case .invalidOwner, .invalidLimits, .invalidBinding,
             .staleOwner, .unknownAdmission, .sequenceExhausted:
            return .securityFailure("Advanced Internet channel admission failed: \(error)")
        }
    }

    private func beginTerminalProtocolFailure(
        _ payload: Data,
        failure: InternetProductSessionError,
        generation: UInt64
    ) {
        guard generation == sessionGeneration, let terminalTransport = transport else {
            fail(failure)
            return
        }
        stopHeartbeat()
        stopNegotiationDeadline()
        terminalProtocolFailureGeneration = generation
        resetQueuedWork(generation: generation, limits: nil)

        let sendResult = terminalTransport.sendControl(payload) {
            [weak self, weak terminalTransport] result in
            guard let self, let terminalTransport else { return }
            self.queue.async {
                self.finishTerminalProtocolFailure(
                    result.mapError(InternetProductSessionError.transportFailure),
                    fallbackFailure: failure,
                    generation: generation,
                    transport: terminalTransport
                )
            }
        }
        if case .failure(let error) = sendResult {
            terminalProtocolFailureGeneration = nil
            fail(.transportFailure(error))
            return
        }
        queue.asyncAfter(
            deadline: .now() + .milliseconds(
                Self.terminalProtocolErrorDrainTimeoutMilliseconds
            )
        ) { [weak self, weak terminalTransport] in
            guard let self, let terminalTransport else { return }
            self.finishTerminalProtocolFailure(
                .success(()),
                fallbackFailure: failure,
                generation: generation,
                transport: terminalTransport
            )
        }
    }

    private func finishTerminalProtocolFailure(
        _ sendResult: Result<Void, InternetProductSessionError>,
        fallbackFailure: InternetProductSessionError,
        generation: UInt64,
        transport terminalTransport: WebRTCInternetTransport
    ) {
        guard terminalProtocolFailureGeneration == generation,
              sessionGeneration == generation,
              transport === terminalTransport else { return }
        terminalProtocolFailureGeneration = nil
        switch sendResult {
        case .success:
            fail(fallbackFailure)
        case .failure(let error):
            fail(error)
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
        guard generation == sessionGeneration,
              terminalProtocolFailureGeneration == nil else { return }
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
        resetAdaptiveVideoState()
        configuration = nil
        let recoveringState = InternetProductSessionState.recovering(attempt: sessionAttempt)
        let stateChanged = state != recoveringState
        state = recoveringState
        retiredTransport?.close()
        if stateChanged { onStateChanged?(recoveringState) }
        guard sessionGeneration == recoveryGeneration,
              state == recoveringState else { return }
        scheduleFreshSessionRecoveryDeadline(generation: recoveryGeneration)
        onFreshSessionRecoveryRequired?(sessionAttempt)
    }

    private func resetQueuedWork(
        generation: UInt64,
        sessionEpoch: UInt64 = 0,
        sessionIdentifier: String? = nil,
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
        if let limits, sessionEpoch > 0, let sessionIdentifier {
            let maximumBulkRecordBytes = max(
                1,
                min(
                    InternetBulkRecordContract.maximumPlaintextRecordBytes,
                    limits.maximumBufferedBulkBytes
                )
            )
            do {
                advancedChannelGate = try AdvancedChannelSecurityGate(
                    owner: advancedChannelOwner(
                        generation: generation,
                        sessionEpoch: sessionEpoch,
                        sessionIdentifier: sessionIdentifier
                    ),
                    limits: .init(
                        maximumAudioRecordBytes: InternetAudioRecordContract.maximumPlaintextRecordBytes,
                        maximumAudioBacklogBytes: InternetAudioRecordContract.maximumPlaintextRecordBytes,
                        maximumBulkRecordBytes: maximumBulkRecordBytes,
                        maximumBulkBacklogBytes: limits.maximumBufferedBulkBytes
                    )
                )
                advancedChannelGateInitializationError = nil
            } catch let error as AdvancedChannelSecurityError {
                advancedChannelGate = nil
                advancedChannelGateInitializationError = error
            } catch {
                advancedChannelGate = nil
                advancedChannelGateInitializationError = .invalidLimits
            }
        } else {
            advancedChannelGate = nil
            advancedChannelGateInitializationError = nil
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
              pendingAdaptiveRequest == nil,
              pendingRuntimeVideoConfiguration == nil,
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
            case .awaitingVideoConfiguration:
                let detail = self.pendingRuntimeVideoConfiguration?.awaitingHostRollback == true
                    ? "the host did not finish adaptive video rollback before the deadline"
                    : "the peer did not acknowledge the active video configuration before the deadline"
                self.fail(.protocolFailure(.unexpectedMessage(
                    detail
                )))
            case .streaming where self.pendingAdaptiveRequest != nil:
                self.fail(.invalidConfiguration(
                    "The host did not apply the requested adaptive video profile before the deadline."
                ))
            case .authenticating:
                self.fail(.protocolFailure(.unexpectedMessage(
                    "the peer did not finish Protocol v1 negotiation before the deadline"
                )))
            default: break
            }
        }
        negotiationTimer = timer
        timer.resume()
    }

    private func scheduleFreshSessionRecoveryDeadline(generation: UInt64) {
        stopNegotiationDeadline()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .milliseconds(
            Int(Self.freshSessionRecoveryTimeoutMilliseconds)
        ))
        timer.setEventHandler { [weak self] in
            guard let self, self.sessionGeneration == generation else { return }
            guard case .recovering = self.state else { return }
            self.fail(.securityFailure(
                "fresh-session recovery timed out before replacement credentials were supplied"
            ))
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
        terminalProtocolFailureGeneration = nil
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
        resetAdaptiveVideoState()
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
        if terminalProtocolFailureGeneration == nil,
           case .streaming = state { return true }
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
