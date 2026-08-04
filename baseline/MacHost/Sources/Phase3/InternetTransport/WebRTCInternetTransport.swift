import Foundation

final class WebRTCInternetTransport {
    var onStateChanged: ((InternetTransportState) -> Void)?
    var onAdaptiveProfileChanged: ((AdaptiveMediaProfile) -> Void)?
    var onKeyframeRequired: (() -> Void)?
    var onError: ((InternetTransportError) -> Void)?
    var onControlReceived: ((Data) -> Void)?
    var onMediaReceived: ((Data) -> Void)?

    private struct MutableState {
        var transportState: InternetTransportState = .idle
        var activePath: InternetPathKind?
        var pipelineGeneration: UInt64 = 0
        var controlInFlight = false
        var controlQueue: [Data] = []
        var bufferedControlBytes = 0
        var mediaInFlight = false
        var pendingMediaFrame: EncodedInternetFrame?
        var waitingForKeyframe = true
        var controlBytesSent: UInt64 = 0
        var mediaBytesSent: UInt64 = 0
        var relayBytesSent: UInt64 = 0
        var relayBytesReserved: UInt64 = 0
        var droppedMediaFrames: UInt64 = 0
        var iceRestartCount: UInt64 = 0
        var recovery: NetworkRecoveryStateMachine
    }

    private let engine: WebRTCEnginePort
    private let hasApplicationCipher: Bool
    private let limits: InternetTransportLimits
    private let adaptivePolicy: AdaptiveMediaPolicy
    private let lock = NSLock()
    private var mutableState: MutableState

    init(
        engine: WebRTCEnginePort = ProductionWebRTCEngine(),
        packetCipher: PlatformSessionPacketCipher? = nil,
        limits: InternetTransportLimits = .standard,
        recoveryPolicy: NetworkRecoveryPolicy = .standard,
        adaptivePolicy: AdaptiveMediaPolicy = AdaptiveMediaPolicy()
    ) {
        if let packetCipher {
            self.engine = ProtectedWebRTCEngine(engine: engine, packetCipher: packetCipher)
            self.hasApplicationCipher = true
        } else {
            self.engine = engine
            self.hasApplicationCipher = false
        }
        self.limits = limits
        self.adaptivePolicy = adaptivePolicy
        self.mutableState = MutableState(recovery: NetworkRecoveryStateMachine(policy: recoveryPolicy))
        self.engine.install(callbacks: WebRTCEngineCallbacks(
            connectionStateChanged: { [weak self] state in self?.handleEngineState(state) },
            networkPathChanged: { [weak self] path in self?.handleNetworkPath(path) },
            networkQualitySampled: { [weak self] sample in self?.handleNetworkQuality(sample) },
            messageReceived: { [weak self] payload, channel in
                switch channel {
                case .control: self?.onControlReceived?(payload)
                case .media: self?.onMediaReceived?(payload)
                }
            }
        ))
    }

    func start(configuration: WebRTCTransportConfiguration) throws {
        try configuration.validate()
        guard hasApplicationCipher else {
            throw InternetTransportError.invalidConfiguration(
                "Protocol v1 application encryption and a platform-backed session cipher are required."
            )
        }
        setState(.connecting)
        do {
            try engine.start(
                configuration: configuration,
                channels: [
                    InternetTransportChannel.control.dataChannelConfiguration,
                    InternetTransportChannel.media.dataChannelConfiguration
                ]
            )
        } catch {
            let transportError = (error as? InternetTransportError)
                ?? .engineUnavailable(error.localizedDescription)
            setState(.failed(transportError.localizedDescription))
            throw transportError
        }
    }

    @discardableResult
    func sendControl(_ payload: Data) -> Result<Void, InternetTransportError> {
        guard !payload.isEmpty else {
            return .failure(.emptyPayload(channel: .control))
        }
        guard payload.count <= limits.maximumControlMessageBytes else {
            return .failure(.payloadTooLarge(
                channel: .control,
                actual: payload.count,
                maximum: limits.maximumControlMessageBytes
            ))
        }

        var shouldTransmit = false
        var transmissionGeneration: UInt64 = 0
        let admissionError: InternetTransportError? = withLock {
            guard isConnected($0.transportState) else { return .notConnected }
            guard $0.bufferedControlBytes + payload.count <= limits.maximumBufferedControlBytes else {
                return .controlBacklogExceeded(maximumBytes: limits.maximumBufferedControlBytes)
            }
            if $0.activePath == .relay {
                let payloadBytes = UInt64(payload.count)
                guard $0.relayBytesSent + $0.relayBytesReserved + payloadBytes
                        <= limits.maximumRelayBytesPerSession else {
                    return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                }
                $0.relayBytesReserved += payloadBytes
            }
            $0.bufferedControlBytes += payload.count
            transmissionGeneration = $0.pipelineGeneration
            if $0.controlInFlight {
                $0.controlQueue.append(payload)
            } else {
                $0.controlInFlight = true
                shouldTransmit = true
            }
            return nil
        }

        if let admissionError {
            if case .controlBacklogExceeded = admissionError {
                failTransport(admissionError)
            }
            return .failure(admissionError)
        }
        if shouldTransmit { transmitControl(payload, generation: transmissionGeneration) }
        return .success(())
    }

    @discardableResult
    func sendMedia(_ frame: EncodedInternetFrame) -> Result<Void, InternetTransportError> {
        guard !frame.payload.isEmpty else {
            return .failure(.emptyPayload(channel: .media))
        }
        guard frame.payload.count <= limits.maximumMediaFrameBytes else {
            return .failure(.payloadTooLarge(
                channel: .media,
                actual: frame.payload.count,
                maximum: limits.maximumMediaFrameBytes
            ))
        }

        var frameToTransmit: EncodedInternetFrame?
        var shouldRequestKeyframe = false
        var transmissionGeneration: UInt64 = 0
        let admissionError: InternetTransportError? = withLock { state in
            guard isConnected(state.transportState) else { return .notConnected }
            if state.activePath == .relay,
               state.relayBytesSent + state.relayBytesReserved + UInt64(frame.payload.count)
                    > limits.maximumRelayBytesPerSession {
                return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
            }
            if state.waitingForKeyframe {
                guard frame.isKeyframe else {
                    state.droppedMediaFrames += 1
                    return nil
                }
                state.waitingForKeyframe = false
            }
            if state.activePath == .relay {
                state.relayBytesReserved += UInt64(frame.payload.count)
            }
            transmissionGeneration = state.pipelineGeneration
            guard state.mediaInFlight else {
                state.mediaInFlight = true
                frameToTransmit = frame
                return nil
            }

            if let pending = state.pendingMediaFrame {
                if pending.isKeyframe && !frame.isKeyframe {
                    state.droppedMediaFrames += 1
                    releaseRelayReservation(for: frame.payload.count, state: &state)
                } else if frame.isKeyframe {
                    state.pendingMediaFrame = frame
                    state.droppedMediaFrames += 1
                    releaseRelayReservation(for: pending.payload.count, state: &state)
                } else {
                    state.pendingMediaFrame = nil
                    state.waitingForKeyframe = true
                    state.droppedMediaFrames += 2
                    releaseRelayReservation(
                        for: pending.payload.count + frame.payload.count,
                        state: &state
                    )
                    shouldRequestKeyframe = true
                }
            } else {
                state.pendingMediaFrame = frame
            }
            return nil
        }

        if let admissionError { return .failure(admissionError) }
        if shouldRequestKeyframe {
            engine.requestMediaKeyframe()
            onKeyframeRequired?()
        }
        if let frameToTransmit { transmitMedia(frameToTransmit, generation: transmissionGeneration) }
        return .success(())
    }

    func close() {
        withLock {
            $0.transportState = .closed
            $0.activePath = nil
            invalidatePipeline(state: &$0)
        }
        engine.close()
        onStateChanged?(.closed)
    }

    func snapshot() -> InternetTransportSnapshot {
        withLock {
            InternetTransportSnapshot(
                state: $0.transportState,
                activePath: $0.activePath,
                controlBytesSent: $0.controlBytesSent,
                mediaBytesSent: $0.mediaBytesSent,
                relayBytesSent: $0.relayBytesSent,
                relayBytesReserved: $0.relayBytesReserved,
                droppedMediaFrames: $0.droppedMediaFrames,
                iceRestartCount: $0.iceRestartCount,
                bufferedControlBytes: $0.bufferedControlBytes,
                hasPendingMediaFrame: $0.pendingMediaFrame != nil
            )
        }
    }

    private func transmitControl(_ payload: Data, generation: UInt64) {
        let wasRelay = withLock { $0.activePath == .relay }
        engine.send(payload, channel: .control) { [weak self] result in
            guard let self else { return }
            var next: Data?
            var reportedError: InternetTransportError?
            self.withLock {
                guard $0.pipelineGeneration == generation else { return }
                $0.bufferedControlBytes = max(0, $0.bufferedControlBytes - payload.count)
                if wasRelay {
                    $0.relayBytesReserved = $0.relayBytesReserved.subtractingClamped(UInt64(payload.count))
                }
                switch result {
                case .success:
                    $0.controlBytesSent += UInt64(payload.count)
                    if wasRelay { $0.relayBytesSent += UInt64(payload.count) }
                    if !$0.controlQueue.isEmpty {
                        next = $0.controlQueue.removeFirst()
                    } else {
                        $0.controlInFlight = false
                    }
                case .failure(let error):
                    reportedError = .engineSendFailed(error.localizedDescription)
                }
            }
            if let reportedError { self.failTransport(reportedError) }
            if let next { self.transmitControl(next, generation: generation) }
        }
    }

    private func transmitMedia(_ frame: EncodedInternetFrame, generation: UInt64) {
        let wasRelay = withLock { $0.activePath == .relay }
        engine.send(frame.payload, channel: .media) { [weak self] result in
            guard let self else { return }
            var next: EncodedInternetFrame?
            var reportedError: InternetTransportError?
            var shouldRequestKeyframe = false
            self.withLock {
                guard $0.pipelineGeneration == generation else { return }
                if wasRelay {
                    $0.relayBytesReserved = $0.relayBytesReserved.subtractingClamped(UInt64(frame.payload.count))
                }
                switch result {
                case .success:
                    $0.mediaBytesSent += UInt64(frame.payload.count)
                    if wasRelay { $0.relayBytesSent += UInt64(frame.payload.count) }
                    if let pending = $0.pendingMediaFrame {
                        next = pending
                        $0.pendingMediaFrame = nil
                    } else {
                        $0.mediaInFlight = false
                    }
                case .failure(let error):
                    $0.droppedMediaFrames += 1
                    $0.waitingForKeyframe = true
                    reportedError = .engineSendFailed(error.localizedDescription)
                    if let pending = $0.pendingMediaFrame, pending.isKeyframe {
                        next = pending
                        $0.pendingMediaFrame = nil
                        $0.waitingForKeyframe = false
                    } else {
                        if let pending = $0.pendingMediaFrame {
                            $0.droppedMediaFrames += 1
                            self.releaseRelayReservation(for: pending.payload.count, state: &$0)
                        }
                        $0.pendingMediaFrame = nil
                        $0.mediaInFlight = false
                        shouldRequestKeyframe = true
                    }
                }
            }
            if let reportedError {
                if shouldRequestKeyframe {
                    self.engine.requestMediaKeyframe()
                    self.onKeyframeRequired?()
                }
                self.onError?(reportedError)
            }
            if let next { self.transmitMedia(next, generation: generation) }
        }
    }

    private func handleEngineState(_ state: WebRTCEngineConnectionState) {
        let isClosed = withLock { $0.transportState == .closed }
        guard !isClosed else { return }
        switch state {
        case .connecting:
            setState(.connecting)
        case .connected(let path):
            withLock {
                if let previousPath = $0.activePath, previousPath != path {
                    invalidatePipeline(state: &$0)
                }
                $0.activePath = path
                $0.recovery.connected()
                $0.waitingForKeyframe = true
            }
            setState(.connected(path))
            engine.requestMediaKeyframe()
            onKeyframeRequired?()
        case .disconnected:
            recoverConnectivity()
        case .failed(let reason):
            failTransport(.engineSendFailed(reason), reportError: false)
        case .closed:
            let shouldReportClosed = withLock { state -> Bool in
                if case .failed = state.transportState { return false }
                guard state.transportState != .closed else { return false }
                state.transportState = .closed
                state.activePath = nil
                invalidatePipeline(state: &state)
                return true
            }
            if shouldReportClosed { onStateChanged?(.closed) }
        }
    }

    private func handleNetworkPath(_ path: InternetNetworkPath) {
        let action: NetworkRecoveryAction? = withLock {
            let action = $0.recovery.pathChanged(path)
            return isConnected($0.transportState) ? action : nil
        }
        if action == .restartICE { executeICERestart() }
    }

    private func recoverConnectivity() {
        let action: NetworkRecoveryAction? = withLock {
            guard isConnected($0.transportState) else { return nil }
            return $0.recovery.connectivityLost()
        }
        guard let action else { return }
        switch action {
        case .restartICE:
            executeICERestart()
        case .fail(let reason):
            setState(.failed(reason))
        }
    }

    private func executeICERestart() {
        let attempt = withLock { state -> Int in
            state.iceRestartCount += 1
            invalidatePipeline(state: &state)
            state.activePath = nil
            state.waitingForKeyframe = true
            return state.recovery.attempt
        }
        setState(.recovering(attempt: attempt))
        engine.restartICE()
    }

    private func handleNetworkQuality(_ sample: InternetNetworkQualitySample) {
        let profile = withLock { _ in adaptivePolicy.observe(sample) }
        if let profile {
            onAdaptiveProfileChanged?(profile)
        }
    }

    private func setState(_ state: InternetTransportState) {
        let changed = withLock { mutable -> Bool in
            guard mutable.transportState != state else { return false }
            mutable.transportState = state
            return true
        }
        if changed { onStateChanged?(state) }
    }

    private func failTransport(
        _ error: InternetTransportError,
        reportError: Bool = true
    ) {
        let failedState = InternetTransportState.failed(error.localizedDescription)
        let changed = withLock { state -> Bool in
            guard state.transportState != .closed else { return false }
            if case .failed = state.transportState { return false }
            state.transportState = failedState
            state.activePath = nil
            invalidatePipeline(state: &state)
            return true
        }
        guard changed else { return }
        engine.close()
        onStateChanged?(failedState)
        if reportError { onError?(error) }
    }

    private func invalidatePipeline(state: inout MutableState) {
        state.pipelineGeneration &+= 1
        state.controlQueue.removeAll()
        state.bufferedControlBytes = 0
        if state.mediaInFlight { state.droppedMediaFrames += 1 }
        if state.pendingMediaFrame != nil { state.droppedMediaFrames += 1 }
        state.pendingMediaFrame = nil
        state.controlInFlight = false
        state.mediaInFlight = false
        state.relayBytesReserved = 0
    }

    private func isConnected(_ state: InternetTransportState) -> Bool {
        if case .connected = state { return true }
        return false
    }

    private func releaseRelayReservation(for byteCount: Int, state: inout MutableState) {
        guard state.activePath == .relay else { return }
        state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(UInt64(byteCount))
    }

    @discardableResult
    private func withLock<T>(_ operation: (inout MutableState) -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation(&mutableState)
    }
}

private extension UInt64 {
    func subtractingClamped(_ value: UInt64) -> UInt64 {
        value > self ? 0 : self - value
    }
}
