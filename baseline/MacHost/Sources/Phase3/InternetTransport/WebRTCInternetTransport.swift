import Foundation

final class WebRTCInternetTransport {
    var onStateChanged: ((InternetTransportState) -> Void)?
    var onAdaptiveProfileChanged: ((AdaptiveMediaProfile) -> Void)?
    var onKeyframeRequired: (() -> Void)?
    var onError: ((InternetTransportError) -> Void)?
    var onControlReceived: ((Data) -> Void)?
    var onMediaReceived: ((Data) -> Void)?
    var onAudioRecordReceived: ((Data) -> Void)?
    var onBulkRecordReceived: ((Data) -> Void)?
    var onFreshSessionRecoveryRequired: ((Int) -> Void)?

    private final class ControlTransmissionCompletion {
        let identifier: UInt64

        private let lock = NSLock()
        private var handler: ((Result<Void, InternetTransportError>) -> Void)?

        init(
            identifier: UInt64,
            handler: @escaping (Result<Void, InternetTransportError>) -> Void
        ) {
            self.identifier = identifier
            self.handler = handler
        }

        func complete(_ result: Result<Void, InternetTransportError>) {
            lock.lock()
            let handler = handler
            self.handler = nil
            lock.unlock()
            handler?(result)
        }
    }

    private struct ControlTransmission {
        let identifier: UInt64
        let payload: Data
        let generation: UInt64
        let path: InternetPathKind
        let engineContext: WebRTCEngineTransmissionContext
        let relayReservationBytes: UInt64
        let completion: ControlTransmissionCompletion?
    }

    private struct ControlTransmissionQueue {
        private var storage: [ControlTransmission?] = []
        private var head = 0

        var count: Int { storage.count - head }

        mutating func append(_ transmission: ControlTransmission) {
            storage.append(transmission)
        }

        mutating func popFirst() -> ControlTransmission? {
            guard head < storage.count else { return nil }
            let transmission = storage[head]
            storage[head] = nil
            head += 1
            if head >= 64, head * 2 >= storage.count {
                storage.removeFirst(head)
                head = 0
            }
            return transmission
        }

        mutating func removeAll() {
            storage.removeAll(keepingCapacity: true)
            head = 0
        }

        func payloadBytes() -> Int {
            storage[head...].compactMap { $0 }.reduce(0) { $0 + $1.payload.count }
        }

        func relayReservationBytes() -> UInt64 {
            storage[head...].compactMap { $0 }.reduce(0) { partial, transmission in
                partial.addingClamped(transmission.relayReservationBytes)
            }
        }
    }

    private struct BulkTransmission {
        let identifier: UInt64
        let payload: Data
        let generation: UInt64
        let path: InternetPathKind
        let engineContext: WebRTCEngineTransmissionContext
        let relayReservationBytes: UInt64
    }

    private struct BulkTransmissionQueue {
        private var storage: [BulkTransmission?] = []
        private var head = 0

        var count: Int { storage.count - head }

        mutating func append(_ transmission: BulkTransmission) {
            storage.append(transmission)
        }

        mutating func popFirst() -> BulkTransmission? {
            guard head < storage.count else { return nil }
            let transmission = storage[head]
            storage[head] = nil
            head += 1
            if head >= 64, head * 2 >= storage.count {
                storage.removeFirst(head)
                head = 0
            }
            return transmission
        }

        mutating func removeAll() {
            storage.removeAll(keepingCapacity: true)
            head = 0
        }

        func payloadBytes() -> Int {
            storage[head...].compactMap { $0 }.reduce(0) { $0 + $1.payload.count }
        }

        func relayReservationBytes() -> UInt64 {
            storage[head...].compactMap { $0 }.reduce(0) { partial, transmission in
                partial.addingClamped(transmission.relayReservationBytes)
            }
        }
    }

    private struct FailureTransition {
        let failedState: InternetTransportState
        let generation: UInt64
        let error: InternetTransportError
        let reportError: Bool
        let invalidatedControlCompletions: [ControlTransmissionCompletion]
    }

    private struct RecoveryTransition {
        let attempt: Int
        let changed: Bool
        let generation: UInt64
        let recoveringState: InternetTransportState
        let invalidatedControlCompletions: [ControlTransmissionCompletion]
    }

    private enum PreparedRecovery {
        case iceRestart(RecoveryTransition)
        case freshSession(RecoveryTransition)
        case failure(FailureTransition)
    }

    private struct MutableState {
        var transportState: InternetTransportState = .idle
        var activePath: InternetPathKind?
        var engineTransmissionContext: WebRTCEngineTransmissionContext?
        var pipelineGeneration: UInt64 = 0
        var pipelineGenerationExhausted = false
        var nextControlTransmissionIdentifier: UInt64 = 0
        var controlInFlight = false
        var activeControlTransmissionIdentifier: UInt64?
        var controlQueue = ControlTransmissionQueue()
        var controlCompletions: [UInt64: ControlTransmissionCompletion] = [:]
        var dispatchedControlTransmissionIdentifiers: Set<UInt64> = []
        var dispatchedControlRelayReservations: [UInt64: UInt64] = [:]
        var nextMediaTransmissionIdentifier: UInt64 = 0
        var dispatchedMediaTransmissionIdentifiers: Set<UInt64> = []
        var dispatchedMediaRelayReservations: [UInt64: UInt64] = [:]
        var nextAudioTransmissionIdentifier: UInt64 = 0
        var dispatchedAudioTransmissionIdentifiers: Set<UInt64> = []
        var dispatchedAudioRelayReservations: [UInt64: UInt64] = [:]
        var nextBulkTransmissionIdentifier: UInt64 = 0
        var dispatchedBulkTransmissionIdentifiers: Set<UInt64> = []
        var dispatchedBulkRelayReservations: [UInt64: UInt64] = [:]
        var bufferedControlBytes = 0
        var mediaInFlight = false
        var pendingMediaFrame: EncodedInternetFrame?
        var audioInFlight = false
        var pendingAudioRecord: Data?
        var bulkInFlight = false
        var activeBulkTransmissionIdentifier: UInt64?
        var bulkQueue = BulkTransmissionQueue()
        var bufferedBulkBytes = 0
        var waitingForKeyframe = true
        var controlBytesSent: UInt64 = 0
        var mediaBytesSent: UInt64 = 0
        var audioBytesSent: UInt64 = 0
        var bulkBytesSent: UInt64 = 0
        var relayBytesSent: UInt64 = 0
        var relayBytesReserved: UInt64 = 0
        var droppedMediaFrames: UInt64 = 0
        var droppedAudioRecords: UInt64 = 0
        var iceRestartCount: UInt64 = 0
        var recoveryAttemptAwaitingOutcome = false
        var recovery: NetworkRecoveryStateMachine
    }

    private let engine: WebRTCEnginePort
    private let hasApplicationCipher: Bool
    private let limits: InternetTransportLimits
    private let adaptivePolicy: AdaptiveMediaPolicy
    private let recoveryStrategy: InternetRecoveryStrategy
    private let networkHandoffRecoveryStrategy: InternetRecoveryStrategy
    private let lock = NSLock()
    private let sendGate = NSRecursiveLock()
    private let engineLifecycleGate = NSRecursiveLock()
    private var engineCloseInvoked = false
    private let beforeEngineStart: (() -> Void)?
    private let beforeControlSend: (() -> Void)?
    private let beforeMediaRecordSend: (() -> Void)?
    private let beforeFailureSideEffects: (() -> Void)?
    private let duringRecoveryDecision: (() -> Void)?
    private let duringMediaRecoveryTransition: (() -> Void)?
    private var mutableState: MutableState

    init(
        engine: WebRTCEnginePort = ProductionWebRTCEngine(),
        packetCipher: PlatformSessionPacketCipher? = nil,
        limits: InternetTransportLimits = .standard,
        recoveryPolicy: NetworkRecoveryPolicy = .standard,
        adaptivePolicy: AdaptiveMediaPolicy = AdaptiveMediaPolicy(),
        recoveryStrategy: InternetRecoveryStrategy = .restartICE,
        networkHandoffRecoveryStrategy: InternetRecoveryStrategy = .restartICE,
        beforeEngineStart: (() -> Void)? = nil,
        beforeControlSend: (() -> Void)? = nil,
        beforeMediaRecordSend: (() -> Void)? = nil,
        beforeFailureSideEffects: (() -> Void)? = nil,
        duringRecoveryDecision: (() -> Void)? = nil,
        duringMediaRecoveryTransition: (() -> Void)? = nil,
        initialPipelineGeneration: UInt64 = 0,
        initialControlTransmissionIdentifier: UInt64 = 0,
        initialMediaTransmissionIdentifier: UInt64 = 0,
        initialControlBytesSent: UInt64 = 0,
        initialMediaBytesSent: UInt64 = 0,
        initialRelayBytesSent: UInt64 = 0,
        initialRelayBytesReserved: UInt64 = 0
    ) {
        if let packetCipher {
            self.engine = ProtectedWebRTCEngine(
                engine: engine,
                packetCipher: packetCipher,
                limits: limits
            )
            self.hasApplicationCipher = true
        } else {
            self.engine = engine
            self.hasApplicationCipher = false
        }
        self.limits = limits
        self.adaptivePolicy = adaptivePolicy
        self.recoveryStrategy = recoveryStrategy
        self.networkHandoffRecoveryStrategy = networkHandoffRecoveryStrategy
        self.beforeEngineStart = beforeEngineStart
        self.beforeControlSend = beforeControlSend
        self.beforeMediaRecordSend = beforeMediaRecordSend
        self.beforeFailureSideEffects = beforeFailureSideEffects
        self.duringRecoveryDecision = duringRecoveryDecision
        self.duringMediaRecoveryTransition = duringMediaRecoveryTransition
        var initialState = MutableState(recovery: NetworkRecoveryStateMachine(policy: recoveryPolicy))
        initialState.pipelineGeneration = initialPipelineGeneration
        initialState.nextControlTransmissionIdentifier = initialControlTransmissionIdentifier
        initialState.nextMediaTransmissionIdentifier = initialMediaTransmissionIdentifier
        initialState.controlBytesSent = initialControlBytesSent
        initialState.mediaBytesSent = initialMediaBytesSent
        initialState.relayBytesSent = initialRelayBytesSent
        initialState.relayBytesReserved = initialRelayBytesReserved
        self.mutableState = initialState
        self.engine.install(callbacks: WebRTCEngineCallbacks(
            connectionStateChanged: { [weak self] state in self?.handleEngineState(state) },
            transmissionContextChanged: { [weak self] context in
                self?.handleEngineTransmissionContext(context)
            },
            networkPathChanged: { [weak self] path in self?.handleNetworkPath(path) },
            networkQualitySampled: { [weak self] sample in self?.handleNetworkQuality(sample) },
            messageReceived: { [weak self] payload, channel in
                self?.handleInbound(payload, channel: channel)
            }
        ))
    }

    deinit {
        lock.lock()
        let pendingCompletions = mutableState.controlCompletions.values.sorted {
            $0.identifier < $1.identifier
        }
        mutableState.controlCompletions.removeAll()
        lock.unlock()
        completeControlTransmissions(pendingCompletions, with: .notConnected)
        closeEngineOnce()
    }

    func start(configuration: WebRTCTransportConfiguration) throws {
        try configuration.validate()
        guard hasApplicationCipher else {
            throw InternetTransportError.invalidConfiguration(
                "Protocol v1 application encryption and a platform-backed session cipher are required."
            )
        }
        beforeEngineStart?()
        engineLifecycleGate.lock()
        defer { engineLifecycleGate.unlock() }
        let startupAdmission = withSendGate {
            withLock { state -> Result<UInt64, InternetTransportError> in
                switch state.transportState {
                case .idle:
                    state.transportState = .connecting
                    return .success(state.pipelineGeneration)
                case .failed(let reason):
                    return .failure(.engineUnavailable(
                        "The Internet transport failed and cannot be restarted: \(reason)"
                    ))
                case .closed:
                    return .failure(.engineUnavailable(
                        "The Internet transport is closed and cannot be restarted."
                    ))
                case .connecting, .connected, .recovering:
                    return .failure(.engineUnavailable(
                        "The Internet transport is already started."
                    ))
                }
            }
        }
        let startupGeneration: UInt64
        switch startupAdmission {
        case .success(let generation):
            startupGeneration = generation
        case .failure(let error):
            throw error
        }
        do {
            try engine.start(
                configuration: configuration,
                channels: InternetTransportChannel.allCases.map(\.dataChannelConfiguration)
            )
        } catch {
            let transportError = (error as? InternetTransportError)
                ?? .engineUnavailable(error.localizedDescription)
            setState(.failed(transportError.localizedDescription))
            throw transportError
        }
        let shouldPublishConnecting = withSendGate {
            withLock {
                $0.pipelineGeneration == startupGeneration
                    && $0.transportState == .connecting
            }
        }
        if shouldPublishConnecting { onStateChanged?(.connecting) }
    }

    @discardableResult
    func sendControl(
        _ payload: Data,
        completion: ((Result<Void, InternetTransportError>) -> Void)? = nil
    ) -> Result<Void, InternetTransportError> {
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

        let encryptedPayloadBytes = InternetMediaRecordContract.encryptedRecordBytes(
            forPlaintextBytes: payload.count
        )
        var failureTransition: FailureTransition?
        var transmission: ControlTransmission?
        let result: Result<Void, InternetTransportError> = withSendGate {
            let admissionError: InternetTransportError? = withLock { state in
                guard isConnected(state.transportState),
                      !state.pipelineGenerationExhausted,
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else {
                    return .notConnected
                }
                guard state.bufferedControlBytes + payload.count <= limits.maximumBufferedControlBytes else {
                    return .controlBacklogExceeded(maximumBytes: limits.maximumBufferedControlBytes)
                }
                let bufferedControlMessages = state.controlQueue.count + (state.controlInFlight ? 1 : 0)
                guard bufferedControlMessages < limits.maximumBufferedControlMessages else {
                    return .controlBacklogExceeded(maximumBytes: limits.maximumBufferedControlBytes)
                }
                let relayReservationBytes = activePath == .relay ? encryptedPayloadBytes : 0
                if relayReservationBytes > 0 {
                    guard relayReservationFits(
                        sent: state.relayBytesSent,
                        reserved: state.relayBytesReserved,
                        additional: relayReservationBytes
                    ) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    state.relayBytesReserved = state.relayBytesReserved.addingClamped(
                        relayReservationBytes
                    )
                }
                guard state.nextControlTransmissionIdentifier < UInt64.max else {
                    return .sequenceExhausted("control transmission identifier")
                }
                state.nextControlTransmissionIdentifier += 1
                let trackedCompletion = completion.map {
                    ControlTransmissionCompletion(
                        identifier: state.nextControlTransmissionIdentifier,
                        handler: $0
                    )
                }
                let admitted = ControlTransmission(
                    identifier: state.nextControlTransmissionIdentifier,
                    payload: payload,
                    generation: state.pipelineGeneration,
                    path: activePath,
                    engineContext: engineContext,
                    relayReservationBytes: relayReservationBytes,
                    completion: trackedCompletion
                )
                if let trackedCompletion {
                    state.controlCompletions[admitted.identifier] = trackedCompletion
                }
                state.bufferedControlBytes += payload.count
                if state.controlInFlight {
                    state.controlQueue.append(admitted)
                } else {
                    state.controlInFlight = true
                    state.activeControlTransmissionIdentifier = admitted.identifier
                    transmission = admitted
                }
                return nil
            }

            if let admissionError {
                if case .controlBacklogExceeded = admissionError {
                    failureTransition = prepareFailureWithinSendGate(admissionError)
                } else if case .sequenceExhausted = admissionError {
                    failureTransition = prepareFailureWithinSendGate(admissionError)
                }
                return .failure(admissionError)
            }
            return .success(())
        }
        if let failureTransition { performFailureTransition(failureTransition) }
        if let transmission { transmitControl(transmission) }
        return result
    }

    @discardableResult
    func sendMedia(_ frame: EncodedInternetFrame) -> Result<Void, InternetTransportError> {
        guard frame.mediaPayloadBytes > 0,
              !frame.records.isEmpty,
              !frame.records.contains(where: \.isEmpty) else {
            return .failure(.emptyPayload(channel: .media))
        }
        guard frame.mediaPayloadBytes <= limits.maximumMediaFrameBytes else {
            return .failure(.payloadTooLarge(
                channel: .media,
                actual: frame.mediaPayloadBytes,
                maximum: limits.maximumMediaFrameBytes
            ))
        }
        if let oversizedRecord = frame.records.first(where: {
            $0.count > InternetMediaRecordContract.maximumPlaintextRecordBytes
        }) {
            return .failure(.payloadTooLarge(
                channel: .media,
                actual: oversizedRecord.count,
                maximum: InternetMediaRecordContract.maximumPlaintextRecordBytes
            ))
        }

        var frameToTransmit: EncodedInternetFrame?
        var shouldRequestKeyframe = false
        var transmissionGeneration: UInt64 = 0
        let encryptedFrameBytes = frame.totalEncryptedRecordBytes
        let admissionError: InternetTransportError? = withSendGate {
            withLock { state in
                guard isConnected(state.transportState),
                      !state.pipelineGenerationExhausted,
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else { return .notConnected }
                let releasesKeyframeGate = state.waitingForKeyframe
                if releasesKeyframeGate {
                    guard frame.isKeyframe else {
                        state.droppedMediaFrames += 1
                        return nil
                    }
                }
                transmissionGeneration = state.pipelineGeneration
                guard state.mediaInFlight else {
                    guard reserveRelayBytes(encryptedFrameBytes, state: &state) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    if releasesKeyframeGate { state.waitingForKeyframe = false }
                    state.mediaInFlight = true
                    frameToTransmit = frame
                    return nil
                }

                if let pending = state.pendingMediaFrame {
                    if pending.isKeyframe && !frame.isKeyframe {
                        state.droppedMediaFrames += 1
                    } else if frame.isKeyframe {
                        guard reserveRelayBytes(
                            encryptedFrameBytes,
                            replacing: pending.totalEncryptedRecordBytes,
                            state: &state
                        ) else {
                            return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                        }
                        if releasesKeyframeGate { state.waitingForKeyframe = false }
                        state.pendingMediaFrame = frame
                        state.droppedMediaFrames += 1
                    } else {
                        state.pendingMediaFrame = nil
                        state.waitingForKeyframe = true
                        state.droppedMediaFrames += 2
                        releaseRelayReservation(
                            for: pending.totalEncryptedRecordBytes,
                            state: &state
                        )
                        shouldRequestKeyframe = true
                    }
                } else {
                    guard reserveRelayBytes(encryptedFrameBytes, state: &state) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    if releasesKeyframeGate { state.waitingForKeyframe = false }
                    state.pendingMediaFrame = frame
                }
                return nil
            }
        }

        if let admissionError { return .failure(admissionError) }
        if shouldRequestKeyframe {
            engine.requestMediaKeyframe()
            onKeyframeRequired?()
        }
        if let frameToTransmit { transmitMedia(frameToTransmit, generation: transmissionGeneration) }
        return .success(())
    }

    @discardableResult
    func sendAudioRecord(_ payload: Data) -> Result<Void, InternetTransportError> {
        guard !payload.isEmpty else {
            return .failure(.emptyPayload(channel: .audio))
        }
        guard payload.count <= InternetAudioRecordContract.maximumPlaintextRecordBytes else {
            return .failure(.payloadTooLarge(
                channel: .audio,
                actual: payload.count,
                maximum: InternetAudioRecordContract.maximumPlaintextRecordBytes
            ))
        }

        var recordToTransmit: Data?
        var transmissionGeneration: UInt64 = 0
        let encryptedRecordBytes = InternetAudioRecordContract.encryptedRecordBytes(
            forPlaintextBytes: payload.count
        )
        let admissionError: InternetTransportError? = withSendGate {
            withLock { state in
                guard isConnected(state.transportState),
                      !state.pipelineGenerationExhausted,
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else { return .notConnected }
                transmissionGeneration = state.pipelineGeneration
                guard state.audioInFlight else {
                    guard reserveRelayBytes(encryptedRecordBytes, state: &state) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    state.audioInFlight = true
                    recordToTransmit = payload
                    return nil
                }

                if let pending = state.pendingAudioRecord {
                    let pendingEncryptedRecordBytes = InternetAudioRecordContract.encryptedRecordBytes(
                        forPlaintextBytes: pending.count
                    )
                    guard reserveRelayBytes(
                        encryptedRecordBytes,
                        replacing: pendingEncryptedRecordBytes,
                        state: &state
                    ) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    state.droppedAudioRecords += 1
                } else {
                    guard reserveRelayBytes(encryptedRecordBytes, state: &state) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                }
                state.pendingAudioRecord = payload
                return nil
            }
        }

        if let admissionError { return .failure(admissionError) }
        if let recordToTransmit { transmitAudioRecord(recordToTransmit, generation: transmissionGeneration) }
        return .success(())
    }

    @discardableResult
    func sendBulkRecord(_ payload: Data) -> Result<Void, InternetTransportError> {
        guard !payload.isEmpty else {
            return .failure(.emptyPayload(channel: .bulk))
        }
        guard payload.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes else {
            return .failure(.payloadTooLarge(
                channel: .bulk,
                actual: payload.count,
                maximum: InternetBulkRecordContract.maximumPlaintextRecordBytes
            ))
        }

        let encryptedPayloadBytes = InternetBulkRecordContract.encryptedRecordBytes(
            forPlaintextBytes: payload.count
        )
        var failureTransition: FailureTransition?
        var transmission: BulkTransmission?
        let result: Result<Void, InternetTransportError> = withSendGate {
            let admissionError: InternetTransportError? = withLock { state in
                guard isConnected(state.transportState),
                      !state.pipelineGenerationExhausted,
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else { return .notConnected }
                guard state.bufferedBulkBytes + payload.count <= limits.maximumBufferedBulkBytes else {
                    return .bulkBacklogExceeded(maximumBytes: limits.maximumBufferedBulkBytes)
                }
                let bufferedBulkMessages = state.bulkQueue.count + (state.bulkInFlight ? 1 : 0)
                guard bufferedBulkMessages < limits.maximumBufferedBulkMessages else {
                    return .bulkBacklogExceeded(maximumBytes: limits.maximumBufferedBulkBytes)
                }
                let relayReservationBytes = activePath == .relay ? encryptedPayloadBytes : 0
                if relayReservationBytes > 0 {
                    guard relayReservationFits(
                        sent: state.relayBytesSent,
                        reserved: state.relayBytesReserved,
                        additional: relayReservationBytes
                    ) else {
                        return .relayBudgetExceeded(maximumBytes: limits.maximumRelayBytesPerSession)
                    }
                    state.relayBytesReserved = state.relayBytesReserved.addingClamped(
                        relayReservationBytes
                    )
                }
                guard state.nextBulkTransmissionIdentifier < UInt64.max else {
                    return .sequenceExhausted("bulk transmission identifier")
                }
                state.nextBulkTransmissionIdentifier += 1
                let admitted = BulkTransmission(
                    identifier: state.nextBulkTransmissionIdentifier,
                    payload: payload,
                    generation: state.pipelineGeneration,
                    path: activePath,
                    engineContext: engineContext,
                    relayReservationBytes: relayReservationBytes
                )
                state.bufferedBulkBytes += payload.count
                if state.bulkInFlight {
                    state.bulkQueue.append(admitted)
                } else {
                    state.bulkInFlight = true
                    state.activeBulkTransmissionIdentifier = admitted.identifier
                    transmission = admitted
                }
                return nil
            }

            if let admissionError {
                if case .bulkBacklogExceeded = admissionError {
                    failureTransition = prepareFailureWithinSendGate(admissionError)
                } else if case .sequenceExhausted = admissionError {
                    failureTransition = prepareFailureWithinSendGate(admissionError)
                }
                return .failure(admissionError)
            }
            return .success(())
        }
        if let failureTransition { performFailureTransition(failureTransition) }
        if let transmission { transmitBulk(transmission) }
        return result
    }

    func close() {
        let closeTransition = {
            engineLifecycleGate.lock()
            defer { engineLifecycleGate.unlock() }
            let transition = withSendGate {
                withLock { state -> (
                    changed: Bool,
                    completions: [ControlTransmissionCompletion]
                ) in
                    guard state.transportState != .closed else { return (false, []) }
                    state.transportState = .closed
                    state.activePath = nil
                    return (true, invalidatePipeline(state: &state))
                }
            }
            closeEngineOnce()
            return transition
        }()
        completeControlTransmissions(closeTransition.completions, with: .notConnected)
        if closeTransition.changed { onStateChanged?(.closed) }
    }

    func snapshot() -> InternetTransportSnapshot {
        withLock {
            InternetTransportSnapshot(
                state: $0.transportState,
                activePath: $0.activePath,
                controlBytesSent: $0.controlBytesSent,
                mediaBytesSent: $0.mediaBytesSent,
                audioBytesSent: $0.audioBytesSent,
                bulkBytesSent: $0.bulkBytesSent,
                relayBytesSent: $0.relayBytesSent,
                relayBytesReserved: $0.relayBytesReserved,
                droppedMediaFrames: $0.droppedMediaFrames,
                droppedAudioRecords: $0.droppedAudioRecords,
                iceRestartCount: $0.iceRestartCount,
                bufferedControlBytes: $0.bufferedControlBytes,
                bufferedControlMessages: $0.controlQueue.count + ($0.controlInFlight ? 1 : 0),
                bufferedBulkBytes: $0.bufferedBulkBytes,
                bufferedBulkMessages: $0.bulkQueue.count + ($0.bulkInFlight ? 1 : 0),
                mediaInFlight: $0.mediaInFlight,
                hasPendingMediaFrame: $0.pendingMediaFrame != nil,
                audioInFlight: $0.audioInFlight,
                hasPendingAudioRecord: $0.pendingAudioRecord != nil,
                bulkInFlight: $0.bulkInFlight
            )
        }
    }

    private func transmitControl(_ transmission: ControlTransmission) {
        beforeControlSend?()
        var rejectedCompletions: [ControlTransmissionCompletion] = []
        let canSend = withSendGate {
            withLock { state -> Bool in
                guard state.pipelineGeneration == transmission.generation,
                      state.controlInFlight,
                      state.activeControlTransmissionIdentifier == transmission.identifier,
                      isConnected(state.transportState),
                      state.activePath == transmission.path,
                      state.engineTransmissionContext == transmission.engineContext else {
                    rejectedCompletions = recoverRejectedControlSend(
                        transmission,
                        state: &state
                    )
                    return false
                }
                state.dispatchedControlTransmissionIdentifiers.insert(transmission.identifier)
                if transmission.relayReservationBytes > 0 {
                    state.dispatchedControlRelayReservations[transmission.identifier] =
                        transmission.relayReservationBytes
                }
                return true
            }
        }
        guard canSend else {
            completeControlTransmissions(rejectedCompletions, with: .notConnected)
            return
        }

        let completionHandoff = EngineSendCompletionHandoff()
        engine.send(
            transmission.payload,
            channel: .control,
            expectedContext: transmission.engineContext
        ) { [weak self] result in
            guard let self else {
                transmission.completion?.complete(.failure(.notConnected))
                return
            }
            if completionHandoff.receive(result) {
                self.handleControlCompletion(transmission, result: result)
            }
        }
        let synchronousResult = completionHandoff.markEngineSendReturned()
        if let synchronousResult {
            handleControlCompletion(transmission, result: synchronousResult)
        }
    }

    private func handleControlCompletion(
        _ transmission: ControlTransmission,
        result: Result<Void, Error>
    ) {
        var next: ControlTransmission?
        var failureTransition: FailureTransition?
        var completion: ControlTransmissionCompletion?
        var completionResult: Result<Void, InternetTransportError>?
        withSendGate {
            var reportedError: InternetTransportError?
            withLock { state in
                guard state.dispatchedControlTransmissionIdentifiers.remove(
                    transmission.identifier
                ) != nil else { return }
                let relayReservationBytes = state.dispatchedControlRelayReservations
                    .removeValue(forKey: transmission.identifier) ?? 0
                state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
                    relayReservationBytes
                )
                let isCurrent = state.pipelineGeneration == transmission.generation
                    && state.controlInFlight
                    && state.activeControlTransmissionIdentifier == transmission.identifier
                if case .success = result {
                    let (controlBytesSent, controlOverflow) = state.controlBytesSent
                        .addingReportingOverflow(UInt64(transmission.payload.count))
                    let (relayBytesSent, relayOverflow) = state.relayBytesSent
                        .addingReportingOverflow(relayReservationBytes)
                    guard !controlOverflow, !relayOverflow else {
                        let transportError = InternetTransportError.sequenceExhausted(
                            "transport byte accounting"
                        )
                        completion = state.controlCompletions.removeValue(
                            forKey: transmission.identifier
                        )
                        completionResult = .failure(transportError)
                        reportedError = transportError
                        return
                    }
                    state.controlBytesSent = controlBytesSent
                    state.relayBytesSent = relayBytesSent
                }
                guard isCurrent else {
                    completion = state.controlCompletions.removeValue(
                        forKey: transmission.identifier
                    )
                    completionResult = .failure(.notConnected)
                    return
                }
                state.bufferedControlBytes = max(
                    0,
                    state.bufferedControlBytes - transmission.payload.count
                )
                switch result {
                case .success:
                    completion = state.controlCompletions.removeValue(
                        forKey: transmission.identifier
                    )
                    completionResult = .success(())
                    if let queued = state.controlQueue.popFirst() {
                        next = queued
                        state.activeControlTransmissionIdentifier = next?.identifier
                    } else {
                        state.controlInFlight = false
                        state.activeControlTransmissionIdentifier = nil
                    }
                case .failure(let error):
                    let transportError = InternetTransportError.engineSendFailed(
                        error.localizedDescription
                    )
                    completion = state.controlCompletions.removeValue(
                        forKey: transmission.identifier
                    )
                    completionResult = .failure(transportError)
                    reportedError = transportError
                }
            }
            if let reportedError {
                failureTransition = prepareFailureWithinSendGate(reportedError)
            }
        }
        if let completion, let completionResult {
            completion.complete(completionResult)
        }
        if let failureTransition {
            performFailureTransition(failureTransition)
        } else if let next {
            transmitControl(next)
        }
    }

    private func transmitBulk(_ transmission: BulkTransmission) {
        var canSend = false
        let claimed = withSendGate {
            withLock { state -> WebRTCEngineTransmissionContext? in
                guard state.pipelineGeneration == transmission.generation,
                      state.bulkInFlight,
                      state.activeBulkTransmissionIdentifier == transmission.identifier,
                      isConnected(state.transportState),
                      state.activePath == transmission.path,
                      state.engineTransmissionContext == transmission.engineContext else {
                    recoverRejectedBulkSend(transmission, state: &state)
                    return nil
                }
                state.dispatchedBulkTransmissionIdentifiers.insert(transmission.identifier)
                if transmission.relayReservationBytes > 0 {
                    state.dispatchedBulkRelayReservations[transmission.identifier] =
                        transmission.relayReservationBytes
                }
                canSend = true
                return transmission.engineContext
            }
        }
        guard canSend, let engineContext = claimed else { return }

        let completionHandoff = EngineSendCompletionHandoff()
        engine.send(
            transmission.payload,
            channel: .bulk,
            expectedContext: engineContext
        ) { [weak self] result in
            guard let self else { return }
            if completionHandoff.receive(result) {
                self.handleBulkCompletion(transmission, result: result)
            }
        }
        let synchronousResult = completionHandoff.markEngineSendReturned()
        if let synchronousResult {
            handleBulkCompletion(transmission, result: synchronousResult)
        }
    }

    private func handleBulkCompletion(
        _ transmission: BulkTransmission,
        result: Result<Void, Error>
    ) {
        var next: BulkTransmission?
        var failureTransition: FailureTransition?
        withSendGate {
            var reportedError: InternetTransportError?
            withLock { state in
                guard state.dispatchedBulkTransmissionIdentifiers.remove(
                    transmission.identifier
                ) != nil else { return }
                let relayReservationBytes = state.dispatchedBulkRelayReservations
                    .removeValue(forKey: transmission.identifier) ?? 0
                state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
                    relayReservationBytes
                )
                let isCurrent = state.pipelineGeneration == transmission.generation
                    && state.bulkInFlight
                    && state.activeBulkTransmissionIdentifier == transmission.identifier
                if case .success = result {
                    let (bulkBytesSent, bulkOverflow) = state.bulkBytesSent
                        .addingReportingOverflow(UInt64(transmission.payload.count))
                    let (relayBytesSent, relayOverflow) = state.relayBytesSent
                        .addingReportingOverflow(relayReservationBytes)
                    guard !bulkOverflow, !relayOverflow else {
                        reportedError = .sequenceExhausted("transport byte accounting")
                        return
                    }
                    state.bulkBytesSent = bulkBytesSent
                    state.relayBytesSent = relayBytesSent
                }
                guard isCurrent else { return }
                state.bufferedBulkBytes = max(
                    0,
                    state.bufferedBulkBytes - transmission.payload.count
                )
                switch result {
                case .success:
                    if let queued = state.bulkQueue.popFirst() {
                        next = queued
                        state.activeBulkTransmissionIdentifier = next?.identifier
                    } else {
                        state.bulkInFlight = false
                        state.activeBulkTransmissionIdentifier = nil
                    }
                case .failure(let error):
                    reportedError = .engineSendFailed(error.localizedDescription)
                }
            }
            if let reportedError {
                failureTransition = prepareFailureWithinSendGate(reportedError)
            }
        }
        if let failureTransition {
            performFailureTransition(failureTransition)
        } else if let next {
            transmitBulk(next)
        }
    }

    private func transmitMedia(
        _ frame: EncodedInternetFrame,
        recordIndex: Int = 0,
        generation: UInt64
    ) {
        let record = frame.records[recordIndex]
        var rejectedRecovery = RejectedMediaSendRecovery.none
        var failureTransition: FailureTransition?
        beforeMediaRecordSend?()
        let transmission = withSendGate {
            var sequenceError: InternetTransportError?
            let claimed = withLock { state -> (UInt64, WebRTCEngineTransmissionContext)? in
                guard state.pipelineGeneration == generation,
                      !state.pipelineGenerationExhausted,
                      state.mediaInFlight,
                      isConnected(state.transportState),
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else {
                    rejectedRecovery = recoverRejectedMediaSend(
                        frame,
                        recordIndex: recordIndex,
                        generation: generation,
                        state: &state
                    )
                    return nil
                }
                guard state.nextMediaTransmissionIdentifier < UInt64.max else {
                    sequenceError = .sequenceExhausted("media transmission identifier")
                    return nil
                }
                state.nextMediaTransmissionIdentifier += 1
                let identifier = state.nextMediaTransmissionIdentifier
                state.dispatchedMediaTransmissionIdentifiers.insert(identifier)
                if state.activePath == .relay {
                    state.dispatchedMediaRelayReservations[identifier] =
                        InternetMediaRecordContract.encryptedRecordBytes(
                            forPlaintextBytes: record.count
                        )
                }
                return (identifier, engineContext)
            }
            if let sequenceError {
                failureTransition = prepareFailureWithinSendGate(sequenceError)
            }
            return claimed
        }
        if let failureTransition {
            performFailureTransition(failureTransition)
            return
        }
        guard let (transmissionIdentifier, engineContext) = transmission else {
            if rejectedRecovery.shouldRequestKeyframe {
                engine.requestMediaKeyframe()
                onKeyframeRequired?()
            }
            if let nextFrame = rejectedRecovery.nextFrame {
                transmitMedia(nextFrame, generation: generation)
            }
            return
        }
        engine.send(
            record,
            channel: .media,
            expectedContext: engineContext
        ) { [weak self] result in
            guard let self else { return }
            var nextFrame: EncodedInternetFrame?
            var nextRecordIndex: Int?
            var reportedError: InternetTransportError?
            var accountingFailure: InternetTransportError?
            var completionFailureTransition: FailureTransition?
            var shouldRequestKeyframe = false
            self.withSendGate {
                self.withLock { state in
                    guard state.dispatchedMediaTransmissionIdentifiers.remove(
                        transmissionIdentifier
                    ) != nil else { return }
                    let relayReservationBytes = state.dispatchedMediaRelayReservations
                        .removeValue(forKey: transmissionIdentifier) ?? 0
                    state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
                        relayReservationBytes
                    )
                    if case .success = result {
                        let (mediaBytesSent, mediaOverflow) = state.mediaBytesSent
                            .addingReportingOverflow(UInt64(record.count))
                        let (relayBytesSent, relayOverflow) = state.relayBytesSent
                            .addingReportingOverflow(relayReservationBytes)
                        guard !mediaOverflow, !relayOverflow else {
                            accountingFailure = .sequenceExhausted("transport byte accounting")
                            return
                        }
                        state.mediaBytesSent = mediaBytesSent
                        state.relayBytesSent = relayBytesSent
                    }
                    guard state.pipelineGeneration == generation,
                          state.mediaInFlight else { return }
                    switch result {
                    case .success:
                        if recordIndex + 1 < frame.records.count {
                            nextFrame = frame
                            nextRecordIndex = recordIndex + 1
                        } else if let pending = state.pendingMediaFrame {
                            nextFrame = pending
                            nextRecordIndex = 0
                            state.pendingMediaFrame = nil
                        } else {
                            state.mediaInFlight = false
                        }
                    case .failure(let error):
                        let remainingEncryptedBytes = frame.records
                            .dropFirst(recordIndex + 1)
                            .reduce(UInt64(0)) {
                                $0 + InternetMediaRecordContract.encryptedRecordBytes(
                                    forPlaintextBytes: $1.count
                                )
                            }
                        self.releaseRelayReservation(for: remainingEncryptedBytes, state: &state)
                        state.droppedMediaFrames += 1
                        state.waitingForKeyframe = true
                        reportedError = .engineSendFailed(error.localizedDescription)
                        if let pending = state.pendingMediaFrame, pending.isKeyframe {
                            nextFrame = pending
                            nextRecordIndex = 0
                            state.pendingMediaFrame = nil
                            state.waitingForKeyframe = false
                        } else {
                            if let pending = state.pendingMediaFrame {
                                state.droppedMediaFrames += 1
                                self.releaseRelayReservation(
                                    for: pending.totalEncryptedRecordBytes,
                                    state: &state
                                )
                            }
                            state.pendingMediaFrame = nil
                            state.mediaInFlight = false
                            shouldRequestKeyframe = true
                        }
                    }
                }
                if let accountingFailure {
                    completionFailureTransition = self.prepareFailureWithinSendGate(accountingFailure)
                }
            }
            if let completionFailureTransition {
                self.performFailureTransition(completionFailureTransition)
                return
            }
            if let reportedError {
                self.onError?(reportedError)
            }
            if shouldRequestKeyframe {
                self.engine.requestMediaKeyframe()
                self.onKeyframeRequired?()
            }
            if let nextFrame, let nextRecordIndex {
                self.transmitMedia(
                    nextFrame,
                    recordIndex: nextRecordIndex,
                    generation: generation
                )
            }
        }
    }

    private func transmitAudioRecord(_ payload: Data, generation: UInt64) {
        var rejectedRecovery = RejectedAudioSendRecovery.none
        var failureTransition: FailureTransition?
        let transmission = withSendGate {
            var sequenceError: InternetTransportError?
            let claimed = withLock { state -> (UInt64, WebRTCEngineTransmissionContext)? in
                guard state.pipelineGeneration == generation,
                      !state.pipelineGenerationExhausted,
                      state.audioInFlight,
                      isConnected(state.transportState),
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext,
                      engineContext.path == activePath else {
                    rejectedRecovery = recoverRejectedAudioSend(
                        payload,
                        generation: generation,
                        state: &state
                    )
                    return nil
                }
                guard state.nextAudioTransmissionIdentifier < UInt64.max else {
                    sequenceError = .sequenceExhausted("audio transmission identifier")
                    return nil
                }
                state.nextAudioTransmissionIdentifier += 1
                let identifier = state.nextAudioTransmissionIdentifier
                state.dispatchedAudioTransmissionIdentifiers.insert(identifier)
                if state.activePath == .relay {
                    state.dispatchedAudioRelayReservations[identifier] =
                        InternetAudioRecordContract.encryptedRecordBytes(
                            forPlaintextBytes: payload.count
                        )
                }
                return (identifier, engineContext)
            }
            if let sequenceError {
                failureTransition = prepareFailureWithinSendGate(sequenceError)
            }
            return claimed
        }
        if let failureTransition {
            performFailureTransition(failureTransition)
            return
        }
        guard let (transmissionIdentifier, engineContext) = transmission else {
            if let nextRecord = rejectedRecovery.nextRecord {
                transmitAudioRecord(nextRecord, generation: generation)
            }
            return
        }
        engine.send(
            payload,
            channel: .audio,
            expectedContext: engineContext
        ) { [weak self] result in
            guard let self else { return }
            var nextRecord: Data?
            var reportedError: InternetTransportError?
            var accountingFailure: InternetTransportError?
            var completionFailureTransition: FailureTransition?
            self.withSendGate {
                self.withLock { state in
                    guard state.dispatchedAudioTransmissionIdentifiers.remove(
                        transmissionIdentifier
                    ) != nil else { return }
                    let relayReservationBytes = state.dispatchedAudioRelayReservations
                        .removeValue(forKey: transmissionIdentifier) ?? 0
                    state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
                        relayReservationBytes
                    )
                    if case .success = result {
                        let (audioBytesSent, audioOverflow) = state.audioBytesSent
                            .addingReportingOverflow(UInt64(payload.count))
                        let (relayBytesSent, relayOverflow) = state.relayBytesSent
                            .addingReportingOverflow(relayReservationBytes)
                        guard !audioOverflow, !relayOverflow else {
                            accountingFailure = .sequenceExhausted("transport byte accounting")
                            return
                        }
                        state.audioBytesSent = audioBytesSent
                        state.relayBytesSent = relayBytesSent
                    }
                    guard state.pipelineGeneration == generation,
                          state.audioInFlight else { return }
                    switch result {
                    case .success:
                        if let pending = state.pendingAudioRecord {
                            nextRecord = pending
                            state.pendingAudioRecord = nil
                        } else {
                            state.audioInFlight = false
                        }
                    case .failure(let error):
                        if let pending = state.pendingAudioRecord {
                            state.droppedAudioRecords += 1
                            self.releaseRelayReservation(
                                for: InternetAudioRecordContract.encryptedRecordBytes(
                                    forPlaintextBytes: pending.count
                                ),
                                state: &state
                            )
                        }
                        state.pendingAudioRecord = nil
                        state.audioInFlight = false
                        state.droppedAudioRecords += 1
                        reportedError = .engineSendFailed(error.localizedDescription)
                    }
                }
                if let accountingFailure {
                    completionFailureTransition = self.prepareFailureWithinSendGate(accountingFailure)
                }
            }
            if let completionFailureTransition {
                self.performFailureTransition(completionFailureTransition)
                return
            }
            if let reportedError { self.onError?(reportedError) }
            if let nextRecord {
                self.transmitAudioRecord(nextRecord, generation: generation)
            }
        }
    }

    private func handleEngineState(_ state: WebRTCEngineConnectionState) {
        let isClosed = withLock { $0.transportState == .closed }
        guard !isClosed else { return }
        switch state {
        case .connecting:
            handleEngineConnecting()
        case .connected(let path):
            if withLock({ $0.pipelineGenerationExhausted }) {
                failTransport(.sequenceExhausted("pipeline generation"), reportError: false)
                return
            }
            let announcedContext = withLock { $0.engineTransmissionContext }
            guard path != .unknown, announcedContext?.path == path else {
                failTransport(
                    .engineSendFailed(
                        "WebRTC reported connected without a matching transmission context and selected ICE candidate pair."
                    ),
                    reportError: false
                )
                return
            }
            let update = withSendGate {
                withLock { state -> (
                    accepted: Bool,
                    changed: Bool,
                    completions: [ControlTransmissionCompletion]
                ) in
                    guard state.transportState != .closed else { return (false, false, []) }
                    if case .failed = state.transportState { return (false, false, []) }
                    guard let engineContext = state.engineTransmissionContext,
                          engineContext.path == path else { return (false, false, []) }
                    var invalidatedCompletions: [ControlTransmissionCompletion] = []
                    if let previousPath = state.activePath, previousPath != path {
                        invalidatedCompletions = invalidatePipeline(state: &state)
                        state.engineTransmissionContext = engineContext
                    }
                    state.activePath = path
                    state.recovery.connected()
                    state.recoveryAttemptAwaitingOutcome = false
                    state.waitingForKeyframe = true
                    let connectedState = InternetTransportState.connected(path)
                    guard state.transportState != connectedState else {
                        return (true, false, invalidatedCompletions)
                    }
                    state.transportState = connectedState
                    return (true, true, invalidatedCompletions)
                }
            }
            guard update.accepted else { return }
            if update.changed { onStateChanged?(.connected(path)) }
            engine.requestMediaKeyframe()
            onKeyframeRequired?()
            completeControlTransmissions(update.completions, with: .notConnected)
        case .disconnected:
            recoverConnectivity()
        case .failed(let reason):
            failTransport(.engineSendFailed(reason), reportError: false)
        case .closed:
            let closeTransition = withSendGate {
                withLock { state -> (
                    changed: Bool,
                    completions: [ControlTransmissionCompletion]
                ) in
                    if case .failed = state.transportState { return (false, []) }
                    guard state.transportState != .closed else { return (false, []) }
                    state.transportState = .closed
                    state.activePath = nil
                    return (true, invalidatePipeline(state: &state))
                }
            }
            closeEngineOnce()
            if closeTransition.changed { onStateChanged?(.closed) }
            completeControlTransmissions(closeTransition.completions, with: .notConnected)
        }
    }

    private func handleNetworkPath(_ path: InternetNetworkPath) {
        let recovery = withSendGate { () -> PreparedRecovery? in
            let action = withLock { state -> NetworkRecoveryAction? in
                guard isConnected(state.transportState) else {
                    state.recovery.observePath(path)
                    return nil
                }
                return state.recovery.pathChanged(
                    path,
                    requiresFreshSession: networkHandoffRecoveryStrategy == .freshSession
                )
            }
            return prepareRecoveryActionWithinSendGate(action)
        }
        performPreparedRecovery(recovery)
    }

    private func handleEngineConnecting() {
        let shouldNotify = withSendGate {
            withLock { state -> Bool in
                guard state.transportState != .closed else { return false }
                if case .failed = state.transportState { return false }
                if case .recovering = state.transportState {
                    state.recoveryAttemptAwaitingOutcome = true
                    return false
                }
                guard state.transportState != .connecting else { return false }
                state.transportState = .connecting
                return true
            }
        }
        if shouldNotify { onStateChanged?(.connecting) }
    }

    private func handleEngineTransmissionContext(
        _ context: WebRTCEngineTransmissionContext?
    ) {
        var didExhaustPipeline = false
        var invalidatedCompletions: [ControlTransmissionCompletion] = []
        withSendGate {
            withLock { state in
                guard state.transportState != .closed else { return }
                if case .failed = state.transportState { return }
                guard state.engineTransmissionContext != context
                        || (context == nil && state.activePath != nil) else { return }
                if state.engineTransmissionContext != nil || state.activePath != nil {
                    invalidatedCompletions = invalidatePipeline(state: &state)
                    didExhaustPipeline = state.pipelineGenerationExhausted
                }
                state.activePath = nil
                state.engineTransmissionContext = context
            }
        }
        completeControlTransmissions(invalidatedCompletions, with: .notConnected)
        if didExhaustPipeline {
            failTransport(.sequenceExhausted("pipeline generation"), reportError: false)
        }
    }

    private func recoverConnectivity() {
        let recovery = withSendGate { () -> PreparedRecovery? in
            let action: NetworkRecoveryAction? = withLock {
                if isConnected($0.transportState) || $0.transportState == .connecting {
                    return $0.recovery.connectivityLost()
                }
                guard case .recovering = $0.transportState,
                      $0.recoveryAttemptAwaitingOutcome else { return nil }
                $0.recoveryAttemptAwaitingOutcome = false
                return $0.recovery.connectivityLost()
            }
            return prepareRecoveryActionWithinSendGate(action)
        }
        performPreparedRecovery(recovery)
    }

    private func prepareRecoveryActionWithinSendGate(
        _ action: NetworkRecoveryAction?
    ) -> PreparedRecovery? {
        switch action {
        case .restartICE:
            return prepareICERestartWithinSendGate().map(PreparedRecovery.iceRestart)
        case .freshSession(let reason):
            return prepareFreshSessionRecoveryWithinSendGate(reason: reason)
        case .fail(let reason):
            return prepareFreshSessionRecoveryWithinSendGate(reason: reason)
        case nil:
            return nil
        }
    }

    private func prepareICERestartWithinSendGate() -> RecoveryTransition? {
        withLock { state -> RecoveryTransition? in
            let canRestart: Bool
            if isConnected(state.transportState) {
                canRestart = true
            } else if state.transportState == .connecting {
                canRestart = true
            } else if case .recovering = state.transportState {
                canRestart = true
            } else {
                canRestart = false
            }
            guard canRestart else { return nil }
            let invalidatedCompletions = invalidatePipeline(state: &state)
            state.activePath = nil
            state.waitingForKeyframe = true
            state.recoveryAttemptAwaitingOutcome = false
            let attempt = state.recovery.attempt
            let recoveringState = InternetTransportState.recovering(attempt: attempt)
            guard state.transportState != recoveringState else {
                return RecoveryTransition(
                    attempt: attempt,
                    changed: false,
                    generation: state.pipelineGeneration,
                    recoveringState: recoveringState,
                    invalidatedControlCompletions: invalidatedCompletions
                )
            }
            state.transportState = recoveringState
            return RecoveryTransition(
                attempt: attempt,
                changed: true,
                generation: state.pipelineGeneration,
                recoveringState: recoveringState,
                invalidatedControlCompletions: invalidatedCompletions
            )
        }
    }

    private func prepareFreshSessionRecoveryWithinSendGate(reason: String) -> PreparedRecovery? {
        guard onFreshSessionRecoveryRequired != nil else {
            return prepareFailureWithinSendGate(
                .engineSendFailed(reason),
                reportError: false
            ).map(PreparedRecovery.failure)
        }
        return withLock { state -> PreparedRecovery? in
            let canRecover: Bool
            if isConnected(state.transportState) {
                canRecover = true
            } else if state.transportState == .connecting {
                canRecover = true
            } else if case .recovering = state.transportState {
                canRecover = true
            } else {
                canRecover = false
            }
            guard canRecover else { return nil }
            let invalidatedCompletions = invalidatePipeline(state: &state)
            state.activePath = nil
            state.waitingForKeyframe = true
            state.recoveryAttemptAwaitingOutcome = false
            let attempt = max(state.recovery.attempt, 1)
            let recoveringState = InternetTransportState.recovering(attempt: attempt)
            let changed = state.transportState != recoveringState
            state.transportState = recoveringState
            return .freshSession(RecoveryTransition(
                attempt: attempt,
                changed: changed,
                generation: state.pipelineGeneration,
                recoveringState: recoveringState,
                invalidatedControlCompletions: invalidatedCompletions
            ))
        }
    }

    private func performPreparedRecovery(_ recovery: PreparedRecovery?) {
        switch recovery {
        case .iceRestart(let transition):
            performPreparedICERestart(transition)
        case .freshSession(let transition):
            performPreparedFreshSessionRecovery(transition)
        case .failure(let transition):
            performFailureTransition(transition)
        case nil:
            break
        }
    }

    private func performPreparedFreshSessionRecovery(_ transition: RecoveryTransition) {
        completeControlTransmissions(
            transition.invalidatedControlCompletions,
            with: .notConnected
        )
        duringRecoveryDecision?()
        guard isCurrentRecovery(transition) else { return }
        duringMediaRecoveryTransition?()
        guard isCurrentRecovery(transition) else { return }
        if transition.changed { onStateChanged?(.recovering(attempt: transition.attempt)) }
        guard isCurrentRecovery(transition), let onFreshSessionRecoveryRequired else { return }
        onFreshSessionRecoveryRequired(transition.attempt)
    }

    private func performPreparedICERestart(_ transition: RecoveryTransition?) {
        guard let transition else { return }
        completeControlTransmissions(
            transition.invalidatedControlCompletions,
            with: .notConnected
        )
        duringRecoveryDecision?()
        guard isCurrentRecovery(transition) else { return }
        duringMediaRecoveryTransition?()
        guard isCurrentRecovery(transition) else { return }
        if transition.changed { onStateChanged?(.recovering(attempt: transition.attempt)) }
        guard isCurrentRecovery(transition) else { return }
        switch recoveryStrategy {
        case .restartICE:
            switch engine.restartICE() {
            case .peerReplacementStarted:
                withLock { $0.iceRestartCount += 1 }
            case .requiresFreshSession(let reason):
                guard let onFreshSessionRecoveryRequired else {
                    failTransport(.engineSendFailed(reason), reportError: false)
                    return
                }
                onFreshSessionRecoveryRequired(transition.attempt)
            case .failed(let reason):
                failTransport(.engineSendFailed(reason), reportError: false)
            }
        case .freshSession:
            guard let onFreshSessionRecoveryRequired else {
                failTransport(
                    .engineSendFailed("Fresh-session recovery was required but no recovery callback was installed."),
                    reportError: false
                )
                return
            }
            onFreshSessionRecoveryRequired(transition.attempt)
        }
    }

    private func isCurrentRecovery(_ transition: RecoveryTransition) -> Bool {
        withSendGate {
            withLock {
                $0.pipelineGeneration == transition.generation
                    && $0.transportState == transition.recoveringState
            }
        }
    }

    private func handleInbound(_ payload: Data, channel: InternetTransportChannel) {
        let maximum = maximumInboundPlaintextBytes(for: channel)
        var failureTransition: FailureTransition?
        var shouldDeliver = false
        withSendGate {
            let acceptsInbound = withLock { state in
                guard isConnected(state.transportState),
                      let activePath = state.activePath,
                      let engineContext = state.engineTransmissionContext else { return false }
                return engineContext.path == activePath
            }
            guard acceptsInbound else { return }
            if payload.isEmpty {
                failureTransition = prepareFailureWithinSendGate(.emptyPayload(channel: channel))
                return
            }
            if payload.count > maximum {
                failureTransition = prepareFailureWithinSendGate(.payloadTooLarge(
                    channel: channel,
                    actual: payload.count,
                    maximum: maximum
                ))
                return
            }
            shouldDeliver = true
        }
        if let failureTransition {
            performFailureTransition(failureTransition)
        } else if shouldDeliver {
            switch channel {
            case .control: onControlReceived?(payload)
            case .media: onMediaReceived?(payload)
            case .audio: onAudioRecordReceived?(payload)
            case .bulk: onBulkRecordReceived?(payload)
            }
        }
    }

    private func maximumInboundPlaintextBytes(for channel: InternetTransportChannel) -> Int {
        switch channel {
        case .control:
            return limits.maximumControlMessageBytes
        case .media:
            return limits.maximumMediaFrameBytes
        case .audio:
            return InternetAudioRecordContract.maximumPlaintextRecordBytes
        case .bulk:
            return InternetBulkRecordContract.maximumPlaintextRecordBytes
        }
    }

    private func handleNetworkQuality(_ sample: InternetNetworkQualitySample) {
        let profile = withLock { _ in adaptivePolicy.observe(sample) }
        if let profile {
            onAdaptiveProfileChanged?(profile)
        }
    }

    func commitAdaptiveProfile(_ profile: AdaptiveMediaProfile) {
        withLock { _ in adaptivePolicy.commit(profile) }
    }

    func rejectAdaptiveProfile(_ profile: AdaptiveMediaProfile) {
        withLock { _ in adaptivePolicy.reject(profile) }
    }

    private func setState(_ state: InternetTransportState) {
        let changed = withSendGate {
            withLock { mutable -> Bool in
                guard mutable.transportState != .closed else { return false }
                if case .failed = mutable.transportState { return false }
                guard mutable.transportState != state else { return false }
                mutable.transportState = state
                return true
            }
        }
        if changed { onStateChanged?(state) }
    }

    private func failTransport(
        _ error: InternetTransportError,
        reportError: Bool = true
    ) {
        let transition = withSendGate {
            prepareFailureWithinSendGate(error, reportError: reportError)
        }
        if let transition { performFailureTransition(transition) }
    }

    private func prepareFailureWithinSendGate(
        _ error: InternetTransportError,
        reportError: Bool = true
    ) -> FailureTransition? {
        let failedState = InternetTransportState.failed(error.localizedDescription)
        var failureGeneration: UInt64 = 0
        var invalidatedCompletions: [ControlTransmissionCompletion] = []
        let changed = withLock { state -> Bool in
            guard state.transportState != .closed else { return false }
            if case .failed = state.transportState { return false }
            state.transportState = failedState
            state.activePath = nil
            invalidatedCompletions = invalidatePipeline(state: &state)
            failureGeneration = state.pipelineGeneration
            return true
        }
        guard changed else { return nil }
        return FailureTransition(
            failedState: failedState,
            generation: failureGeneration,
            error: error,
            reportError: reportError,
            invalidatedControlCompletions: invalidatedCompletions
        )
    }

    private func performFailureTransition(_ transition: FailureTransition) {
        completeControlTransmissions(
            transition.invalidatedControlCompletions,
            with: .notConnected
        )
        beforeFailureSideEffects?()
        closeEngineOnce()
        let shouldPublish = withSendGate {
            let isCurrent = withLock {
                $0.pipelineGeneration == transition.generation
                    && $0.transportState == transition.failedState
            }
            return isCurrent
        }
        guard shouldPublish else { return }
        onStateChanged?(transition.failedState)
        if transition.reportError { onError?(transition.error) }
    }

    private func closeEngineOnce() {
        engineLifecycleGate.lock()
        defer { engineLifecycleGate.unlock() }
        guard !engineCloseInvoked else { return }
        engineCloseInvoked = true
        engine.close()
    }

    private func invalidatePipeline(
        state: inout MutableState
    ) -> [ControlTransmissionCompletion] {
        let controlCompletions = state.controlCompletions.values.sorted {
            $0.identifier < $1.identifier
        }
        state.controlCompletions.removeAll(keepingCapacity: true)
        if state.pipelineGeneration < UInt64.max {
            state.pipelineGeneration += 1
        } else {
            state.pipelineGenerationExhausted = true
        }
        state.engineTransmissionContext = nil
        state.controlQueue.removeAll()
        state.bufferedControlBytes = 0
        if state.mediaInFlight { state.droppedMediaFrames += 1 }
        if state.pendingMediaFrame != nil { state.droppedMediaFrames += 1 }
        state.pendingMediaFrame = nil
        if state.audioInFlight { state.droppedAudioRecords += 1 }
        if state.pendingAudioRecord != nil { state.droppedAudioRecords += 1 }
        state.pendingAudioRecord = nil
        state.bulkQueue.removeAll()
        state.bufferedBulkBytes = 0
        state.controlInFlight = false
        state.activeControlTransmissionIdentifier = nil
        state.mediaInFlight = false
        state.audioInFlight = false
        state.bulkInFlight = false
        state.activeBulkTransmissionIdentifier = nil
        state.recoveryAttemptAwaitingOutcome = false
        // The engine port still owns dispatched-send accounting until its
        // exactly-once completion reports whether those network bytes drained.
        state.relayBytesReserved =
            state.dispatchedControlRelayReservations.values.reduce(0, +)
            + state.dispatchedMediaRelayReservations.values.reduce(0, +)
            + state.dispatchedAudioRelayReservations.values.reduce(0, +)
            + state.dispatchedBulkRelayReservations.values.reduce(0, +)
        return controlCompletions
    }

    private func recoverRejectedControlSend(
        _ transmission: ControlTransmission,
        state: inout MutableState
    ) -> [ControlTransmissionCompletion] {
        // A generation change already invalidated the old queue and released its reservations.
        guard state.pipelineGeneration == transmission.generation,
              state.controlInFlight else { return [] }
        let controlCompletions = state.controlCompletions.values.sorted {
            $0.identifier < $1.identifier
        }
        state.controlCompletions.removeAll(keepingCapacity: true)
        let queuedPayloadBytes = state.controlQueue.payloadBytes()
        let queuedRelayReservationBytes = state.controlQueue.relayReservationBytes()
        state.bufferedControlBytes = max(
            0,
            state.bufferedControlBytes - transmission.payload.count - queuedPayloadBytes
        )
        state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
            transmission.relayReservationBytes.addingClamped(queuedRelayReservationBytes)
        )
        state.controlQueue.removeAll()
        state.controlInFlight = false
        state.activeControlTransmissionIdentifier = nil
        return controlCompletions
    }

    private func recoverRejectedBulkSend(
        _ transmission: BulkTransmission,
        state: inout MutableState
    ) {
        // A generation change already invalidated the old queue and released its reservations.
        guard state.pipelineGeneration == transmission.generation,
              state.bulkInFlight else { return }
        let queuedPayloadBytes = state.bulkQueue.payloadBytes()
        let queuedRelayReservationBytes = state.bulkQueue.relayReservationBytes()
        state.bufferedBulkBytes = max(
            0,
            state.bufferedBulkBytes - transmission.payload.count - queuedPayloadBytes
        )
        state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(
            transmission.relayReservationBytes.addingClamped(queuedRelayReservationBytes)
        )
        state.bulkQueue.removeAll()
        state.bulkInFlight = false
        state.activeBulkTransmissionIdentifier = nil
    }

    private func completeControlTransmissions(
        _ completions: [ControlTransmissionCompletion],
        with error: InternetTransportError
    ) {
        for completion in completions {
            completion.complete(.failure(error))
        }
    }

    private func isConnected(_ state: InternetTransportState) -> Bool {
        if case .connected = state { return true }
        return false
    }

    private func releaseRelayReservation(for byteCount: UInt64, state: inout MutableState) {
        guard state.activePath == .relay else { return }
        state.relayBytesReserved = state.relayBytesReserved.subtractingClamped(byteCount)
    }

    private func reserveRelayBytes(
        _ byteCount: UInt64,
        replacing replacedBytes: UInt64 = 0,
        state: inout MutableState
    ) -> Bool {
        guard state.activePath == .relay else { return true }
        let retainedReservation = state.relayBytesReserved.subtractingClamped(replacedBytes)
        guard relayReservationFits(
            sent: state.relayBytesSent,
            reserved: retainedReservation,
            additional: byteCount
        ) else {
            return false
        }
        state.relayBytesReserved = retainedReservation.addingClamped(byteCount)
        return true
    }

    private func relayReservationFits(
        sent: UInt64,
        reserved: UInt64,
        additional: UInt64
    ) -> Bool {
        let (committed, committedOverflow) = sent.addingReportingOverflow(reserved)
        guard !committedOverflow else { return false }
        let (projected, projectedOverflow) = committed.addingReportingOverflow(additional)
        return !projectedOverflow && projected <= limits.maximumRelayBytesPerSession
    }

    private struct RejectedMediaSendRecovery {
        static let none = RejectedMediaSendRecovery(nextFrame: nil, shouldRequestKeyframe: false)

        let nextFrame: EncodedInternetFrame?
        let shouldRequestKeyframe: Bool
    }

    private struct RejectedAudioSendRecovery {
        static let none = RejectedAudioSendRecovery(nextRecord: nil)

        let nextRecord: Data?
    }

    private func recoverRejectedMediaSend(
        _ frame: EncodedInternetFrame,
        recordIndex: Int,
        generation: UInt64,
        state: inout MutableState
    ) -> RejectedMediaSendRecovery {
        // A generation change already invalidated and released the old pipeline.
        guard state.pipelineGeneration == generation else { return .none }

        if state.mediaInFlight {
            let remainingEncryptedBytes = frame.records
                .dropFirst(recordIndex)
                .reduce(UInt64(0)) {
                    $0 + InternetMediaRecordContract.encryptedRecordBytes(
                        forPlaintextBytes: $1.count
                    )
                }
            releaseRelayReservation(for: remainingEncryptedBytes, state: &state)
            state.droppedMediaFrames += 1
        }
        state.waitingForKeyframe = true

        if isConnected(state.transportState),
           let pending = state.pendingMediaFrame,
           pending.isKeyframe {
            state.pendingMediaFrame = nil
            state.mediaInFlight = true
            state.waitingForKeyframe = false
            return RejectedMediaSendRecovery(
                nextFrame: pending,
                shouldRequestKeyframe: false
            )
        }

        if let pending = state.pendingMediaFrame {
            releaseRelayReservation(for: pending.totalEncryptedRecordBytes, state: &state)
            state.droppedMediaFrames += 1
        }
        state.pendingMediaFrame = nil
        state.mediaInFlight = false
        return RejectedMediaSendRecovery(
            nextFrame: nil,
            shouldRequestKeyframe: isConnected(state.transportState)
        )
    }

    private func recoverRejectedAudioSend(
        _ payload: Data,
        generation: UInt64,
        state: inout MutableState
    ) -> RejectedAudioSendRecovery {
        // A generation change already invalidated and released the old pipeline.
        guard state.pipelineGeneration == generation else { return .none }

        if state.audioInFlight {
            releaseRelayReservation(
                for: InternetAudioRecordContract.encryptedRecordBytes(
                    forPlaintextBytes: payload.count
                ),
                state: &state
            )
            state.droppedAudioRecords += 1
        }

        if isConnected(state.transportState), let pending = state.pendingAudioRecord {
            state.pendingAudioRecord = nil
            state.audioInFlight = true
            return RejectedAudioSendRecovery(nextRecord: pending)
        }

        if let pending = state.pendingAudioRecord {
            releaseRelayReservation(
                for: InternetAudioRecordContract.encryptedRecordBytes(
                    forPlaintextBytes: pending.count
                ),
                state: &state
            )
            state.droppedAudioRecords += 1
        }
        state.pendingAudioRecord = nil
        state.audioInFlight = false
        return .none
    }

    @discardableResult
    private func withSendGate<T>(_ operation: () -> T) -> T {
        sendGate.lock()
        defer { sendGate.unlock() }
        return operation()
    }

    @discardableResult
    private func withLock<T>(_ operation: (inout MutableState) -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation(&mutableState)
    }
}

private final class EngineSendCompletionHandoff {
    private let lock = NSLock()
    private var engineSendReturned = false
    private var callbackReceived = false
    private var pendingResult: Result<Void, Error>?

    /// Returns true when the caller must process the completion immediately.
    func receive(_ result: Result<Void, Error>) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !callbackReceived else { return false }
        callbackReceived = true
        guard !engineSendReturned else { return true }
        pendingResult = result
        return false
    }

    func markEngineSendReturned() -> Result<Void, Error>? {
        lock.lock()
        defer { lock.unlock() }
        engineSendReturned = true
        defer { pendingResult = nil }
        return pendingResult
    }
}

private extension UInt64 {
    func addingClamped(_ value: UInt64) -> UInt64 {
        let (result, overflow) = addingReportingOverflow(value)
        return overflow ? UInt64.max : result
    }

    func subtractingClamped(_ value: UInt64) -> UInt64 {
        value > self ? 0 : self - value
    }
}
