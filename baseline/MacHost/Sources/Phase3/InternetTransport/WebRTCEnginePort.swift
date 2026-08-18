import Foundation

enum WebRTCEngineConnectionState: Equatable {
    case connecting
    case connected(path: InternetPathKind)
    case disconnected
    case failed(String)
    case closed
}

struct WebRTCEngineTransmissionContext: Equatable {
    let epoch: UInt64
    let path: InternetPathKind
}

struct WebRTCEngineTransmissionContextUpdate: Equatable {
    let invalidatedPriorContext: Bool
    let context: WebRTCEngineTransmissionContext
}

struct WebRTCPeerConnectionDelegateGenerationState {
    private(set) var currentGeneration: UInt64 = 0

    mutating func reset() {
        currentGeneration = 0
    }

    mutating func beginRestart() -> UInt64? {
        guard currentGeneration < UInt64.max else { return nil }
        currentGeneration += 1
        return currentGeneration
    }

    func accepts(delegateGeneration: UInt64) -> Bool {
        delegateGeneration == currentGeneration
    }
}

enum WebRTCPeerConnectionAttemptKind: Equatable {
    case initial
    case localRecovery
    case remoteReplacement
}

struct WebRTCConnectionAttemptDeadlineState {
    private(set) var nextToken: UInt64 = 0
    private(set) var activeToken: UInt64?
    private(set) var scheduledGeneration: UInt64?
    private(set) var attemptKind: WebRTCPeerConnectionAttemptKind?

    mutating func schedule(
        generation: UInt64,
        attemptKind: WebRTCPeerConnectionAttemptKind
    ) -> UInt64? {
        guard activeToken == nil, nextToken < UInt64.max else { return nil }
        nextToken += 1
        activeToken = nextToken
        scheduledGeneration = generation
        self.attemptKind = attemptKind
        return nextToken
    }

    mutating func cancel() {
        activeToken = nil
        scheduledGeneration = nil
        attemptKind = nil
    }

    mutating func fire(
        token: UInt64,
        currentGeneration: UInt64
    ) -> WebRTCPeerConnectionAttemptKind? {
        guard activeToken == token,
              scheduledGeneration == currentGeneration else { return nil }
        let firedAttemptKind = attemptKind
        cancel()
        return firedAttemptKind
    }
}

struct WebRTCEngineTransmissionEpochState {
    private(set) var epoch: UInt64 = 0
    private(set) var peerIsConnected = false
    private(set) var activePath: InternetPathKind?
    private(set) var isExhausted = false

    init(
        epoch: UInt64 = 0,
        peerIsConnected: Bool = false,
        activePath: InternetPathKind? = nil,
        isExhausted: Bool = false
    ) {
        self.epoch = epoch
        self.peerIsConnected = peerIsConnected
        self.activePath = activePath
        self.isExhausted = isExhausted
    }

    var currentContext: WebRTCEngineTransmissionContext? {
        guard !isExhausted, let activePath else { return nil }
        return WebRTCEngineTransmissionContext(epoch: epoch, path: activePath)
    }

    var acceptsCandidateStatistics: Bool { peerIsConnected && !isExhausted }

    func acceptsCandidateStatistics(expectedEpoch: UInt64) -> Bool {
        peerIsConnected && !isExhausted && epoch == expectedEpoch
    }

    mutating func reset() {
        epoch = 0
        peerIsConnected = false
        activePath = nil
        isExhausted = false
    }

    mutating func markPeerConnected() {
        guard !isExhausted else { return }
        peerIsConnected = true
    }

    @discardableResult
    mutating func markPeerDisconnected() -> Bool {
        peerIsConnected = false
        return invalidateContext()
    }

    @discardableResult
    mutating func invalidateContext() -> Bool {
        guard activePath != nil else { return false }
        activePath = nil
        guard epoch < UInt64.max else {
            peerIsConnected = false
            isExhausted = true
            return true
        }
        epoch += 1
        return true
    }

    @discardableResult
    mutating func beginRestart() -> Bool {
        let invalidatedPriorContext = activePath != nil
        activePath = nil
        peerIsConnected = false
        guard epoch < UInt64.max else {
            isExhausted = true
            return invalidatedPriorContext
        }
        epoch += 1
        return invalidatedPriorContext
    }

    mutating func selectPath(
        _ path: InternetPathKind
    ) -> WebRTCEngineTransmissionContextUpdate? {
        guard peerIsConnected, !isExhausted, path != .unknown else { return nil }
        let invalidatedPriorContext = activePath != nil && activePath != path
        if invalidatedPriorContext { _ = invalidateContext() }
        guard !isExhausted else { return nil }
        activePath = path
        guard let currentContext else { return nil }
        return WebRTCEngineTransmissionContextUpdate(
            invalidatedPriorContext: invalidatedPriorContext,
            context: currentContext
        )
    }

    func acceptsSend(expectedContext: WebRTCEngineTransmissionContext) -> Bool {
        peerIsConnected && !isExhausted && currentContext == expectedContext
    }
}

struct WebRTCCandidatePairResolutionTimeoutState {
    private(set) var nextToken: UInt64 = 0
    private(set) var activeToken: UInt64?

    var isScheduled: Bool { activeToken != nil }

    mutating func scheduleIfNeeded() -> UInt64? {
        guard activeToken == nil, nextToken < UInt64.max else { return nil }
        nextToken += 1
        activeToken = nextToken
        return nextToken
    }

    mutating func cancel() {
        activeToken = nil
    }

    mutating func fire(
        token: UInt64,
        peerIsConnected: Bool,
        selectedPath: InternetPathKind
    ) -> Bool? {
        guard activeToken == token else { return nil }
        activeToken = nil
        return peerIsConnected && selectedPath == .unknown
    }
}

struct WebRTCStatisticsRequestOrderingState {
    private(set) var nextSequence: UInt64 = 0
    private(set) var latestObservedResponseSequence: UInt64?

    init(
        nextSequence: UInt64 = 0,
        latestObservedResponseSequence: UInt64? = nil
    ) {
        self.nextSequence = nextSequence
        self.latestObservedResponseSequence = latestObservedResponseSequence
    }

    mutating func reset() {
        nextSequence = 0
        latestObservedResponseSequence = nil
    }

    mutating func beginRequest() -> UInt64? {
        guard nextSequence < UInt64.max else { return nil }
        nextSequence += 1
        return nextSequence
    }

    mutating func acceptsResponse(sequence: UInt64) -> Bool {
        if let latestObservedResponseSequence,
           sequence <= latestObservedResponseSequence {
            return false
        }
        latestObservedResponseSequence = sequence
        return true
    }
}

struct WebRTCSelectedCandidatePair: Equatable {
    let path: InternetPathKind
    let localCandidateType: String
    let remoteCandidateType: String
    let networkProtocol: String
}

struct WebRTCEngineCallbacks {
    let connectionStateChanged: (WebRTCEngineConnectionState) -> Void
    let transmissionContextChanged: (WebRTCEngineTransmissionContext?) -> Void
    let networkPathChanged: (InternetNetworkPath) -> Void
    let networkQualitySampled: (InternetNetworkQualitySample) -> Void
    let messageReceived: (Data, InternetTransportChannel) -> Void
    let selectedCandidatePairChanged: (WebRTCSelectedCandidatePair) -> Void

    init(
        connectionStateChanged: @escaping (WebRTCEngineConnectionState) -> Void,
        transmissionContextChanged: @escaping (WebRTCEngineTransmissionContext?) -> Void = { _ in },
        networkPathChanged: @escaping (InternetNetworkPath) -> Void,
        networkQualitySampled: @escaping (InternetNetworkQualitySample) -> Void,
        messageReceived: @escaping (Data, InternetTransportChannel) -> Void = { _, _ in },
        selectedCandidatePairChanged: @escaping (WebRTCSelectedCandidatePair) -> Void = { _ in }
    ) {
        self.connectionStateChanged = connectionStateChanged
        self.transmissionContextChanged = transmissionContextChanged
        self.networkPathChanged = networkPathChanged
        self.networkQualitySampled = networkQualitySampled
        self.messageReceived = messageReceived
        self.selectedCandidatePairChanged = selectedCandidatePairChanged
    }
}

enum WebRTCEngineRecoveryDisposition: Equatable {
    case peerReplacementStarted
    case requiresFreshSession(String)
    case failed(String)
}

/// Boundary implemented by the production WebRTC SDK adapter.
///
/// The adapter must create the negotiated Protocol v1 data channels using the supplied
/// descriptors. It owns SDP exchange, DTLS/SRTP, ICE candidate signaling, and
/// certificate verification. The transport policy above this port never sees
/// plaintext relay credentials beyond initial configuration and TURN must not
/// terminate application payload encryption.
protocol WebRTCEnginePort: AnyObject {
    func install(callbacks: WebRTCEngineCallbacks)
    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws
    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    )
    func restartICE() -> WebRTCEngineRecoveryDisposition
    func requestMediaKeyframe()
    func close()
}

/// Deliberately fails until an audited WebRTC binary adapter is supplied.
/// This prevents a TCP or test double from being reported as production P2P.
final class UnavailableWebRTCEngine: WebRTCEnginePort {
    private let integrationMessage: String

    init(
        integrationMessage: String = "No production WebRTC engine is linked. Install an audited adapter that implements WebRTCEnginePort."
    ) {
        self.integrationMessage = integrationMessage
    }

    func install(callbacks: WebRTCEngineCallbacks) {}

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        throw InternetTransportError.engineUnavailable(integrationMessage)
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        completion(.failure(InternetTransportError.engineUnavailable(integrationMessage)))
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition {
        .failed(integrationMessage)
    }
    func requestMediaKeyframe() {}
    func close() {}
}
