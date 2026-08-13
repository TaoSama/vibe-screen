import Foundation

struct SessionAuthorityCredential: Equatable {
    let endpoint: URL
    let sessionID: String
    let hostRoleToken: String
    let sessionEpoch: UInt64
}

struct SessionAuthorityTURNConfiguration: Equatable {
    let username: String
    let password: String
    let ttlSeconds: UInt64
    let realm: String
    let uris: [URL]

    var iceServer: WebRTCICEServer {
        WebRTCICEServer(urls: uris, username: username, credential: password)
    }
}

/// A complete replacement for one expired signaling authority lease. Callers
/// must construct the next transport solely from this value; it intentionally
/// contains no fallback reference to the previous role or TURN credentials.
struct SessionAuthorityRefresh: Equatable {
    let signaling: WebRTCSignalingConfiguration
    let sessionID: String
    let sessionEpoch: UInt64
    let expiresAt: Date
    let turn: SessionAuthorityTURNConfiguration?
}

enum SessionAuthorityClientError: Error, Equatable, LocalizedError {
    case invalidRequest(String)
    case transportFailure(String)
    case invalidResponse(String)
    case rejected(status: Int)

    var isRetryable: Bool {
        switch self {
        case .transportFailure:
            return true
        case .rejected(let status):
            return status == 408 || status == 425 || status == 429 || (500...599).contains(status)
        case .invalidRequest, .invalidResponse:
            return false
        }
    }

    var errorDescription: String? {
        switch self {
        case .invalidRequest(let reason): return reason
        case .transportFailure: return "The session authority is temporarily unreachable."
        case .invalidResponse(let reason): return reason
        case .rejected(let status): return "The session authority rejected the request with HTTP \(status)."
        }
    }
}

protocol SessionAuthorityClientPort {
    func refresh(_ current: SessionAuthorityCredential) async throws -> SessionAuthorityRefresh
    func revoke(
        _ current: SessionAuthorityCredential,
        deviceID: String,
        signedTombstone: Data?
    ) async throws
}

final class HTTPSessionAuthorityClient: SessionAuthorityClientPort {
    private struct RefreshWire: Decodable {
        let sessionID: String
        let roleToken: String
        let sessionEpoch: UInt64
        let expiresAt: String
        let turn: TURNWire?

        enum CodingKeys: String, CodingKey {
            case sessionID = "session_id"
            case roleToken = "role_token"
            case sessionEpoch = "session_epoch"
            case expiresAt = "expires_at"
            case turn
        }
    }

    private struct TURNWire: Decodable {
        let username: String
        let password: String
        let ttlSeconds: UInt64
        let realm: String
        let uris: [String]

        enum CodingKeys: String, CodingKey {
            case username, password, realm, uris
            case ttlSeconds = "ttl_seconds"
        }
    }

    private struct RevokeWire: Encodable {
        let deviceID: String
        let tombstone: String?

        enum CodingKeys: String, CodingKey {
            case deviceID = "device_id"
            case tombstone
        }
    }

    private struct RevokeResponseWire: Decodable {
        let status: String
    }

    private static let refreshKeys: Set<String> = [
        "session_id", "role_token", "session_epoch", "expires_at", "turn"
    ]
    private static let turnKeys: Set<String> = [
        "username", "password", "ttl_seconds", "realm", "uris"
    ]
    private static let revokeResponseKeys: Set<String> = ["status"]
    private static let maximumResponseBytes = 64 * 1024
    private static let maximumIdentifierBytes = 256
    private static let maximumSecretBytes = 8 * 1024
    private static let maximumTURNURIs = 16

    private let session: URLSession
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(session: URLSession = .shared) {
        self.session = session
    }

    func refresh(_ current: SessionAuthorityCredential) async throws -> SessionAuthorityRefresh {
        try validate(current)
        let request = try authorityRequest(
            current,
            action: "refresh",
            body: Data("{}".utf8)
        )
        let data = try await execute(request, acceptedStatuses: [200, 201])
        try validateJSONObject(data, allowedKeys: Self.refreshKeys, nestedTURN: true)

        let wire: RefreshWire
        do {
            wire = try decoder.decode(RefreshWire.self, from: data)
        } catch {
            throw SessionAuthorityClientError.invalidResponse("The refresh response is malformed.")
        }
        guard validAuthorityIdentifier(wire.sessionID),
              validBounded(wire.roleToken, maximumBytes: Self.maximumSecretBytes),
              wire.sessionID != current.sessionID,
              wire.roleToken != current.hostRoleToken,
              current.sessionEpoch < SecurityLifecycle.maximumCrossPlatformSessionEpoch,
              wire.sessionEpoch == current.sessionEpoch + 1,
              wire.sessionEpoch <= SecurityLifecycle.maximumCrossPlatformSessionEpoch,
              let expiresAt = parseDate(wire.expiresAt),
              expiresAt > Date() else {
            throw SessionAuthorityClientError.invalidResponse(
                "The authority did not issue a fresh bounded session credential."
            )
        }

        let turn = try wire.turn.map { try decodeTURN($0) }
        return SessionAuthorityRefresh(
            signaling: WebRTCSignalingConfiguration(
                endpoint: current.endpoint,
                bearerToken: wire.roleToken,
                role: .offerer
            ),
            sessionID: wire.sessionID,
            sessionEpoch: wire.sessionEpoch,
            expiresAt: expiresAt,
            turn: turn
        )
    }

    func revoke(
        _ current: SessionAuthorityCredential,
        deviceID: String,
        signedTombstone: Data?
    ) async throws {
        try validate(current)
        guard validAuthorityIdentifier(deviceID),
              signedTombstone?.isEmpty != true,
              (signedTombstone?.count ?? 0) <= Self.maximumResponseBytes else {
            throw SessionAuthorityClientError.invalidRequest("The revoke target or tombstone is invalid.")
        }
        let body: Data
        do {
            body = try encoder.encode(RevokeWire(
                deviceID: deviceID,
                tombstone: signedTombstone?.base64EncodedString()
            ))
        } catch {
            throw SessionAuthorityClientError.invalidRequest("The revoke request could not be encoded.")
        }
        let request = try authorityRequest(current, action: "revoke", body: body)
        let data = try await execute(request, acceptedStatuses: [200])
        try validateJSONObject(data, allowedKeys: Self.revokeResponseKeys, nestedTURN: false)
        let response: RevokeResponseWire
        do {
            response = try decoder.decode(RevokeResponseWire.self, from: data)
        } catch {
            throw SessionAuthorityClientError.invalidResponse("The revoke response is malformed.")
        }
        guard response.status == "revoked" else {
            throw SessionAuthorityClientError.invalidResponse("The authority did not confirm revocation.")
        }
    }

    private func authorityRequest(
        _ current: SessionAuthorityCredential,
        action: String,
        body: Data
    ) throws -> URLRequest {
        let url = current.endpoint
            .appendingPathComponent("v1/sessions")
            .appendingPathComponent(current.sessionID)
            .appendingPathComponent(action)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(current.hostRoleToken)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func execute(_ request: URLRequest, acceptedStatuses: Set<Int>) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            if (error as NSError).code == NSURLErrorCancelled {
                throw CancellationError()
            }
            throw SessionAuthorityClientError.transportFailure("network")
        }
        guard let http = response as? HTTPURLResponse,
              http.url == request.url else {
            throw SessionAuthorityClientError.invalidResponse("The authority returned a non-HTTP response.")
        }
        guard acceptedStatuses.contains(http.statusCode) else {
            throw SessionAuthorityClientError.rejected(status: http.statusCode)
        }
        guard data.count <= Self.maximumResponseBytes else {
            throw SessionAuthorityClientError.invalidResponse("The authority response is too large.")
        }
        return data
    }

    private func validate(_ credential: SessionAuthorityCredential) throws {
        guard DisplaySettings.isSafeInternetSignalingEndpoint(credential.endpoint.absoluteString),
              validAuthorityIdentifier(credential.sessionID),
              validBounded(credential.hostRoleToken, maximumBytes: Self.maximumSecretBytes),
              credential.sessionEpoch > 0,
              credential.sessionEpoch <= SecurityLifecycle.maximumCrossPlatformSessionEpoch else {
            throw SessionAuthorityClientError.invalidRequest(
                "A safe signaling endpoint and current bounded host credential are required."
            )
        }
    }

    private func validateJSONObject(
        _ data: Data,
        allowedKeys: Set<String>,
        nestedTURN: Bool
    ) throws {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(root.keys).isSubset(of: allowedKeys) else {
            throw SessionAuthorityClientError.invalidResponse("The authority response has an invalid shape.")
        }
        if nestedTURN, let value = root["turn"], !(value is NSNull) {
            guard let turn = value as? [String: Any],
                  Set(turn.keys).isSubset(of: Self.turnKeys) else {
                throw SessionAuthorityClientError.invalidResponse("The TURN response has an invalid shape.")
            }
        }
    }

    private func decodeTURN(_ wire: TURNWire) throws -> SessionAuthorityTURNConfiguration {
        guard validBounded(wire.username, maximumBytes: Self.maximumSecretBytes),
              validBounded(wire.password, maximumBytes: Self.maximumSecretBytes),
              validBounded(wire.realm, maximumBytes: Self.maximumIdentifierBytes),
              wire.ttlSeconds > 0,
              !wire.uris.isEmpty,
              wire.uris.count <= Self.maximumTURNURIs else {
            throw SessionAuthorityClientError.invalidResponse("The TURN credential is invalid.")
        }
        let urls = try wire.uris.map { raw -> URL in
            guard let url = URL(string: raw),
                  ["turn", "turns"].contains(url.scheme?.lowercased() ?? ""),
                  !raw.contains("@") else {
                throw SessionAuthorityClientError.invalidResponse("The TURN URI is invalid.")
            }
            return url
        }
        return SessionAuthorityTURNConfiguration(
            username: wire.username,
            password: wire.password,
            ttlSeconds: wire.ttlSeconds,
            realm: wire.realm,
            uris: urls
        )
    }

    private func validBounded(_ value: String, maximumBytes: Int) -> Bool {
        !value.isEmpty
            && value.utf8.count <= maximumBytes
            && value.unicodeScalars.allSatisfy { !$0.properties.isControl }
    }

    private func validAuthorityIdentifier(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 128 && value.utf8.allSatisfy { byte in
            (0x61...0x7a).contains(byte)
                || (0x41...0x5a).contains(byte)
                || (0x30...0x39).contains(byte)
                || byte == 0x2d || byte == 0x5f || byte == 0x2e
        }
    }

    private func parseDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
}

/// Serializes authority operations and lets lifecycle owners invalidate an
/// in-flight result before applying any replacement credentials.
actor SessionAuthorityCoordinator {
    struct RefreshResult: Equatable {
        let generation: UInt64
        let replacement: SessionAuthorityRefresh
    }

    private let client: SessionAuthorityClientPort
    private var generation: UInt64 = 0

    init(client: SessionAuthorityClientPort) {
        self.client = client
    }

    @discardableResult
    func invalidatePendingOperations() -> UInt64 {
        generation &+= 1
        return generation
    }

    func refresh(_ current: SessionAuthorityCredential) async throws -> RefreshResult {
        generation &+= 1
        let requestedGeneration = generation
        let replacement = try await client.refresh(current)
        guard requestedGeneration == generation, !Task.isCancelled else {
            throw CancellationError()
        }
        return RefreshResult(generation: requestedGeneration, replacement: replacement)
    }

    func revoke(
        _ current: SessionAuthorityCredential,
        deviceID: String,
        signedTombstone: Data?
    ) async throws {
        generation &+= 1
        let requestedGeneration = generation
        try await client.revoke(current, deviceID: deviceID, signedTombstone: signedTombstone)
        guard requestedGeneration == generation, !Task.isCancelled else {
            throw CancellationError()
        }
    }
}
