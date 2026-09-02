import Foundation
import VibeScreenProtocol

enum InternetTransportChannel: Equatable {
    case control
    case media
    case audio
    case bulk

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
        case .audio:
            return WebRTCDataChannelConfiguration(
                label: "vibescreen.audio.v1",
                isOrdered: false,
                maximumRetransmits: 0
            )
        case .bulk:
            return WebRTCDataChannelConfiguration(
                label: "vibescreen.bulk.v1",
                isOrdered: true,
                maximumRetransmits: nil
            )
        }
    }
}

extension InternetTransportChannel: CaseIterable {
    static var allCases: [InternetTransportChannel] { [.control, .media, .audio, .bulk] }
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
    /// Attempts bounded ICE restart first. If the engine or signaling session
    /// cannot renegotiate, product owners must provide a fresh session.
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

enum InternetMediaRecordContract {
    static let maximumEncryptedRecordBytes = 4 * 1_024 * 1_024
    static let maximumFrameBytes = 16 * 1_024 * 1_024
    static let applicationAEADRecordOverheadBytes = PlatformSessionPacketCipher.recordOverhead
    static let maximumPlaintextRecordBytes =
        maximumEncryptedRecordBytes - applicationAEADRecordOverheadBytes
    static let maximumMediaHeaderBytes = 64 * 1_024
    static let maximumHeaderLengthVarintBytes = 5
    static let maximumFragmentPayloadBytes =
        maximumPlaintextRecordBytes - maximumMediaHeaderBytes - maximumHeaderLengthVarintBytes
    static let maximumFragmentsPerFrame = 256

    static let minimumNegotiatedEncryptedRecordBytes =
        applicationAEADRecordOverheadBytes
        + maximumMediaHeaderBytes
        + maximumHeaderLengthVarintBytes
        + (maximumFrameBytes + maximumFragmentsPerFrame - 1) / maximumFragmentsPerFrame

    static func maximumPlaintextRecordBytes(negotiatedEncryptedRecordBytes: Int) -> Int {
        negotiatedEncryptedRecordBytes - applicationAEADRecordOverheadBytes
    }

    static func maximumFragmentPayloadBytes(negotiatedEncryptedRecordBytes: Int) -> Int {
        maximumPlaintextRecordBytes(negotiatedEncryptedRecordBytes: negotiatedEncryptedRecordBytes)
            - maximumMediaHeaderBytes
            - maximumHeaderLengthVarintBytes
    }

    static func encryptedRecordBytes(forPlaintextBytes plaintextBytes: Int) -> UInt64 {
        UInt64(plaintextBytes + applicationAEADRecordOverheadBytes)
    }
}

enum InternetAudioRecordContract {
    static let maximumEncryptedRecordBytes = 256 * 1_024
    static let applicationAEADRecordOverheadBytes = PlatformSessionPacketCipher.recordOverhead
    static let maximumPlaintextRecordBytes =
        maximumEncryptedRecordBytes - applicationAEADRecordOverheadBytes

    static func encryptedRecordBytes(forPlaintextBytes plaintextBytes: Int) -> UInt64 {
        UInt64(plaintextBytes + applicationAEADRecordOverheadBytes)
    }
}

enum InternetBulkRecordContract {
    static let maximumEncryptedRecordBytes = 4 * 1_024 * 1_024
    static let applicationAEADRecordOverheadBytes = PlatformSessionPacketCipher.recordOverhead
    static let maximumPlaintextRecordBytes =
        maximumEncryptedRecordBytes - applicationAEADRecordOverheadBytes

    static func encryptedRecordBytes(forPlaintextBytes plaintextBytes: Int) -> UInt64 {
        UInt64(plaintextBytes + applicationAEADRecordOverheadBytes)
    }
}

enum EncodedInternetFrameError: Error, Equatable {
    case emptyRecords
    case tooManyRecords(actual: Int, maximum: Int)
    case invalidMediaPayloadBytes(Int)
    case mediaPayloadTooLarge(actual: Int, maximum: Int)
    case invalidRecordSize(index: Int, actual: Int, maximum: Int)
    case malformedRecord(index: Int)
    case invalidFragmentLayout(index: Int)
    case inconsistentHeaderScope(index: Int)
    case mediaPayloadBytesMismatch(declared: Int, actual: Int)
}

struct EncodedInternetFrame: Equatable {
    let records: [Data]
    let mediaPayloadBytes: Int
    let captureTimestamp: UInt64
    let isKeyframe: Bool

    init(
        records: [Data],
        mediaPayloadBytes: Int,
        captureTimestamp: UInt64,
        isKeyframe: Bool
    ) throws {
        guard !records.isEmpty else {
            throw EncodedInternetFrameError.emptyRecords
        }
        guard records.count <= InternetMediaRecordContract.maximumFragmentsPerFrame else {
            throw EncodedInternetFrameError.tooManyRecords(
                actual: records.count,
                maximum: InternetMediaRecordContract.maximumFragmentsPerFrame
            )
        }
        guard mediaPayloadBytes >= 0 else {
            throw EncodedInternetFrameError.invalidMediaPayloadBytes(mediaPayloadBytes)
        }
        guard mediaPayloadBytes <= InternetMediaRecordContract.maximumFrameBytes else {
            throw EncodedInternetFrameError.mediaPayloadTooLarge(
                actual: mediaPayloadBytes,
                maximum: InternetMediaRecordContract.maximumFrameBytes
            )
        }

        var firstHeader: VSMediaPacketHeader?
        var decodedPayloadBytes = 0
        for (index, record) in records.enumerated() {
            guard !record.isEmpty,
                  record.count <= InternetMediaRecordContract.maximumPlaintextRecordBytes else {
                throw EncodedInternetFrameError.invalidRecordSize(
                    index: index,
                    actual: record.count,
                    maximum: InternetMediaRecordContract.maximumPlaintextRecordBytes
                )
            }
            let packet: (header: VSMediaPacketHeader, payload: Data)
            do {
                packet = try ProtocolV1MediaPacketCodec.decode(record)
            } catch {
                throw EncodedInternetFrameError.malformedRecord(index: index)
            }
            guard packet.header.fragmentCount == UInt32(records.count),
                  packet.header.fragmentIndex == UInt32(index) else {
                throw EncodedInternetFrameError.invalidFragmentLayout(index: index)
            }
            guard packet.header.captureTimestampNs == captureTimestamp,
                  packet.header.keyframe == isKeyframe else {
                throw EncodedInternetFrameError.inconsistentHeaderScope(index: index)
            }
            if let firstHeader {
                guard packet.header.streamID == firstHeader.streamID,
                      packet.header.sessionEpoch == firstHeader.sessionEpoch,
                      packet.header.configEpoch == firstHeader.configEpoch,
                      packet.header.frameID == firstHeader.frameID,
                      packet.header.fragmentCount == firstHeader.fragmentCount,
                      packet.header.captureTimestampNs == firstHeader.captureTimestampNs,
                      packet.header.keyframe == firstHeader.keyframe,
                      packet.header.codec == firstHeader.codec else {
                    throw EncodedInternetFrameError.inconsistentHeaderScope(index: index)
                }
            } else {
                firstHeader = packet.header
            }
            let (updatedPayloadBytes, overflow) = decodedPayloadBytes.addingReportingOverflow(packet.payload.count)
            guard !overflow,
                  updatedPayloadBytes <= InternetMediaRecordContract.maximumFrameBytes else {
                throw EncodedInternetFrameError.mediaPayloadTooLarge(
                    actual: overflow ? Int.max : updatedPayloadBytes,
                    maximum: InternetMediaRecordContract.maximumFrameBytes
                )
            }
            decodedPayloadBytes = updatedPayloadBytes
        }
        guard decodedPayloadBytes == mediaPayloadBytes else {
            throw EncodedInternetFrameError.mediaPayloadBytesMismatch(
                declared: mediaPayloadBytes,
                actual: decodedPayloadBytes
            )
        }

        self.records = records
        self.mediaPayloadBytes = mediaPayloadBytes
        self.captureTimestamp = captureTimestamp
        self.isKeyframe = isKeyframe
    }

    var totalEncryptedRecordBytes: UInt64 {
        records.reduce(0) {
            $0 + InternetMediaRecordContract.encryptedRecordBytes(forPlaintextBytes: $1.count)
        }
    }
}

struct InternetTransportLimits: Equatable {
    private static let standardMaximumControlMessageBytes = 1_024 * 1_024 + 64 * 1_024
    private static let standardControlBufferMessages = 4

    static let standard = InternetTransportLimits(
        maximumControlMessageBytes: standardMaximumControlMessageBytes,
        maximumBufferedControlBytes: standardMaximumControlMessageBytes * standardControlBufferMessages,
        maximumBufferedControlMessages: 256,
        maximumMediaFrameBytes: 16 * 1_024 * 1_024,
        maximumBufferedBulkBytes: 4 * 1_024 * 1_024,
        maximumBufferedBulkMessages: 64,
        maximumRelayBytesPerSession: 10 * 1_024 * 1_024 * 1_024
    )

    let maximumControlMessageBytes: Int
    let maximumBufferedControlBytes: Int
    let maximumBufferedControlMessages: Int
    let maximumMediaFrameBytes: Int
    let maximumBufferedBulkBytes: Int
    let maximumBufferedBulkMessages: Int
    let maximumRelayBytesPerSession: UInt64

    init(
        maximumControlMessageBytes: Int,
        maximumBufferedControlBytes: Int,
        maximumBufferedControlMessages: Int = 256,
        maximumMediaFrameBytes: Int,
        maximumBufferedBulkBytes: Int = 4 * 1_024 * 1_024,
        maximumBufferedBulkMessages: Int = 64,
        maximumRelayBytesPerSession: UInt64
    ) {
        self.maximumControlMessageBytes = maximumControlMessageBytes
        self.maximumBufferedControlBytes = maximumBufferedControlBytes
        self.maximumBufferedControlMessages = maximumBufferedControlMessages
        self.maximumMediaFrameBytes = maximumMediaFrameBytes
        self.maximumBufferedBulkBytes = maximumBufferedBulkBytes
        self.maximumBufferedBulkMessages = maximumBufferedBulkMessages
        self.maximumRelayBytesPerSession = maximumRelayBytesPerSession
    }
}

struct InternetTransportSnapshot: Equatable {
    let state: InternetTransportState
    let activePath: InternetPathKind?
    let controlBytesSent: UInt64
    let mediaBytesSent: UInt64
    let audioBytesSent: UInt64
    let bulkBytesSent: UInt64
    let relayBytesSent: UInt64
    let relayBytesReserved: UInt64
    let droppedMediaFrames: UInt64
    let droppedAudioRecords: UInt64
    let iceRestartCount: UInt64
    let bufferedControlBytes: Int
    let bufferedControlMessages: Int
    let bufferedBulkBytes: Int
    let bufferedBulkMessages: Int
    let mediaInFlight: Bool
    let hasPendingMediaFrame: Bool
    let audioInFlight: Bool
    let hasPendingAudioRecord: Bool
    let bulkInFlight: Bool
}

enum InternetTransportError: Error, Equatable, LocalizedError {
    case invalidConfiguration(String)
    case engineUnavailable(String)
    case notConnected
    case emptyPayload(channel: InternetTransportChannel)
    case payloadTooLarge(channel: InternetTransportChannel, actual: Int, maximum: Int)
    case controlBacklogExceeded(maximumBytes: Int)
    case bulkBacklogExceeded(maximumBytes: Int)
    case relayBudgetExceeded(maximumBytes: UInt64)
    case sequenceExhausted(String)
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
        case .bulkBacklogExceeded(let maximumBytes):
            return "Reliable bulk backlog exceeded \(maximumBytes) bytes."
        case .relayBudgetExceeded(let maximumBytes):
            return "TURN relay budget exceeded \(maximumBytes) bytes."
        case .sequenceExhausted(let sequence):
            return "The \(sequence) sequence was exhausted; the Internet transport failed closed."
        case .engineSendFailed(let reason):
            return "WebRTC engine send failed: \(reason)"
        }
    }
}
