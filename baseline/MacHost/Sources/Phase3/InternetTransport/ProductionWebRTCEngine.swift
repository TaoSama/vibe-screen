import Foundation
import Network
import WebRTC

final class ProductionWebRTCEngine: NSObject, WebRTCEnginePort {
    private enum AdapterError: Error, LocalizedError {
        case alreadyStarted
        case closed
        case failed
        case peerCreationFailed
        case channelCreationFailed(String)
        case invalidChannelConfiguration(String)
        case deadlineSchedulingFailed
        case channelUnavailable(InternetTransportChannel)
        case channelNotOpen(InternetTransportChannel)
        case sendRejected(InternetTransportChannel)
        case staleTransmissionContext(InternetTransportChannel)
        case sendAlreadyPending(InternetTransportChannel)
        case sdkBacklogExceeded(InternetTransportChannel, UInt64)
        case closedBeforeDrain(InternetTransportChannel)

        var errorDescription: String? {
            switch self {
            case .alreadyStarted: return "The WebRTC engine is already started."
            case .closed: return "The WebRTC engine is closed and cannot be restarted."
            case .failed: return "The WebRTC engine failed and cannot be restarted."
            case .peerCreationFailed: return "libwebrtc could not create a peer connection."
            case .channelCreationFailed(let label): return "libwebrtc could not create data channel \(label)."
            case .invalidChannelConfiguration(let reason): return reason
            case .deadlineSchedulingFailed: return "The WebRTC connection deadline could not be scheduled."
            case .channelUnavailable(let channel): return "The \(channel) data channel is unavailable."
            case .channelNotOpen(let channel): return "The \(channel) data channel is not open."
            case .sendRejected(let channel): return "libwebrtc rejected a \(channel) data message."
            case .staleTransmissionContext(let channel):
                return "The \(channel) data message belongs to an inactive WebRTC transmission context."
            case .sendAlreadyPending(let channel):
                return "A \(channel) data message is still buffered by libwebrtc."
            case .sdkBacklogExceeded(let channel, let maximum):
                return "The \(channel) libwebrtc buffer exceeded \(maximum) bytes."
            case .closedBeforeDrain(let channel):
                return "The \(channel) data channel closed before buffered data drained."
            }
        }
    }

    private struct PendingSDKSend {
        let baselineBufferedAmount: UInt64
        let completion: (Result<Void, Error>) -> Void
    }

    struct DataChannelClosureSelfTestReport {
        let invalidatedConnectedState: Bool
        let pendingCompletionsFailedExactlyOnce: Bool
        let lateInboundRejected: Bool
        let lateDrainRejected: Bool
        let staleClosureIgnored: Bool
        let selectedDeterministicTerminalEvent: Bool
    }

    private struct UnexpectedDataChannelClosure {
        let invalidatedTransmissionContext: Bool
        let pendingSends: [(InternetTransportChannel, PendingSDKSend)]
        let connectionState: WebRTCEngineConnectionState
    }

    private struct SignaledCandidateKey: Hashable {
        let sdp: String
        let mid: String?
        let lineIndex: Int32
        let generation: UInt64
    }

    private struct PendingSignaledCandidate {
        let key: SignaledCandidateKey
        let candidate: RTCIceCandidate
    }

    private final class PeerDelegateProxy: NSObject, RTCPeerConnectionDelegate {
        private weak var owner: ProductionWebRTCEngine?
        let generation: UInt64

        init(owner: ProductionWebRTCEngine, generation: UInt64) {
            self.owner = owner
            self.generation = generation
        }

        func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
        func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
        func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
        func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}

        func peerConnection(
            _ peerConnection: RTCPeerConnection,
            didChange newState: RTCIceConnectionState
        ) {
            owner?.handleICEConnectionState(
                newState,
                peerConnection: peerConnection,
                delegateGeneration: generation
            )
        }

        func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
        func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

        func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {
            owner?.handleGeneratedCandidate(
                candidate,
                peerConnection: peerConnection,
                delegateGeneration: generation
            )
        }

        func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
            owner?.handleOpenedDataChannel(
                dataChannel,
                peerConnection: peerConnection,
                delegateGeneration: generation
            )
        }

        func peerConnection(
            _ peerConnection: RTCPeerConnection,
            didChange newState: RTCPeerConnectionState
        ) {
            owner?.handlePeerConnectionState(
                newState,
                peerConnection: peerConnection,
                delegateGeneration: generation
            )
        }
    }

    private final class DataChannelDelegateProxy: NSObject, RTCDataChannelDelegate {
        private weak var owner: ProductionWebRTCEngine?
        let kind: InternetTransportChannel
        let generation: UInt64

        init(
            owner: ProductionWebRTCEngine,
            kind: InternetTransportChannel,
            generation: UInt64
        ) {
            self.owner = owner
            self.kind = kind
            self.generation = generation
        }

        func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {
            owner?.handleDataChannelStateChange(
                dataChannel,
                kind: kind,
                generation: generation
            )
        }

        func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
            owner?.handleDataChannelMessage(
                buffer,
                dataChannel: dataChannel,
                kind: kind,
                generation: generation
            )
        }

        func dataChannel(_ dataChannel: RTCDataChannel, didChangeBufferedAmount amount: UInt64) {
            owner?.handleDataChannelBufferedAmountChange(
                dataChannel,
                kind: kind,
                generation: generation
            )
        }
    }

    private static let initializeWebRTC: Void = {
        RTCInitializeSSL()
    }()
    private static let candidatePairResolutionTimeoutSeconds = 5
    private static let connectionAttemptTimeoutSeconds = 10
    private static let transmissionEpochExhaustedReason = "WebRTC transmission epoch was exhausted."
    private static let freshSignalingSessionRequiredReason =
        "This signaling session cannot replace a PeerConnection; request a fresh signaling session."

    private let factory: RTCPeerConnectionFactory
    private let signaling: WebRTCSignalingClientPort
    private let queue = DispatchQueue(label: "dev.vibescreen.webrtc.peer")
    private let queueKey = DispatchSpecificKey<UInt8>()
    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "dev.vibescreen.webrtc.path")
    private var callbacks: WebRTCEngineCallbacks?
    private var peerConnection: RTCPeerConnection?
    private var peerDelegateProxy: PeerDelegateProxy?
    private var peerDelegateGenerationState = WebRTCPeerConnectionDelegateGenerationState()
    private var channelByKind: [InternetTransportChannel: RTCDataChannel] = [:]
    private var channelDelegateByKind: [InternetTransportChannel: DataChannelDelegateProxy] = [:]
    private var channelConfigurations: [WebRTCDataChannelConfiguration] = []
    private var pendingSDKSendByKind: [InternetTransportChannel: PendingSDKSend] = [:]
    private var kindByLabel: [String: InternetTransportChannel] = [:]
    private var pendingRemoteCandidates: [RTCIceCandidate] = []
    private var pendingLocalCandidates: [RTCIceCandidate] = []
    private var futureRemoteCandidatesByGeneration: [UInt64: [PendingSignaledCandidate]] = [:]
    private var acceptedRemoteDescriptionSignal: WebRTCSignal?
    private var localDescriptionGenerationInFlight: UInt64?
    private var remoteCandidateKeys: Set<SignaledCandidateKey> = []
    private var localCandidateKeys: Set<SignaledCandidateKey> = []
    private var localDescriptionPublished = false
    private var configuration: WebRTCTransportConfiguration?
    private var statsTimer: DispatchSourceTimer?
    private var candidatePairResolutionTimer: DispatchSourceTimer?
    private var connectionAttemptTimer: DispatchSourceTimer?
    private var candidatePairResolutionTimeoutState = WebRTCCandidatePairResolutionTimeoutState()
    private var connectionAttemptDeadlineState = WebRTCConnectionAttemptDeadlineState()
    private var statisticsRequestOrderingState = WebRTCStatisticsRequestOrderingState()
    private var selectedPath: InternetPathKind = .unknown
    private var selectedCandidatePair: WebRTCSelectedCandidatePair?
    private var selectedCandidatePairStatisticsID: String?
    private var didPublishConnected = false
    private var isClosed = false
    private var hasStarted = false
    private var startupFailed = false
    private var transmissionState = WebRTCEngineTransmissionEpochState()
    private var lastNetworkPathFingerprint: String?

    init(
        factory: RTCPeerConnectionFactory? = nil,
        signaling: WebRTCSignalingClientPort = HTTPSignalingClient()
    ) {
        _ = Self.initializeWebRTC
        self.factory = factory ?? RTCPeerConnectionFactory()
        self.signaling = signaling
        super.init()
        queue.setSpecific(key: queueKey, value: 1)
        signaling.onSignal = { [weak self] signal in self?.queue.async { self?.handle(signal) } }
        signaling.onFailure = { [weak self] error in
            self?.queue.async { self?.fail("Signaling failed: \(error.localizedDescription)") }
        }
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        performSync { self.callbacks = callbacks }
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        try performSync {
            guard !startupFailed else { throw AdapterError.failed }
            guard !isClosed else { throw AdapterError.closed }
            guard !hasStarted else { throw AdapterError.alreadyStarted }
            guard configuration.signaling != nil else { throw WebRTCSignalingError.missingConfiguration }
            hasStarted = true
            localDescriptionPublished = false
            pendingLocalCandidates.removeAll()
            pendingRemoteCandidates.removeAll()
            acceptedRemoteDescriptionSignal = nil
            localDescriptionGenerationInFlight = nil
            remoteCandidateKeys.removeAll()
            localCandidateKeys.removeAll()
            futureRemoteCandidatesByGeneration.removeAll()
            pendingSDKSendByKind.removeAll()
            self.configuration = configuration
            selectedPath = .unknown
            selectedCandidatePair = nil
            selectedCandidatePairStatisticsID = nil
            candidatePairResolutionTimeoutState.cancel()
            connectionAttemptDeadlineState.cancel()
            statisticsRequestOrderingState.reset()
            didPublishConnected = false
            peerDelegateGenerationState.reset()
            transmissionState.reset()
            lastNetworkPathFingerprint = nil
            channelConfigurations = channels
            do {
                kindByLabel = try validatedChannelKindMapping(channels)
                try createPeerConnection()
                try signaling.connect(configuration: configuration)
                guard startConnectionAttemptDeadline(attemptKind: .initial) else {
                    throw AdapterError.deadlineSchedulingFailed
                }
                startPathMonitor()
            } catch {
                stopConnectionAttemptDeadline()
                stopCandidatePairResolutionTimeout()
                stopStats()
                teardownPeerConnection()
                signaling.close()
                self.configuration = nil
                channelConfigurations.removeAll()
                kindByLabel.removeAll()
                startupFailed = true
                isClosed = true
                throw error
            }
            callbacks?.connectionStateChanged(.connecting)
        }
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        queue.async { [weak self] in
            guard let self, let dataChannel = self.channelByKind[channel] else {
                completion(.failure(AdapterError.channelUnavailable(channel)))
                return
            }
            guard !self.isClosed,
                  self.didPublishConnected,
                  self.transmissionState.acceptsSend(expectedContext: expectedContext) else {
                completion(.failure(AdapterError.staleTransmissionContext(channel)))
                return
            }
            guard dataChannel.readyState == .open else {
                completion(.failure(AdapterError.channelNotOpen(channel)))
                return
            }
            guard self.pendingSDKSendByKind[channel] == nil else {
                completion(.failure(AdapterError.sendAlreadyPending(channel)))
                return
            }
            let bufferedBefore = dataChannel.bufferedAmount
            let maximumBuffered = self.maximumBufferedAmount(for: channel)
            let payloadBytes = UInt64(payload.count)
            guard WebRTCDataChannelBackpressurePolicy.canAdmit(
                bufferedAmount: bufferedBefore,
                payloadBytes: payloadBytes,
                maximumBufferedAmount: maximumBuffered
            ) else {
                completion(.failure(AdapterError.sdkBacklogExceeded(channel, maximumBuffered)))
                return
            }
            self.pendingSDKSendByKind[channel] = PendingSDKSend(
                baselineBufferedAmount: bufferedBefore,
                completion: completion
            )
            let accepted = dataChannel.sendData(RTCDataBuffer(data: payload, isBinary: true))
            guard accepted else {
                self.pendingSDKSendByKind.removeValue(forKey: channel)
                completion(.failure(AdapterError.sendRejected(channel)))
                return
            }
            self.completeSDKSendIfDrained(channel: channel, currentBufferedAmount: dataChannel.bufferedAmount)
        }
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        performSync {
            guard peerConnection != nil else {
                return .failed("No active PeerConnection is available for recovery.")
            }
            guard signaling.supportsNegotiationGeneration,
                  configuration?.signaling?.role == .offerer else {
                guard quiesceForFreshSignalingSession() else {
                    return .failed("The current PeerConnection could not be retired safely.")
                }
                return .requiresFreshSession(Self.freshSignalingSessionRequiredReason)
            }
            guard replacePeerConnection(attemptKind: .localRecovery) else {
                return .failed("PeerConnection replacement failed.")
            }
            createAndSendOffer()
            return .peerReplacementStarted
        }
    }

    func requestMediaKeyframe() {
        // Encoded media is carried over the unreliable data channel. The host
        // encoder owns keyframe production through WebRTCInternetTransport's callback.
    }

    func close() {
        performSync {
            guard !isClosed else { return }
            markPeerDisconnected()
            isClosed = true
            stopConnectionAttemptDeadline()
            stopCandidatePairResolutionTimeout()
            stopStats()
            pathMonitor.cancel()
            teardownPeerConnection()
            signaling.close()
            callbacks?.connectionStateChanged(.closed)
        }
    }

    private func install(
        channel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) -> Bool {
        if let existing = channelByKind[kind] {
            if existing === channel { return true }
            channel.delegate = nil
            channel.close()
            fail("Duplicate \(kind) data channel was rejected.")
            return false
        }
        let delegate = DataChannelDelegateProxy(
            owner: self,
            kind: kind,
            generation: generation
        )
        channel.delegate = delegate
        channelByKind[kind] = channel
        channelDelegateByKind[kind] = delegate
        return true
    }

    private func createPeerConnection() throws {
        guard let configuration else { throw AdapterError.peerCreationFailed }
        let rtcConfiguration = RTCConfiguration()
        rtcConfiguration.sdpSemantics = .unifiedPlan
        rtcConfiguration.continualGatheringPolicy = .gatherContinually
        rtcConfiguration.iceTransportPolicy = configuration.forceRelay ? .relay : .all
        rtcConfiguration.iceServers = configuration.iceServers.map {
            RTCIceServer(
                urlStrings: $0.urls.map(\.absoluteString),
                username: $0.username,
                credential: $0.credential
            )
        }
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: nil,
            optionalConstraints: ["DtlsSrtpKeyAgreement": "true"]
        )
        let generation = peerDelegateGenerationState.currentGeneration
        let peerDelegate = PeerDelegateProxy(owner: self, generation: generation)
        peerDelegateProxy = peerDelegate
        guard let peer = factory.peerConnection(
            with: rtcConfiguration,
            constraints: constraints,
            delegate: peerDelegate
        ) else {
            peerDelegateProxy = nil
            throw AdapterError.peerCreationFailed
        }
        peerConnection = peer
        if configuration.signaling?.role == .offerer {
            for descriptor in channelConfigurations {
                let rtcDescriptor = RTCDataChannelConfiguration()
                rtcDescriptor.isOrdered = descriptor.isOrdered
                rtcDescriptor.maxRetransmits = descriptor.maximumRetransmits.map(Int32.init) ?? -1
                guard let channel = peer.dataChannel(
                    forLabel: descriptor.label,
                    configuration: rtcDescriptor
                ), let kind = kindByLabel[descriptor.label] else {
                    teardownPeerConnection()
                    throw AdapterError.channelCreationFailed(descriptor.label)
                }
                guard install(channel: channel, kind: kind, generation: generation) else {
                    teardownPeerConnection()
                    throw AdapterError.channelCreationFailed(descriptor.label)
                }
            }
        }
    }

    private func replacePeerConnection(
        attemptKind: WebRTCPeerConnectionAttemptKind
    ) -> Bool {
        guard let replacementGeneration = peerDelegateGenerationState.beginRestart() else {
            fail("WebRTC peer generation was exhausted.")
            return false
        }
        let bufferedFutureCandidates = futureRemoteCandidatesByGeneration.removeValue(
            forKey: replacementGeneration
        ) ?? []
        futureRemoteCandidatesByGeneration.removeAll()
        stopConnectionAttemptDeadline()
        stopCandidatePairResolutionTimeout()
        stopStats()
        guard beginRestartTransmissionEpoch() else { return false }
        selectedPath = .unknown
        selectedCandidatePair = nil
        selectedCandidatePairStatisticsID = nil
        didPublishConnected = false
        resetNegotiationState()
        statisticsRequestOrderingState.reset()
        teardownPeerConnection()
        guard !isClosed else { return false }
        do {
            try createPeerConnection()
        } catch {
            fail("PeerConnection replacement failed: \(error.localizedDescription)")
            return false
        }
        pendingRemoteCandidates = bufferedFutureCandidates.map(\.candidate)
        remoteCandidateKeys.formUnion(bufferedFutureCandidates.map(\.key))
        guard startConnectionAttemptDeadline(attemptKind: attemptKind) else {
            fail("WebRTC connection deadline sequence was exhausted.")
            return false
        }
        callbacks?.connectionStateChanged(.connecting)
        return true
    }

    private func quiesceForFreshSignalingSession() -> Bool {
        guard peerDelegateGenerationState.beginRestart() != nil else {
            fail("WebRTC peer generation was exhausted.")
            return false
        }
        stopConnectionAttemptDeadline()
        stopCandidatePairResolutionTimeout()
        stopStats()
        guard beginRestartTransmissionEpoch() else { return false }
        selectedPath = .unknown
        selectedCandidatePair = nil
        selectedCandidatePairStatisticsID = nil
        didPublishConnected = false
        resetNegotiationState()
        futureRemoteCandidatesByGeneration.removeAll()
        isClosed = true
        pathMonitor.cancel()
        teardownPeerConnection()
        signaling.close()
        return true
    }

    private func teardownPeerConnection() {
        let pendingSends = pendingSDKSendByKind
        pendingSDKSendByKind.removeAll()
        channelByKind.values.forEach {
            $0.delegate = nil
            $0.close()
        }
        channelByKind.removeAll()
        channelDelegateByKind.removeAll()
        pendingLocalCandidates.removeAll()
        pendingRemoteCandidates.removeAll()
        peerConnection?.delegate = nil
        peerConnection?.close()
        peerConnection = nil
        peerDelegateProxy = nil
        for (channel, send) in pendingSends {
            send.completion(.failure(AdapterError.closedBeforeDrain(channel)))
        }
    }

    private func resetNegotiationState() {
        localDescriptionPublished = false
        acceptedRemoteDescriptionSignal = nil
        localDescriptionGenerationInFlight = nil
        remoteCandidateKeys.removeAll()
        localCandidateKeys.removeAll()
        pendingLocalCandidates.removeAll()
        pendingRemoteCandidates.removeAll()
    }

    private func validatedChannelKindMapping(
        _ channels: [WebRTCDataChannelConfiguration]
    ) throws -> [String: InternetTransportChannel] {
        guard channels.count == InternetTransportChannel.allCases.count else {
            throw AdapterError.invalidChannelConfiguration(
                "Production WebRTC requires exactly one control and one media data-channel descriptor."
            )
        }
        var mapping: [String: InternetTransportChannel] = [:]
        var assignedKinds: [InternetTransportChannel] = []
        for descriptor in channels {
            guard mapping[descriptor.label] == nil,
                  let kind = InternetTransportChannel.allCases.first(where: {
                      $0.dataChannelConfiguration.label == descriptor.label
                  }),
                  !assignedKinds.contains(kind) else {
                throw AdapterError.invalidChannelConfiguration(
                    "Production WebRTC data-channel descriptors must have unique control and media labels."
                )
            }
            mapping[descriptor.label] = kind
            assignedKinds.append(kind)
        }
        return mapping
    }

    private var currentTransmissionContext: WebRTCEngineTransmissionContext? {
        transmissionState.currentContext
    }

    private func invalidateTransmissionContext() {
        if transmissionState.invalidateContext() {
            callbacks?.transmissionContextChanged(nil)
        }
        if transmissionState.isExhausted {
            fail(Self.transmissionEpochExhaustedReason)
        }
    }

    private func beginRestartTransmissionEpoch() -> Bool {
        if transmissionState.beginRestart() {
            callbacks?.transmissionContextChanged(nil)
        }
        guard !transmissionState.isExhausted else {
            fail(Self.transmissionEpochExhaustedReason)
            return false
        }
        return true
    }

    @discardableResult
    private func markPeerDisconnected() -> Bool {
        if transmissionState.markPeerDisconnected() {
            callbacks?.transmissionContextChanged(nil)
        }
        return !transmissionState.isExhausted
    }

    private func establishTransmissionContext(
        path: InternetPathKind
    ) -> WebRTCEngineTransmissionContext? {
        guard let update = transmissionState.selectPath(path) else {
            if transmissionState.isExhausted {
                fail(Self.transmissionEpochExhaustedReason)
            }
            return nil
        }
        if update.invalidatedPriorContext {
            callbacks?.transmissionContextChanged(nil)
        }
        callbacks?.transmissionContextChanged(update.context)
        return update.context
    }

    private func maximumBufferedAmount(for channel: InternetTransportChannel) -> UInt64 {
        switch channel {
        case .control:
            return UInt64(
                InternetTransportLimits.standard.maximumBufferedControlBytes
                    + PlatformSessionPacketCipher.recordOverhead
            )
        case .media:
            return UInt64(InternetMediaRecordContract.maximumEncryptedRecordBytes)
        }
    }

    private func completeSDKSendIfDrained(
        channel: InternetTransportChannel,
        currentBufferedAmount: UInt64
    ) {
        guard let pending = pendingSDKSendByKind[channel],
              WebRTCDataChannelBackpressurePolicy.hasDrained(
                currentBufferedAmount: currentBufferedAmount,
                baselineBufferedAmount: pending.baselineBufferedAmount
              ) else { return }
        pendingSDKSendByKind.removeValue(forKey: channel)
        pending.completion(.success(()))
    }

    private func failPendingSDKSends() {
        let pending = pendingSDKSendByKind
        pendingSDKSendByKind.removeAll()
        for (channel, send) in pending {
            send.completion(.failure(AdapterError.closedBeforeDrain(channel)))
        }
    }

    private func prepareUnexpectedDataChannelClosure(
        _ dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) -> UnexpectedDataChannelClosure? {
        guard acceptsDataChannelEvent(
            dataChannel: dataChannel,
            kind: kind,
            generation: generation
        ) else { return nil }
        dataChannel.delegate = nil
        channelByKind.removeValue(forKey: kind)
        channelDelegateByKind.removeValue(forKey: kind)
        let invalidatedTransmissionContext = transmissionState.markPeerDisconnected()
        didPublishConnected = false
        stopConnectionAttemptDeadline()
        stopCandidatePairResolutionTimeout()
        stopStats()
        selectedPath = .unknown
        selectedCandidatePair = nil
        selectedCandidatePairStatisticsID = nil
        let pendingSends = pendingSDKSendByKind.map { ($0.key, $0.value) }
        pendingSDKSendByKind.removeAll()
        return UnexpectedDataChannelClosure(
            invalidatedTransmissionContext: invalidatedTransmissionContext,
            pendingSends: pendingSends,
            connectionState: .disconnected
        )
    }

    private func performUnexpectedDataChannelClosure(
        _ transition: UnexpectedDataChannelClosure
    ) {
        if transition.invalidatedTransmissionContext {
            callbacks?.transmissionContextChanged(nil)
        }
        for (channel, pending) in transition.pendingSends {
            pending.completion(.failure(AdapterError.closedBeforeDrain(channel)))
        }
        callbacks?.connectionStateChanged(transition.connectionState)
    }

    func runDataChannelClosureSelfTest(
        kind: InternetTransportChannel,
        simulatePreConnection: Bool = false
    ) -> DataChannelClosureSelfTestReport? {
        performSync {
            guard didPublishConnected,
                  let dataChannel = channelByKind[kind] else { return nil }
            let generation = peerDelegateGenerationState.currentGeneration
            if simulatePreConnection {
                didPublishConnected = false
                transmissionState.reset()
            }
            var completionCounts: [InternetTransportChannel: Int] = [:]
            var allCompletionsFailed = true
            for pendingKind in InternetTransportChannel.allCases {
                pendingSDKSendByKind[pendingKind] = PendingSDKSend(
                    baselineBufferedAmount: 0,
                    completion: { result in
                        completionCounts[pendingKind, default: 0] += 1
                        if case .success = result { allCompletionsFailed = false }
                    }
                )
            }
            let staleGeneration = generation == UInt64.max ? generation - 1 : generation + 1
            let staleGenerationIgnored = prepareUnexpectedDataChannelClosure(
                dataChannel,
                kind: kind,
                generation: staleGeneration
            ) == nil
            guard let transition = prepareUnexpectedDataChannelClosure(
                dataChannel,
                kind: kind,
                generation: generation
            ) else { return nil }
            performUnexpectedDataChannelClosure(transition)
            let staleChannelIgnored = prepareUnexpectedDataChannelClosure(
                dataChannel,
                kind: kind,
                generation: generation
            ) == nil
            let lateInboundRejected = InternetTransportChannel.allCases.allSatisfy { candidateKind in
                let candidate = candidateKind == kind ? dataChannel : channelByKind[candidateKind]
                guard let candidate else { return true }
                return !acceptsInboundDataChannelEvent(
                    dataChannel: candidate,
                    kind: candidateKind,
                    generation: generation
                )
            }
            let lateDrainRejected = InternetTransportChannel.allCases.allSatisfy { candidateKind in
                let candidate = candidateKind == kind ? dataChannel : channelByKind[candidateKind]
                guard let candidate else { return true }
                return !acceptsDataChannelDrainEvent(
                    dataChannel: candidate,
                    kind: candidateKind,
                    generation: generation
                )
            }
            return DataChannelClosureSelfTestReport(
                invalidatedConnectedState: !didPublishConnected
                    && !transmissionState.peerIsConnected
                    && currentTransmissionContext == nil,
                pendingCompletionsFailedExactlyOnce: allCompletionsFailed
                    && InternetTransportChannel.allCases.allSatisfy {
                        completionCounts[$0] == 1
                    },
                lateInboundRejected: lateInboundRejected,
                lateDrainRejected: lateDrainRejected,
                staleClosureIgnored: staleGenerationIgnored && staleChannelIgnored,
                selectedDeterministicTerminalEvent: transition.connectionState == .disconnected
            )
        }
    }

    private func handle(_ signal: WebRTCSignal) {
        guard !isClosed else { return }
        switch signal {
        case .peerReady:
            if configuration?.signaling?.role == .offerer,
               peerConnection?.localDescription == nil {
                createAndSendOffer()
            }
        case .offer(let sdp, let generation):
            guard configuration?.signaling?.role == .answerer else { return }
            let currentGeneration = peerDelegateGenerationState.currentGeneration
            guard generation >= currentGeneration else { return }
            if generation > currentGeneration {
                guard signaling.supportsNegotiationGeneration,
                      currentGeneration < UInt64.max,
                      generation == currentGeneration + 1 else {
                    fail("Signaling delivered an unsupported PeerConnection generation.")
                    return
                }
                guard replacePeerConnection(attemptKind: .remoteReplacement) else { return }
            }
            guard let peer = peerConnection else { return }
            let generation = peerDelegateGenerationState.currentGeneration
            let acceptedSignal = WebRTCSignal.offer(sdp: sdp, generation: generation)
            guard acceptRemoteDescriptionSignal(acceptedSignal) else { return }
            let description = RTCSessionDescription(type: .offer, sdp: sdp)
            peer.setRemoteDescription(description) { [weak self] error in
                self?.queue.async {
                    guard let self,
                          self.acceptsPeerDelegateEvent(
                              peerConnection: peer,
                              delegateGeneration: generation
                          ) else { return }
                    if let error { self.fail("Remote offer rejected: \(error.localizedDescription)") }
                    else {
                        self.flushRemoteCandidates()
                        self.createAndSendAnswer()
                    }
                }
            }
        case .answer(let sdp, let generation):
            guard configuration?.signaling?.role == .offerer,
                  generation == peerDelegateGenerationState.currentGeneration,
                  let peer = peerConnection else { return }
            let generation = peerDelegateGenerationState.currentGeneration
            let acceptedSignal = WebRTCSignal.answer(sdp: sdp, generation: generation)
            guard acceptRemoteDescriptionSignal(acceptedSignal) else { return }
            peer.setRemoteDescription(RTCSessionDescription(type: .answer, sdp: sdp)) { [weak self] error in
                self?.queue.async {
                    guard let self,
                          self.acceptsPeerDelegateEvent(
                              peerConnection: peer,
                              delegateGeneration: generation
                          ) else { return }
                    if let error { self.fail("Remote answer rejected: \(error.localizedDescription)") }
                    else { self.flushRemoteCandidates() }
                }
            }
        case .candidate(let sdp, let mid, let lineIndex, let generation):
            let currentGeneration = peerDelegateGenerationState.currentGeneration
            let candidateKey = SignaledCandidateKey(
                sdp: sdp,
                mid: mid,
                lineIndex: lineIndex,
                generation: generation
            )
            guard remoteCandidateKeys.insert(candidateKey).inserted else { return }
            let candidate = RTCIceCandidate(sdp: sdp, sdpMLineIndex: lineIndex, sdpMid: mid)
            if generation > currentGeneration {
                guard configuration?.signaling?.role == .answerer,
                      signaling.supportsNegotiationGeneration,
                      currentGeneration < UInt64.max,
                      generation == currentGeneration + 1 else {
                    remoteCandidateKeys.remove(candidateKey)
                    return
                }
                futureRemoteCandidatesByGeneration[generation, default: []].append(
                    PendingSignaledCandidate(key: candidateKey, candidate: candidate)
                )
                return
            }
            guard generation == currentGeneration,
                  let peer = peerConnection else {
                remoteCandidateKeys.remove(candidateKey)
                return
            }
            guard peer.remoteDescription != nil else {
                pendingRemoteCandidates.append(candidate)
                return
            }
            addRemoteCandidate(candidate)
        }
    }

    private func createAndSendOffer() {
        guard configuration?.signaling?.role == .offerer,
              let peer = peerConnection else { return }
        let generation = peerDelegateGenerationState.currentGeneration
        guard localDescriptionGenerationInFlight != generation,
              peer.localDescription == nil else { return }
        localDescriptionGenerationInFlight = generation
        peer.offer(for: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)) {
            [weak self] description, error in
            self?.queue.async {
                guard let self,
                      self.acceptsPeerDelegateEvent(
                          peerConnection: peer,
                          delegateGeneration: generation
                      ) else { return }
                if let error { self.fail("Offer creation failed: \(error.localizedDescription)"); return }
                guard let description else { self.fail("Offer creation returned no SDP."); return }
                self.setLocalAndSignal(
                    description,
                    signal: .offer(sdp: description.sdp, generation: generation),
                    peerConnection: peer,
                    generation: generation
                )
            }
        }
    }

    private func createAndSendAnswer() {
        guard configuration?.signaling?.role == .answerer,
              let peer = peerConnection else { return }
        let generation = peerDelegateGenerationState.currentGeneration
        guard localDescriptionGenerationInFlight != generation,
              peer.localDescription == nil else { return }
        localDescriptionGenerationInFlight = generation
        peer.answer(for: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)) {
            [weak self] description, error in
            self?.queue.async {
                guard let self,
                      self.acceptsPeerDelegateEvent(
                          peerConnection: peer,
                          delegateGeneration: generation
                      ) else { return }
                if let error { self.fail("Answer creation failed: \(error.localizedDescription)"); return }
                guard let description else { self.fail("Answer creation returned no SDP."); return }
                self.setLocalAndSignal(
                    description,
                    signal: .answer(sdp: description.sdp, generation: generation),
                    peerConnection: peer,
                    generation: generation
                )
            }
        }
    }

    private func setLocalAndSignal(
        _ description: RTCSessionDescription,
        signal: WebRTCSignal,
        peerConnection: RTCPeerConnection,
        generation: UInt64
    ) {
        peerConnection.setLocalDescription(description) { [weak self] error in
            self?.queue.async {
                guard let self,
                      self.acceptsPeerDelegateEvent(
                          peerConnection: peerConnection,
                          delegateGeneration: generation
                      ) else { return }
                if let error { self.fail("Local SDP rejected: \(error.localizedDescription)"); return }
                self.signaling.send(signal) { [weak self] result in
                    self?.queue.async {
                        guard let self,
                              self.acceptsPeerDelegateEvent(
                                  peerConnection: peerConnection,
                                  delegateGeneration: generation
                              ) else { return }
                        switch result {
                        case .success:
                            self.localDescriptionPublished = true
                            self.flushLocalCandidates()
                        case .failure(let error):
                            self.fail("SDP signaling failed: \(error.localizedDescription)")
                        }
                    }
                }
            }
        }
    }

    private func addRemoteCandidate(_ candidate: RTCIceCandidate) {
        guard let peer = peerConnection else { return }
        let generation = peerDelegateGenerationState.currentGeneration
        peer.add(candidate) { [weak self] error in
            self?.queue.async {
                guard let self,
                      self.acceptsPeerDelegateEvent(
                          peerConnection: peer,
                          delegateGeneration: generation
                      ) else { return }
                if let error { self.fail("ICE candidate rejected: \(error.localizedDescription)") }
            }
        }
    }

    private func flushRemoteCandidates() {
        let candidates = pendingRemoteCandidates
        pendingRemoteCandidates.removeAll()
        candidates.forEach(addRemoteCandidate)
    }

    private func flushLocalCandidates() {
        let candidates = pendingLocalCandidates
        pendingLocalCandidates.removeAll()
        candidates.forEach(sendLocalCandidate)
    }

    private func sendLocalCandidate(_ candidate: RTCIceCandidate) {
        guard let peer = peerConnection else { return }
        let generation = peerDelegateGenerationState.currentGeneration
        let candidateKey = SignaledCandidateKey(
            sdp: candidate.sdp,
            mid: candidate.sdpMid,
            lineIndex: candidate.sdpMLineIndex,
            generation: generation
        )
        guard localCandidateKeys.insert(candidateKey).inserted else { return }
        signaling.send(.candidate(
            sdp: candidate.sdp,
            mid: candidate.sdpMid,
            lineIndex: candidate.sdpMLineIndex,
            generation: generation
        )) { [weak self] result in
            self?.queue.async {
                guard let self,
                      self.acceptsPeerDelegateEvent(
                          peerConnection: peer,
                          delegateGeneration: generation
                      ) else { return }
                if case .failure(let error) = result {
                    self.fail("ICE signaling failed: \(error.localizedDescription)")
                }
            }
        }
    }

    private func publishConnectedIfReady() {
        guard !isClosed,
              transmissionState.peerIsConnected,
              InternetTransportChannel.allCases.allSatisfy({ channelByKind[$0]?.readyState == .open }) else {
            return
        }
        startStats()
        guard selectedPath != .unknown else {
            guard startCandidatePairResolutionTimeout() else {
                fail("Selected ICE candidate pair deadline sequence was exhausted.")
                return
            }
            return
        }
        stopCandidatePairResolutionTimeout()
        guard !didPublishConnected else { return }
        guard establishTransmissionContext(path: selectedPath) != nil else { return }
        didPublishConnected = true
        stopConnectionAttemptDeadline()
        callbacks?.connectionStateChanged(.connected(path: selectedPath))
    }

    private func acceptRemoteDescriptionSignal(_ signal: WebRTCSignal) -> Bool {
        guard let acceptedRemoteDescriptionSignal else {
            self.acceptedRemoteDescriptionSignal = signal
            return true
        }
        guard acceptedRemoteDescriptionSignal != signal else { return false }
        fail("Signaling delivered conflicting remote SDP for the current PeerConnection generation.")
        return false
    }

    @discardableResult
    private func startConnectionAttemptDeadline(
        attemptKind: WebRTCPeerConnectionAttemptKind
    ) -> Bool {
        let generation = peerDelegateGenerationState.currentGeneration
        if connectionAttemptTimer != nil { return true }
        guard let token = connectionAttemptDeadlineState.schedule(
                  generation: generation,
                  attemptKind: attemptKind
              ) else { return false }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .seconds(Self.connectionAttemptTimeoutSeconds))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            guard !self.isClosed,
                  let attemptKind = self.connectionAttemptDeadlineState.fire(
                      token: token,
                      currentGeneration: self.peerDelegateGenerationState.currentGeneration
                  ) else { return }
            self.connectionAttemptTimer = nil
            switch attemptKind {
            case .initial:
                self.fail("Initial WebRTC connection timed out.")
            case .localRecovery:
                self.callbacks?.connectionStateChanged(.disconnected)
            case .remoteReplacement:
                self.fail("Remote PeerConnection replacement timed out.")
            }
        }
        connectionAttemptTimer = timer
        timer.resume()
        return true
    }

    private func stopConnectionAttemptDeadline() {
        connectionAttemptDeadlineState.cancel()
        connectionAttemptTimer?.cancel()
        connectionAttemptTimer = nil
    }

    @discardableResult
    private func startCandidatePairResolutionTimeout() -> Bool {
        if candidatePairResolutionTimer != nil { return true }
        guard let token = candidatePairResolutionTimeoutState.scheduleIfNeeded() else { return false }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .seconds(Self.candidatePairResolutionTimeoutSeconds))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            guard let shouldFailClosed = self.candidatePairResolutionTimeoutState.fire(
                token: token,
                peerIsConnected: self.transmissionState.peerIsConnected,
                selectedPath: self.selectedPath
            ) else { return }
            self.candidatePairResolutionTimer = nil
            guard !self.isClosed, shouldFailClosed else { return }
            self.fail("Selected ICE candidate pair statistics were unavailable before timeout.")
        }
        candidatePairResolutionTimer = timer
        timer.resume()
        return true
    }

    private func stopCandidatePairResolutionTimeout() {
        candidatePairResolutionTimeoutState.cancel()
        candidatePairResolutionTimer?.cancel()
        candidatePairResolutionTimer = nil
    }

    private func startPathMonitor() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let interface: InternetNetworkPath.Interface
            if path.usesInterfaceType(.wiredEthernet) { interface = .wiredEthernet }
            else if path.usesInterfaceType(.wifi) { interface = .wifi }
            else if path.usesInterfaceType(.cellular) { interface = .cellular }
            else { interface = .other("other") }
            let fingerprint = NetworkPathFingerprint.make(path)
            let networkPath = InternetNetworkPath(
                interface: interface,
                isSatisfied: path.status == .satisfied,
                fingerprint: fingerprint
            )
            self.queue.async {
                guard !self.isClosed else { return }
                let changed = self.lastNetworkPathFingerprint.map { $0 != fingerprint } ?? false
                self.lastNetworkPathFingerprint = fingerprint
                if changed { self.invalidateTransmissionContext() }
                self.callbacks?.networkPathChanged(networkPath)
            }
        }
        pathMonitor.start(queue: pathQueue)
    }

    private func startStats() {
        guard statsTimer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .seconds(1))
        timer.setEventHandler { [weak self] in self?.sampleStats() }
        statsTimer = timer
        timer.resume()
    }

    private func stopStats() {
        statsTimer?.cancel()
        statsTimer = nil
    }

    private func sampleStats() {
        guard let peer = peerConnection else { return }
        let expectedTransmissionEpoch = transmissionState.epoch
        let generation = peerDelegateGenerationState.currentGeneration
        guard let requestSequence = statisticsRequestOrderingState.beginRequest() else {
            fail("WebRTC statistics request sequence was exhausted.")
            return
        }
        peer.statistics { [weak self] report in
            self?.queue.async {
                self?.consume(
                    report,
                    peerConnection: peer,
                    generation: generation,
                    expectedTransmissionEpoch: expectedTransmissionEpoch,
                    requestSequence: requestSequence
                )
            }
        }
    }

    private func consume(
        _ report: RTCStatisticsReport,
        peerConnection: RTCPeerConnection,
        generation: UInt64,
        expectedTransmissionEpoch: UInt64,
        requestSequence: UInt64
    ) {
        guard !isClosed,
              acceptsPeerDelegateEvent(
                  peerConnection: peerConnection,
                  delegateGeneration: generation
              ),
              transmissionState.acceptsCandidateStatistics(
                  expectedEpoch: expectedTransmissionEpoch
              ),
              statisticsRequestOrderingState.acceptsResponse(
                  sequence: requestSequence
              ) else { return }
        let selectedPairID = report.statistics.values.lazy.compactMap { statistic -> String? in
            guard statistic.type == "transport" else { return nil }
            return statistic.values["selectedCandidatePairId"] as? String
        }.first
        selectedCandidatePairStatisticsID = selectedPairID
        var availableBitrate: UInt64 = 0
        var roundTripTime: Double = 0
        var packetsLost: Double = 0
        var packetsReceived: Double = 0
        var observedSelectedPath: InternetPathKind?
        var observedCandidatePair: WebRTCSelectedCandidatePair?
        for statistic in report.statistics.values {
            if statistic.type == "candidate-pair", statistic.id == selectedPairID {
                availableBitrate = (statistic.values["availableOutgoingBitrate"] as? NSNumber)?.uint64Value ?? 0
                roundTripTime = ((statistic.values["currentRoundTripTime"] as? NSNumber)?.doubleValue ?? 0) * 1_000
                let localID = statistic.values["localCandidateId"] as? String
                let remoteID = statistic.values["remoteCandidateId"] as? String
                let localCandidate = report.statistics.values.first { $0.id == localID }
                let remoteCandidate = report.statistics.values.first { $0.id == remoteID }
                let localType = localCandidate?.values["candidateType"] as? String
                let remoteType = remoteCandidate?.values["candidateType"] as? String
                let newPath = SelectedCandidatePathResolver.resolve(
                    localCandidateType: localType,
                    remoteCandidateType: remoteType
                )
                observedSelectedPath = newPath
                let pair = WebRTCSelectedCandidatePair(
                    path: newPath,
                    localCandidateType: localType ?? "unknown",
                    remoteCandidateType: remoteType ?? "unknown",
                    networkProtocol: (localCandidate?.values["protocol"] as? String ?? "unknown").lowercased()
                )
                observedCandidatePair = pair
            }
            if statistic.type == "data-channel" {
                packetsLost += (statistic.values["messagesDiscardedOnSend"] as? NSNumber)?.doubleValue ?? 0
                packetsReceived += (statistic.values["messagesReceived"] as? NSNumber)?.doubleValue ?? 0
            }
        }
        if SelectedCandidatePathResolver.mustFailClosed(
            publishedPath: didPublishConnected ? selectedPath : nil,
            observedPath: observedSelectedPath
        ) {
            fail("Selected ICE candidate pair statistics became unavailable or unknown.")
            return
        }
        if let pair = observedCandidatePair {
            if pair.path != .unknown, pair.path != selectedPath {
                selectedPath = pair.path
                if didPublishConnected {
                    guard establishTransmissionContext(path: pair.path) != nil else { return }
                    callbacks?.connectionStateChanged(.connected(path: pair.path))
                } else {
                    publishConnectedIfReady()
                }
            }
            if pair != selectedCandidatePair {
                selectedCandidatePair = pair
                callbacks?.selectedCandidatePairChanged(pair)
            }
        }
        let denominator = packetsLost + packetsReceived
        callbacks?.networkQualitySampled(InternetNetworkQualitySample(
            roundTripTimeMilliseconds: roundTripTime,
            packetLossFraction: denominator > 0 ? packetsLost / denominator : 0,
            availableOutgoingBitrateBps: availableBitrate
        ))
    }

    private func fail(_ reason: String) {
        guard !isClosed else { return }
        markPeerDisconnected()
        didPublishConnected = false
        stopConnectionAttemptDeadline()
        stopCandidatePairResolutionTimeout()
        stopStats()
        callbacks?.connectionStateChanged(.failed(reason))
        if !isClosed { failPendingSDKSends() }
    }

    private func performSync<T>(_ operation: () throws -> T) rethrows -> T {
        if DispatchQueue.getSpecific(key: queueKey) != nil { return try operation() }
        return try queue.sync(execute: operation)
    }
}

extension InternetTransportChannel: CaseIterable {
    static var allCases: [InternetTransportChannel] { [.control, .media] }
}

private extension ProductionWebRTCEngine {
    func acceptsPeerDelegateEvent(
        peerConnection: RTCPeerConnection,
        delegateGeneration: UInt64
    ) -> Bool {
        !isClosed
            && self.peerConnection === peerConnection
            && peerDelegateGenerationState.accepts(delegateGeneration: delegateGeneration)
    }

    func handleICEConnectionState(
        _ newState: RTCIceConnectionState,
        peerConnection: RTCPeerConnection,
        delegateGeneration: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsPeerDelegateEvent(
                      peerConnection: peerConnection,
                      delegateGeneration: delegateGeneration
                  ) else { return }
            switch newState {
            case .new:
                break
            case .checking:
                self.stopStats()
                self.stopCandidatePairResolutionTimeout()
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.selectedPath = .unknown
                self.selectedCandidatePair = nil
                self.didPublishConnected = false
                self.callbacks?.connectionStateChanged(.connecting)
            case .connected, .completed:
                self.transmissionState.markPeerConnected()
                self.publishConnectedIfReady()
            case .disconnected:
                self.stopStats()
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.stopCandidatePairResolutionTimeout()
                self.selectedPath = .unknown
                self.selectedCandidatePair = nil
                self.didPublishConnected = false
                self.callbacks?.connectionStateChanged(.disconnected)
            case .failed:
                self.fail("libwebrtc ICE connection failed.")
            case .closed:
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.callbacks?.connectionStateChanged(.closed)
            case .count:
                break
            @unknown default:
                self.fail("Unknown libwebrtc ICE connection state.")
            }
        }
    }

    func handleGeneratedCandidate(
        _ candidate: RTCIceCandidate,
        peerConnection: RTCPeerConnection,
        delegateGeneration: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsPeerDelegateEvent(
                      peerConnection: peerConnection,
                      delegateGeneration: delegateGeneration
                  ) else { return }
            guard self.localDescriptionPublished else {
                self.pendingLocalCandidates.append(candidate)
                return
            }
            self.sendLocalCandidate(candidate)
        }
    }

    func handleOpenedDataChannel(
        _ dataChannel: RTCDataChannel,
        peerConnection: RTCPeerConnection,
        delegateGeneration: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsPeerDelegateEvent(
                      peerConnection: peerConnection,
                      delegateGeneration: delegateGeneration
                  ) else {
                dataChannel.close()
                return
            }
            guard self.configuration?.signaling?.role == .answerer,
                  let kind = self.kindByLabel[dataChannel.label] else {
                dataChannel.close()
                self.fail("Unexpected remote data channel \(dataChannel.label) was rejected.")
                return
            }
            guard self.install(
                channel: dataChannel,
                kind: kind,
                generation: delegateGeneration
            ) else { return }
            self.publishConnectedIfReady()
        }
    }

    func handlePeerConnectionState(
        _ newState: RTCPeerConnectionState,
        peerConnection: RTCPeerConnection,
        delegateGeneration: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsPeerDelegateEvent(
                      peerConnection: peerConnection,
                      delegateGeneration: delegateGeneration
                  ) else { return }
            switch newState {
            case .new:
                break
            case .connecting:
                self.stopStats()
                self.stopCandidatePairResolutionTimeout()
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.selectedPath = .unknown
                self.selectedCandidatePair = nil
                self.didPublishConnected = false
                self.callbacks?.connectionStateChanged(.connecting)
            case .connected:
                self.transmissionState.markPeerConnected()
                self.publishConnectedIfReady()
            case .disconnected:
                self.stopStats()
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.stopCandidatePairResolutionTimeout()
                self.selectedPath = .unknown
                self.selectedCandidatePair = nil
                self.didPublishConnected = false
                self.callbacks?.connectionStateChanged(.disconnected)
            case .failed:
                self.fail("libwebrtc peer connection failed.")
            case .closed:
                guard self.markPeerDisconnected() else {
                    self.fail(Self.transmissionEpochExhaustedReason)
                    return
                }
                self.callbacks?.connectionStateChanged(.closed)
            @unknown default:
                self.fail("Unknown libwebrtc connection state.")
            }
        }
    }

    func acceptsDataChannelEvent(
        dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) -> Bool {
        !isClosed
            && peerDelegateGenerationState.accepts(delegateGeneration: generation)
            && channelByKind[kind] === dataChannel
    }

    func acceptsInboundDataChannelEvent(
        dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) -> Bool {
        acceptsDataChannelEvent(dataChannel: dataChannel, kind: kind, generation: generation)
            && didPublishConnected
            && transmissionState.peerIsConnected
            && currentTransmissionContext != nil
    }

    func acceptsDataChannelDrainEvent(
        dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) -> Bool {
        acceptsInboundDataChannelEvent(
            dataChannel: dataChannel,
            kind: kind,
            generation: generation
        )
    }

    func handleDataChannelStateChange(
        _ dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsDataChannelEvent(
                      dataChannel: dataChannel,
                      kind: kind,
                      generation: generation
                  ) else { return }
            switch dataChannel.readyState {
            case .connecting, .open:
                self.publishConnectedIfReady()
            case .closing, .closed:
                guard let transition = self.prepareUnexpectedDataChannelClosure(
                    dataChannel,
                    kind: kind,
                    generation: generation
                ) else { return }
                self.performUnexpectedDataChannelClosure(transition)
            @unknown default:
                self.fail("Unknown \(kind) data channel state.")
            }
        }
    }

    func handleDataChannelMessage(
        _ buffer: RTCDataBuffer,
        dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsInboundDataChannelEvent(
                      dataChannel: dataChannel,
                      kind: kind,
                      generation: generation
                  ) else { return }
            self.callbacks?.messageReceived(buffer.data, kind)
        }
    }

    func handleDataChannelBufferedAmountChange(
        _ dataChannel: RTCDataChannel,
        kind: InternetTransportChannel,
        generation: UInt64
    ) {
        queue.async { [weak self] in
            guard let self,
                  self.acceptsDataChannelDrainEvent(
                      dataChannel: dataChannel,
                      kind: kind,
                      generation: generation
                  ) else { return }
            // The property is authoritative across libwebrtc versions; the
            // delegate argument has represented both old and new values.
            self.completeSDKSendIfDrained(
                channel: kind,
                currentBufferedAmount: dataChannel.bufferedAmount
            )
        }
    }
}
