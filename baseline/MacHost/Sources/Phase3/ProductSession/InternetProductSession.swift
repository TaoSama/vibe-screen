import Foundation
import VibeScreenProtocol

final class InternetProductSession: EncodedFrameSink {
    typealias EngineFactory = () -> WebRTCEnginePort
    typealias SecuritySessionFactory = (
        InternetProductSessionConfiguration
    ) throws -> InternetProductSecuritySession
    typealias RevocationHandler = (
        InternetProductSessionConfiguration,
        UInt64
    ) throws -> PairedDeviceRevocationTombstone?

    var onStateChanged: ((InternetProductSessionState) -> Void)?
    var onError: ((InternetProductSessionError) -> Void)?
    var onTouchEvent: ((Float, Float, Int, Int, Float, Float) -> Void)?
    var onAuthenticatedTouchEvent: ((UInt64, UInt64, Float, Float, Int, Int, Float, Float) -> Bool)?
    var onKeyframeRequired: (() -> Void)?
    var onFreshSessionRecoveryRequired: ((Int) -> Void)?
    var onRevoked: (() -> Void)?
    /// Composition must deliver this signed tombstone to the session authority
    /// and peer. Local persistence remains fail-closed even if propagation is delayed.
    var onRevocationPropagationRequired: ((PairedDeviceRevocationTombstone) -> Void)?

    private let queue = DispatchQueue(label: "dev.vibescreen.internet-product-session")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private let engineFactory: EngineFactory
    private let securitySessionFactory: SecuritySessionFactory
    private let revocationHandler: RevocationHandler
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

    var currentSessionEpoch: UInt64 {
        performSync { codec?.sessionEpoch ?? 0 }
    }

    init(
        engineFactory: @escaping EngineFactory = { ProductionWebRTCEngine() },
        securitySessionFactory: SecuritySessionFactory? = nil,
        revocationHandler: RevocationHandler? = nil
    ) {
        self.engineFactory = engineFactory
        self.securitySessionFactory = securitySessionFactory ?? Self.makeStoredSecuritySession
        self.revocationHandler = revocationHandler ?? Self.persistPeerRevocation
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
            sessionGeneration &+= 1
            stopHeartbeat()
            stopNegotiationDeadline()
            transport?.close()
            transport = nil
            codec = nil
            activePath = nil
            configuration = nil
            setState(.closed)
        }
    }

    func revoke(sequence: UInt64) throws {
        try performSync {
            guard let configuration else {
                throw InternetProductSessionError.invalidConfiguration(
                    "No paired Internet device is active."
                )
            }
            do {
                if let tombstone = try revocationHandler(configuration, sequence) {
                    onRevocationPropagationRequired?(tombstone)
                }
            } catch {
                throw InternetProductSessionError.securityFailure(error.localizedDescription)
            }
            sessionGeneration &+= 1
            stopHeartbeat()
            stopNegotiationDeadline()
            transport?.close()
            transport = nil
            codec = nil
            activePath = nil
            setState(.revoked)
            onRevoked?()
        }
    }

    func sendFrame(
        _ data: Data,
        timestamp: UInt64,
        isKeyframe: Bool,
        sessionEpoch: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  case .streaming = self.state,
                  let transport = self.transport,
                  var codec = self.codec,
                  sessionEpoch == codec.sessionEpoch else { return }
            do {
                let frame = try codec.mediaFrame(
                    payload: data,
                    timestamp: timestamp,
                    isKeyframe: isKeyframe
                )
                self.codec = codec
                if case .failure(let error) = transport.sendMedia(frame) {
                    self.fail(.transportFailure(error))
                }
            } catch let error as InternetProductProtocolError {
                self.fail(.protocolFailure(error))
            } catch {
                self.fail(.securityFailure(error.localizedDescription))
            }
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
        sessionGeneration &+= 1
        let generation = sessionGeneration
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
        nextHeartbeatSequence = 1
        lastPeerActivityNanoseconds = DispatchTime.now().uptimeNanoseconds
        setState(.connecting)
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
            self?.queue.async { self?.handleControl(data, generation: generation) }
        }
        transport.onMediaReceived = { [weak self] _ in
            self?.queue.async {
                guard let self, self.sessionGeneration == generation else { return }
                self.fail(.protocolFailure(.unexpectedMessage(
                    "the host received an unsupported inbound media message"
                )))
            }
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
        case .recovering(let attempt): setState(.recovering(attempt: attempt))
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
                peerSupportsTouch = hello.capabilities.contains(.touch)
                try sendControl(codec.hostHello())
                try sendControl(codec.sessionAccepted(
                    heartbeatIntervalMilliseconds: configuration?.heartbeatIntervalMilliseconds ?? 1_000,
                    peerSupportsTouch: peerSupportsTouch
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
                try routeTouch(touch, sessionEpoch: codec.sessionEpoch)
                self.codec = codec

            case .disconnectNotice:
                self.codec = codec
                beginFreshSessionRecovery(attempt: 1, generation: generation)

            default:
                throw InternetProductProtocolError.unexpectedMessage(
                    "the product session is in state \(state)"
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
            try sendControl(codec.ping(sequence: nextHeartbeatSequence))
            nextHeartbeatSequence &+= 1
            self.codec = codec
        } catch let error as InternetProductSessionError {
            fail(error)
        } catch {
            fail(.securityFailure(error.localizedDescription))
        }
    }

    private func beginFreshSessionRecovery(attempt: Int, generation: UInt64) {
        guard generation == sessionGeneration else { return }
        stopHeartbeat()
        stopNegotiationDeadline()
        setState(.recovering(attempt: attempt))
        sessionGeneration &+= 1
        transport?.close()
        transport = nil
        codec = nil
        activePath = nil
        peerSupportsTouch = false
        onFreshSessionRecoveryRequired?(attempt)
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
        sessionGeneration &+= 1
        let failedTransport = transport
        transport = nil
        codec = nil
        activePath = nil
        peerSupportsTouch = false
        setState(.failed(error.localizedDescription))
        onError?(error)
        failedTransport?.close()
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
    private func performSync<T>(_ operation: () throws -> T) rethrows -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return try operation() }
        return try queue.sync(execute: operation)
    }

}
