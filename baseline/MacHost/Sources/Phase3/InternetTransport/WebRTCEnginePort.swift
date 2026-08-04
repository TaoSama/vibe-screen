import Foundation

enum WebRTCEngineConnectionState: Equatable {
    case connecting
    case connected(path: InternetPathKind)
    case disconnected
    case failed(String)
    case closed
}

struct WebRTCSelectedCandidatePair: Equatable {
    let path: InternetPathKind
    let localCandidateType: String
    let remoteCandidateType: String
    let networkProtocol: String
}

struct WebRTCEngineCallbacks {
    let connectionStateChanged: (WebRTCEngineConnectionState) -> Void
    let networkPathChanged: (InternetNetworkPath) -> Void
    let networkQualitySampled: (InternetNetworkQualitySample) -> Void
    let messageReceived: (Data, InternetTransportChannel) -> Void
    let selectedCandidatePairChanged: (WebRTCSelectedCandidatePair) -> Void

    init(
        connectionStateChanged: @escaping (WebRTCEngineConnectionState) -> Void,
        networkPathChanged: @escaping (InternetNetworkPath) -> Void,
        networkQualitySampled: @escaping (InternetNetworkQualitySample) -> Void,
        messageReceived: @escaping (Data, InternetTransportChannel) -> Void = { _, _ in },
        selectedCandidatePairChanged: @escaping (WebRTCSelectedCandidatePair) -> Void = { _ in }
    ) {
        self.connectionStateChanged = connectionStateChanged
        self.networkPathChanged = networkPathChanged
        self.networkQualitySampled = networkQualitySampled
        self.messageReceived = messageReceived
        self.selectedCandidatePairChanged = selectedCandidatePairChanged
    }
}

/// Boundary implemented by the production WebRTC SDK adapter.
///
/// The adapter must create two negotiated data channels using the supplied
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
        completion: @escaping (Result<Void, Error>) -> Void
    )
    func restartICE()
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
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        completion(.failure(InternetTransportError.engineUnavailable(integrationMessage)))
    }

    func restartICE() {}
    func requestMediaKeyframe() {}
    func close() {}
}
