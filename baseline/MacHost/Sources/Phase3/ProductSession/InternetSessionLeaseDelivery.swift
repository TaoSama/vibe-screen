import Foundation

enum InternetSessionLeaseDeliveryError: Error, Equatable, LocalizedError {
    case invalidLeaseHostKeyID
    case invalidSignature
    case invalidDeliveryPayload(String)
    case invalidProvisioningRequest(String)
    case invalidSignalingStatus(Int)

    var errorDescription: String? {
        switch self {
        case .invalidLeaseHostKeyID:
            return "Internet session lease delivery requires a host signing key ID."
        case .invalidSignature:
            return "Internet session lease delivery requires a bounded ECDSA signature."
        case .invalidDeliveryPayload(let reason):
            return "Internet session lease delivery payload is invalid: \(reason)"
        case .invalidProvisioningRequest(let reason):
            return "Internet session lease provisioning request is invalid: \(reason)"
        case .invalidSignalingStatus(let status):
            return "The signaling service returned HTTP \(status) while provisioning a session profile."
        }
    }
}

struct InternetSessionLeaseDeliveryResult: Equatable {
    let sessionID: String
    let hostSignalingToken: String
    let expiresAt: Date
    let payload: Data
}

struct InternetSessionProfileIdentity: Encodable, Equatable {
    let deviceID: String
    let keyID: String
    let keyEpoch: UInt64
    let signatureAlgorithm: String
    let signingPublicKey: String

    init(_ identity: PlatformPublicIdentity) {
        deviceID = identity.deviceID
        keyID = identity.keyID
        keyEpoch = identity.keyEpoch
        signatureAlgorithm = PlatformPublicIdentity.algorithm
        signingPublicKey = InternetSessionLeaseProvisionerBase64URL.encode(identity.signingPublicKey)
    }

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case keyID = "key_id"
        case keyEpoch = "key_epoch"
        case signatureAlgorithm = "signature_algorithm"
        case signingPublicKey = "signing_public_key"
    }
}

struct InternetSessionProfileICEServerRequest: Encodable, Equatable {
    let urls: [String]
    let username: String?
    let credential: String?
}

struct InternetSessionProfileLeaseRequest: Encodable, Equatable {
    let pairingID: String
    let hostIdentity: InternetSessionProfileIdentity
    let clientIdentity: InternetSessionProfileIdentity
    let signalingURL: String
    let transcriptContext: String
    let protocolSessionID: String
    let iceServers: [InternetSessionProfileICEServerRequest]
    let allowInsecureForTesting: Bool

    init(
        pairingID: String,
        hostIdentity: PlatformPublicIdentity,
        clientIdentity: PlatformPublicIdentity,
        signalingURL: String,
        transcriptContext: Data,
        protocolSessionID: Data,
        iceServers: [InternetSessionProfileICEServerRequest],
        allowInsecureForTesting: Bool = false
    ) {
        self.pairingID = pairingID
        self.hostIdentity = InternetSessionProfileIdentity(hostIdentity)
        self.clientIdentity = InternetSessionProfileIdentity(clientIdentity)
        self.signalingURL = signalingURL
        self.transcriptContext = transcriptContext.base64EncodedString()
        self.protocolSessionID = protocolSessionID.base64EncodedString()
        self.iceServers = iceServers
        self.allowInsecureForTesting = allowInsecureForTesting
    }

    enum CodingKeys: String, CodingKey {
        case pairingID = "pairing_id"
        case hostIdentity = "host_identity"
        case clientIdentity = "client_identity"
        case signalingURL = "signaling_url"
        case transcriptContext = "transcript_context"
        case protocolSessionID = "protocol_session_id"
        case iceServers = "ice_servers"
        case allowInsecureForTesting = "allow_insecure_for_testing"
    }
}

struct InternetSignalingSessionProfileRequest: Encodable, Equatable {
    let requestID: String
    let accountID: String
    let hostDeviceID: String
    let clientDeviceID: String
    let sessionEpoch: UInt64
    let ttlSeconds: Int64
    let sessionProfile: InternetSessionProfileLeaseRequest

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case accountID = "account_id"
        case hostDeviceID = "host_device_id"
        case clientDeviceID = "client_device_id"
        case sessionEpoch = "session_epoch"
        case ttlSeconds = "ttl_seconds"
        case sessionProfile = "session_profile"
    }
}

final class InternetSessionLeaseProvisioner {
    private let session: URLSession
    private let encoder = JSONEncoder()

    init(session: URLSession = .shared) {
        self.session = session
    }

    func createAuthoritativeLeaseDelivery(
        signalingBaseURL: URL,
        issuerToken: String,
        request: InternetSignalingSessionProfileRequest
    ) async throws -> InternetSessionLeaseDeliveryResult {
        let urlRequest = try makeCreateSessionRequest(
            signalingBaseURL: signalingBaseURL,
            issuerToken: issuerToken,
            request: request
        )
        let (data, response) = try await session.data(for: urlRequest)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 || status == 201 else {
            throw InternetSessionLeaseDeliveryError.invalidSignalingStatus(status)
        }
        return try InternetSessionLeaseDelivery.deliveryResult(
            fromSignalingSessionResponse: data,
            matching: request
        )
    }

    func makeCreateSessionRequest(
        signalingBaseURL: URL,
        issuerToken: String,
        request: InternetSignalingSessionProfileRequest
    ) throws -> URLRequest {
        guard !issuerToken.isEmpty, request.requestID.isEmpty == false,
              request.accountID.isEmpty == false, request.hostDeviceID.isEmpty == false,
              request.clientDeviceID.isEmpty == false, request.hostDeviceID != request.clientDeviceID,
              request.sessionEpoch > 0, request.ttlSeconds > 0 else {
            throw InternetSessionLeaseDeliveryError.invalidProvisioningRequest(
                "required identifiers, session epoch, or TTL are missing"
            )
        }
        var url = try Self.validatedSignalingBaseURL(signalingBaseURL)
        url.appendPathComponent("v1")
        url.appendPathComponent("sessions")
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.httpBody = try encoder.encode(request)
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(issuerToken)", forHTTPHeaderField: "Authorization")
        urlRequest.timeoutInterval = 15
        return urlRequest
    }

    private static func validatedSignalingBaseURL(_ value: URL) throws -> URL {
        guard var components = URLComponents(url: value, resolvingAgainstBaseURL: false),
              let scheme = components.scheme?.lowercased(),
              let host = components.host?.lowercased(), !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else {
            throw InternetSessionLeaseDeliveryError.invalidProvisioningRequest(
                "signaling base URL is invalid"
            )
        }
        let path = components.percentEncodedPath
        guard path.isEmpty || path == "/" else {
            throw InternetSessionLeaseDeliveryError.invalidProvisioningRequest(
                "signaling base URL must not contain a path"
            )
        }
        let isLoopbackHTTP = scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host)
        guard scheme == "https" || isLoopbackHTTP else {
            throw InternetSessionLeaseDeliveryError.invalidProvisioningRequest(
                "signaling base URL must use HTTPS or loopback HTTP"
            )
        }
        components.scheme = scheme
        components.path = ""
        guard let url = components.url else {
            throw InternetSessionLeaseDeliveryError.invalidProvisioningRequest(
                "signaling base URL is invalid"
            )
        }
        return url
    }
}

enum InternetSessionLeaseDelivery {
    static let bulkTransferID = Data("internet-bulk-v1".utf8)

    private static let version = 1
    private static let purpose = "vibescreen.session_lease.v1"
    private static let contentType = "application/vnd.vibescreen.signed-internet-session-lease+json"
    private static let rootKeys: Set<String> = [
        "version", "purpose", "content_type", "signed_lease"
    ]
    private static let signalingRootKeys: Set<String> = [
        "session_id", "host_token", "device_token", "expires_at",
        "session_profile"
    ]
    private static let signalingProfileKeys: Set<String> = [
        "account_id", "pairing_id", "signaling_session_id",
        "host_signaling_token", "expires_at", "created", "unsigned_android_lease"
    ]

    static func deliveryPayload(
        forSignedLease signedLease: Data
    ) throws -> Data {
        guard !signedLease.isEmpty,
              signedLease.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signed lease is empty or too large"
            )
        }
        let root: [String: Any] = [
            "version": version,
            "purpose": purpose,
            "content_type": contentType,
            "signed_lease": signedLease.base64EncodedString()
        ]
        let data = try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
        guard data.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "envelope exceeds the bulk record limit"
            )
        }
        return data
    }

    static func signedLease(fromDeliveryPayload payload: Data) throws -> Data {
        guard !payload.isEmpty,
              payload.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "payload is empty or too large"
            )
        }
        let object: Any
        do {
            object = try JSONSerialization.jsonObject(with: payload, options: [])
        } catch {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "payload is not valid JSON"
            )
        }
        guard let root = object as? [String: Any], Set(root.keys) == rootKeys else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "payload contains missing or unknown fields"
            )
        }
        guard (root["version"] as? NSNumber)?.intValue == version,
              root["purpose"] as? String == purpose,
              root["content_type"] as? String == contentType,
              let encodedLease = root["signed_lease"] as? String,
              encodedLease.utf8.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes,
              let signedLease = Data(base64Encoded: encodedLease),
              signedLease.base64EncodedString() == encodedLease,
              !signedLease.isEmpty,
              signedLease.count <= InternetBulkRecordContract.maximumPlaintextRecordBytes else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "payload fields are invalid"
            )
        }
        return signedLease
    }

    static func unsignedAndroidLease(
        fromSignalingSessionResponse response: Data,
        matching request: InternetSignalingSessionProfileRequest
    ) throws -> Data {
        let decoded = try decodedSignalingSessionResponse(response)
        let lease = try InternetSessionLeaseCodec.decodeUnsigned(decoded.unsignedAndroidLeaseData)
        try validate(lease: lease, response: decoded, matches: request)
        return decoded.unsignedAndroidLeaseData
    }

    static func deliveryResult(
        fromSignalingSessionResponse response: Data,
        matching request: InternetSignalingSessionProfileRequest
    ) throws -> InternetSessionLeaseDeliveryResult {
        let decoded = try decodedSignalingSessionResponse(response)
        let lease = try InternetSessionLeaseCodec.decodeUnsigned(decoded.unsignedAndroidLeaseData)
        try validate(lease: lease, response: decoded, matches: request)
        let signedLease = try issueSignedLease(decoded.unsignedAndroidLeaseData)
        let payload = try deliveryPayload(forSignedLease: signedLease)
        return InternetSessionLeaseDeliveryResult(
            sessionID: decoded.sessionID,
            hostSignalingToken: decoded.hostSignalingToken,
            expiresAt: decoded.expiresAt,
            payload: payload
        )
    }

    private static func issueSignedLease(_ unsignedLease: Data) throws -> Data {
        try InternetSessionLeaseIssuer.issue(unsignedJSON: unsignedLease)
    }

    @discardableResult
    static func send(
        _ result: InternetSessionLeaseDeliveryResult,
        on session: InternetProductSession
    ) -> Bool {
        session.sendBulkRecord(result.payload, transferID: bulkTransferID)
    }

    private static func decodedSignalingSessionResponse(
        _ response: Data
    ) throws -> DecodedSignalingSessionResponse {
        guard !response.isEmpty, response.count <= 65_536 else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signaling response is empty or too large"
            )
        }
        let object: Any
        do {
            object = try JSONSerialization.jsonObject(with: response, options: [])
        } catch {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signaling response is not valid JSON"
            )
        }
        guard let root = object as? [String: Any], Set(root.keys) == signalingRootKeys,
              let sessionID = root["session_id"] as? String, !sessionID.isEmpty,
              let hostToken = root["host_token"] as? String, hostToken.utf8.count >= 32,
              let deviceToken = root["device_token"] as? String, deviceToken.utf8.count >= 32,
              let expiresAtText = root["expires_at"] as? String,
              let expiresAt = InternetSessionLeaseDeliveryISO8601.date(from: expiresAtText),
              let profile = root["session_profile"] as? [String: Any],
              Set(profile.keys) == signalingProfileKeys,
              let accountID = profile["account_id"] as? String, !accountID.isEmpty,
              let pairingID = profile["pairing_id"] as? String, !pairingID.isEmpty,
              let profileSessionID = profile["signaling_session_id"] as? String,
              let profileHostToken = profile["host_signaling_token"] as? String,
              let profileExpiresAtText = profile["expires_at"] as? String,
              let profileExpiresAt = InternetSessionLeaseDeliveryISO8601.date(from: profileExpiresAtText),
              profile["created"] is Bool,
              let unsignedLease = profile["unsigned_android_lease"] else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signaling response omitted session_profile"
            )
        }
        guard sessionID == profileSessionID, hostToken == profileHostToken,
              expiresAt == profileExpiresAt else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signaling response profile is not bound to the admission"
            )
        }
        guard JSONSerialization.isValidJSONObject(unsignedLease) else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "unsigned Android lease is not a JSON object"
            )
        }
        let leaseData = try JSONSerialization.data(
            withJSONObject: unsignedLease,
            options: [.sortedKeys]
        )
        _ = try InternetSessionLeaseCodec.decodeUnsigned(leaseData)
        return DecodedSignalingSessionResponse(
            sessionID: sessionID,
            hostSignalingToken: hostToken,
            deviceSignalingToken: deviceToken,
            expiresAt: expiresAt,
            accountID: accountID,
            pairingID: pairingID,
            unsignedAndroidLeaseData: leaseData
        )
    }

    private static func validate(
        lease: InternetSessionLeasePayload,
        response: DecodedSignalingSessionResponse,
        matches request: InternetSignalingSessionProfileRequest
    ) throws {
        let expiresAtSeconds = response.expiresAt.timeIntervalSince1970
        guard expiresAtSeconds >= 0, expiresAtSeconds < TimeInterval(UInt64.max) else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "signaling response expiry is outside the supported range"
            )
        }
        let expectedICE = request.sessionProfile.iceServers.map {
            InternetSessionLeaseICE(urls: $0.urls, username: $0.username, credential: $0.credential)
        }
        guard response.accountID == request.accountID,
              response.pairingID == request.sessionProfile.pairingID,
              lease.pairingIdentifier == request.sessionProfile.pairingID,
              lease.pinnedHostID == request.hostDeviceID,
              lease.pinnedDeviceID == request.clientDeviceID,
              lease.leaseDeviceKeyID == request.sessionProfile.clientIdentity.keyID,
              lease.signalingURL == request.sessionProfile.signalingURL,
              lease.signalingSessionID == response.sessionID,
              lease.signalingToken == response.deviceSignalingToken,
              lease.authoritativeSessionEpoch == request.sessionEpoch,
              lease.hostIdentityEpoch == request.sessionProfile.hostIdentity.keyEpoch,
              lease.deviceIdentityEpoch == request.sessionProfile.clientIdentity.keyEpoch,
              lease.expiresAtUnixSeconds == UInt64(expiresAtSeconds),
              lease.transcriptContext.base64EncodedString() == request.sessionProfile.transcriptContext,
              lease.protocolSessionID.base64EncodedString() == request.sessionProfile.protocolSessionID,
              lease.iceServers == expectedICE,
              lease.allowInsecureForTesting == request.sessionProfile.allowInsecureForTesting else {
            throw InternetSessionLeaseDeliveryError.invalidDeliveryPayload(
                "unsigned Android lease does not match the session profile request"
            )
        }
    }
}

private struct DecodedSignalingSessionResponse {
    let sessionID: String
    let hostSignalingToken: String
    let deviceSignalingToken: String
    let expiresAt: Date
    let accountID: String
    let pairingID: String
    let unsignedAndroidLeaseData: Data
}

private enum InternetSessionLeaseDeliveryISO8601 {
    private static let formatter = ISO8601DateFormatter()

    static func date(from text: String) -> Date? {
        formatter.date(from: text)
    }
}

private enum InternetSessionLeaseProvisionerBase64URL {
    static func encode(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
