import Foundation

enum InternetProductSessionState: Equatable {
    case idle
    case connecting
    case authenticating
    case awaitingVideoConfiguration
    case streaming(InternetPathKind)
    case recovering(attempt: Int)
    case failed(String)
    case revoked
    case closed
}

enum InternetSessionInputCleanupScope: Equatable {
    case preserve
    case transientOnly
    case fullSessionReset

    func apply(
        transientReset: () -> Void,
        fullSessionReset: () -> Void
    ) {
        switch self {
        case .preserve:
            break
        case .transientOnly:
            transientReset()
        case .fullSessionReset:
            fullSessionReset()
        }
    }
}

extension InternetProductSessionState {
    var inputCleanupScope: InternetSessionInputCleanupScope {
        switch self {
        case .streaming:
            return .preserve
        case .awaitingVideoConfiguration:
            return .transientOnly
        case .idle, .connecting, .authenticating, .recovering,
             .failed, .revoked, .closed:
            return .fullSessionReset
        }
    }

}

enum InternetProductSessionError: Error, Equatable, LocalizedError {
    case invalidConfiguration(String)
    case protocolFailure(InternetProductProtocolError)
    case transportFailure(InternetTransportError)
    case securityFailure(String)
    case revoked

    var errorDescription: String? {
        switch self {
        case .invalidConfiguration(let reason), .securityFailure(let reason): return reason
        case .protocolFailure(let error): return error.localizedDescription
        case .transportFailure(let error): return error.localizedDescription
        case .revoked: return "The paired Internet device has been revoked."
        }
    }
}

struct InternetProductSessionConfiguration {
    let transport: WebRTCTransportConfiguration
    let hostDeviceID: String
    let hostName: String
    let peerDeviceID: String
    let peerIdentity: PlatformPublicIdentity
    let authoritativeSessionEpoch: UInt64
    let identityEpoch: UInt64
    let sharedSecretName: String
    let bootstrapSecretName: String
    let transcriptContext: Data
    let video: InternetProductVideoConfiguration
    let inputEnabled: Bool
    let controllerAvailable: Bool
    let fileTransferPolicy: ProtocolV1FileTransferPolicy
    let heartbeatIntervalMilliseconds: UInt32
    let heartbeatTimeoutMilliseconds: UInt32
    let negotiationTimeoutMilliseconds: UInt32
    let limits: InternetTransportLimits

    init(
        transport: WebRTCTransportConfiguration,
        hostDeviceID: String,
        hostName: String,
        peerDeviceID: String,
        peerIdentity: PlatformPublicIdentity,
        authoritativeSessionEpoch: UInt64,
        identityEpoch: UInt64 = PlatformPublicIdentity.initialKeyEpoch,
        sharedSecretName: String,
        bootstrapSecretName: String,
        transcriptContext: Data,
        video: InternetProductVideoConfiguration,
        inputEnabled: Bool = true,
        controllerAvailable: Bool = false,
        fileTransferPolicy: ProtocolV1FileTransferPolicy = .default,
        heartbeatIntervalMilliseconds: UInt32 = 1_000,
        heartbeatTimeoutMilliseconds: UInt32 = 5_000,
        negotiationTimeoutMilliseconds: UInt32 = 10_000,
        limits: InternetTransportLimits = .standard
    ) {
        self.transport = transport
        self.hostDeviceID = hostDeviceID
        self.hostName = hostName
        self.peerDeviceID = peerDeviceID
        self.peerIdentity = peerIdentity
        self.authoritativeSessionEpoch = authoritativeSessionEpoch
        self.identityEpoch = identityEpoch
        self.sharedSecretName = sharedSecretName
        self.bootstrapSecretName = bootstrapSecretName
        self.transcriptContext = transcriptContext
        self.video = video
        self.inputEnabled = inputEnabled
        self.controllerAvailable = controllerAvailable
        self.fileTransferPolicy = fileTransferPolicy
        self.heartbeatIntervalMilliseconds = heartbeatIntervalMilliseconds
        self.heartbeatTimeoutMilliseconds = heartbeatTimeoutMilliseconds
        self.negotiationTimeoutMilliseconds = negotiationTimeoutMilliseconds
        self.limits = limits
    }

    func validate() throws {
        try transport.validate()
        try video.validate()
        guard !hostDeviceID.isEmpty, !peerDeviceID.isEmpty,
              peerIdentity.deviceID == peerDeviceID,
              transport.peerIdentity == peerIdentity.keyID,
              !peerIdentity.keyID.isEmpty,
              peerIdentity.keyEpoch > 0,
              peerIdentity.signingPublicKey.count == 65,
              peerIdentity.signingPublicKey.first == 0x04,
              authoritativeSessionEpoch > 0,
              authoritativeSessionEpoch <= SecurityLifecycle.maximumCrossPlatformSessionEpoch,
              identityEpoch > 0,
              !sharedSecretName.isEmpty, !bootstrapSecretName.isEmpty,
              transcriptContext.count == 32,
              heartbeatIntervalMilliseconds > 0,
              heartbeatTimeoutMilliseconds >= heartbeatIntervalMilliseconds,
              negotiationTimeoutMilliseconds > 0 else {
            throw InternetProductSessionError.invalidConfiguration(
                "Internet product session identity, secrets, transcript, and heartbeat settings are invalid."
            )
        }
    }

    /// Binds pairing output to this exact authoritative product session. Both
    /// endpoints derive this value from the same ordered host/device roles.
    var boundTranscriptContext: Data {
        SecurityTranscript.digest(
            domain: "vibescreen/product-session-context/v1",
            parts: [
                transcriptContext,
                Data(transport.sessionIdentifier.utf8),
                SecurityTranscript.uint64(authoritativeSessionEpoch),
                Data(hostDeviceID.utf8),
                Data(peerDeviceID.utf8),
                SecurityTranscript.uint64(UInt64(PlatformSenderRole.host.rawValue)),
                SecurityTranscript.uint64(UInt64(PlatformSenderRole.device.rawValue)),
            ]
        )
    }

    var peerSecurityScopeID: String {
        PairedDeviceSecurityScope.identifier(peerIdentity)
    }
}

struct InternetProductSecuritySession {
    let sessionEpoch: UInt64
    let packetCipher: PlatformSessionPacketCipher
    private let cleanup: () throws -> Void

    init(
        sessionEpoch: UInt64,
        packetCipher: PlatformSessionPacketCipher,
        cleanup: (() throws -> Void)? = nil
    ) {
        self.sessionEpoch = sessionEpoch
        self.packetCipher = packetCipher
        self.cleanup = cleanup ?? { packetCipher.close() }
    }

    func close() throws { try cleanup() }
}
