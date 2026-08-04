import Foundation

enum InternetTransportChannel: Equatable {
    case control
    case media

    var dataChannelConfiguration: WebRTCDataChannelConfiguration {
        switch self {
        case .control:
            return WebRTCDataChannelConfiguration(
                label: "vibescreen.control.v1",
                isOrdered: true,
                maximumRetransmits: nil
            )
        case .media:
            return WebRTCDataChannelConfiguration(
                label: "vibescreen.media.v1",
                isOrdered: false,
                maximumRetransmits: 0
            )
        }
    }
}

struct WebRTCDataChannelConfiguration: Equatable {
    let label: String
    let isOrdered: Bool
    let maximumRetransmits: UInt16?
}

struct WebRTCICEServer: Equatable {
    let urls: [URL]
    let username: String?
    let credential: String?

    init(urls: [URL], username: String? = nil, credential: String? = nil) {
        self.urls = urls
        self.username = username
        self.credential = credential
    }

    var isRelay: Bool {
        urls.contains { ["turn", "turns"].contains($0.scheme?.lowercased() ?? "") }
    }
}

enum WebRTCSignalingRole: String, Codable, Equatable {
    case offerer
    case answerer
}

struct WebRTCSignalingConfiguration: Equatable {
    let endpoint: URL
    let bearerToken: String
    let role: WebRTCSignalingRole

    init(endpoint: URL, bearerToken: String, role: WebRTCSignalingRole) {
        self.endpoint = endpoint
        self.bearerToken = bearerToken
        self.role = role
    }
}

struct WebRTCTransportConfiguration: Equatable {
    let iceServers: [WebRTCICEServer]
    let peerIdentity: String
    let sessionIdentifier: String
    let forceRelay: Bool
    let signaling: WebRTCSignalingConfiguration?

    init(
        iceServers: [WebRTCICEServer],
        peerIdentity: String,
        sessionIdentifier: String,
        forceRelay: Bool,
        signaling: WebRTCSignalingConfiguration? = nil
    ) {
        self.iceServers = iceServers
        self.peerIdentity = peerIdentity
        self.sessionIdentifier = sessionIdentifier
        self.forceRelay = forceRelay
        self.signaling = signaling
    }

    func validate() throws {
        guard !peerIdentity.isEmpty, !sessionIdentifier.isEmpty else {
            throw InternetTransportError.invalidConfiguration("Peer identity and session identifier are required.")
        }
        guard !iceServers.isEmpty else {
            throw InternetTransportError.invalidConfiguration("At least one STUN or TURN server is required.")
        }

        for server in iceServers {
            guard !server.urls.isEmpty else {
                throw InternetTransportError.invalidConfiguration("An ICE server has no URLs.")
            }
            for url in server.urls {
                let scheme = url.scheme?.lowercased() ?? ""
                guard ["stun", "stuns", "turn", "turns"].contains(scheme) else {
                    throw InternetTransportError.invalidConfiguration("Unsupported ICE URL scheme: \(scheme)")
                }
            }
            if server.isRelay,
               (server.username?.isEmpty != false || server.credential?.isEmpty != false) {
                throw InternetTransportError.invalidConfiguration("TURN servers require a username and credential.")
            }
        }

        if forceRelay, !iceServers.contains(where: \.isRelay) {
            throw InternetTransportError.invalidConfiguration("Relay-only mode requires a TURN server.")
        }

        if let signaling {
            let scheme = signaling.endpoint.scheme?.lowercased()
            let isLocalCleartext = scheme == "http"
                && ["localhost", "127.0.0.1", "::1"].contains(signaling.endpoint.host ?? "")
            guard scheme == "https" || isLocalCleartext else {
                throw InternetTransportError.invalidConfiguration(
                    "Signaling must use https://; http:// is allowed only for loopback integration tests."
                )
            }
            guard !signaling.bearerToken.isEmpty else {
                throw InternetTransportError.invalidConfiguration("A signaling bearer token is required.")
            }
        }
    }
}

enum InternetTransportState: Equatable {
    case idle
    case connecting
    case connected(InternetPathKind)
    case recovering(attempt: Int)
    case failed(String)
    case closed
}

enum InternetPathKind: Equatable {
    case unknown
    case direct
    case relay
}

enum SelectedCandidatePathResolver {
    private static let directCandidateTypes: Set<String> = [
        "host", "srflx", "prflx"
    ]

    static func resolve(
        localCandidateType: String?,
        remoteCandidateType: String?
    ) -> InternetPathKind {
        guard let local = localCandidateType?.lowercased(),
              let remote = remoteCandidateType?.lowercased() else {
            return .unknown
        }
        if local == "relay" || remote == "relay" { return .relay }
        guard directCandidateTypes.contains(local),
              directCandidateTypes.contains(remote) else {
            return .unknown
        }
        return .direct
    }

    static func mustFailClosed(
        publishedPath: InternetPathKind?,
        observedPath: InternetPathKind?
    ) -> Bool {
        guard publishedPath == .direct || publishedPath == .relay else {
            return false
        }
        return observedPath == nil || observedPath == .unknown
    }
}

enum InternetRecoveryStrategy: Equatable {
    /// Retained for standalone adapter tests. This requires signaling support
    /// for negotiation generations and is not used by the product session.
    case restartICE
    /// Closes the old cryptographic/signaling session and asks the product
    /// authority for a new session ID, role token, epoch, keys, and PeerConnection.
    case freshSession
}

struct InternetNetworkPath: Equatable {
    enum Interface: Equatable {
        case wiredEthernet
        case wifi
        case cellular
        case other(String)
    }

    let interface: Interface
    let isSatisfied: Bool
    let fingerprint: String
}

struct EncodedInternetFrame: Equatable {
    let payload: Data
    let captureTimestamp: UInt64
    let isKeyframe: Bool
}

struct InternetTransportLimits: Equatable {
    static let standard = InternetTransportLimits(
        maximumControlMessageBytes: 256 * 1_024,
        maximumBufferedControlBytes: 2 * 1_024 * 1_024,
        maximumMediaFrameBytes: 16 * 1_024 * 1_024,
        maximumRelayBytesPerSession: 10 * 1_024 * 1_024 * 1_024
    )

    let maximumControlMessageBytes: Int
    let maximumBufferedControlBytes: Int
    let maximumMediaFrameBytes: Int
    let maximumRelayBytesPerSession: UInt64
}

struct InternetTransportSnapshot: Equatable {
    let state: InternetTransportState
    let activePath: InternetPathKind?
    let controlBytesSent: UInt64
    let mediaBytesSent: UInt64
    let relayBytesSent: UInt64
    let relayBytesReserved: UInt64
    let droppedMediaFrames: UInt64
    let iceRestartCount: UInt64
    let bufferedControlBytes: Int
    let hasPendingMediaFrame: Bool
}

enum InternetTransportError: Error, Equatable, LocalizedError {
    case invalidConfiguration(String)
    case engineUnavailable(String)
    case notConnected
    case emptyPayload(channel: InternetTransportChannel)
    case payloadTooLarge(channel: InternetTransportChannel, actual: Int, maximum: Int)
    case controlBacklogExceeded(maximumBytes: Int)
    case relayBudgetExceeded(maximumBytes: UInt64)
    case engineSendFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidConfiguration(let reason), .engineUnavailable(let reason):
            return reason
        case .notConnected:
            return "The Internet transport is not connected."
        case .emptyPayload(let channel):
            return "The \(channel) channel does not accept empty messages."
        case .payloadTooLarge(let channel, let actual, let maximum):
            return "\(channel) payload is \(actual) bytes; maximum is \(maximum)."
        case .controlBacklogExceeded(let maximumBytes):
            return "Reliable control backlog exceeded \(maximumBytes) bytes."
        case .relayBudgetExceeded(let maximumBytes):
            return "TURN relay budget exceeded \(maximumBytes) bytes."
        case .engineSendFailed(let reason):
            return "WebRTC engine send failed: \(reason)"
        }
    }
}
