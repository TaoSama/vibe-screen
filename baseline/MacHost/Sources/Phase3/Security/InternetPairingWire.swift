import CryptoKit
import Foundation

struct InternetPairingPublicAcceptance: Equatable {
    let accepted: Bool
    let offerID: Data
    let hostIdentity: InternetPairingPublicIdentity
    let sessionContext: Data
    let sessionKeyID: String
    let hostSignature: Data
}

enum InternetPairingURL {
    private static let maximumURLBytes = 16_384
    private static let prefix = "vibescreen://pair?v=1&o="

    static func encode(_ offer: InternetPairingOffer) throws -> URL {
        try InternetPairingCanonical.validateOffer(offer)
        let payload = try JSONEncoder().encode(OfferWire(offer))
        var components = URLComponents()
        components.scheme = "vibescreen"
        components.host = "pair"
        components.queryItems = [
            URLQueryItem(name: "v", value: "1"),
            URLQueryItem(name: "o", value: Base64URL.encode(payload))
        ]
        guard let url = components.url else { throw InternetPairingError.invalidURL }
        return url
    }

    static func parse(_ url: URL) throws -> InternetPairingOffer {
        let raw = url.absoluteString
        guard raw.utf8.count <= maximumURLBytes,
              raw.hasPrefix(prefix),
              !raw.contains("%"),
              !raw.contains("#"),
              !raw.contains("+"),
              raw.count > prefix.count else {
            throw InternetPairingError.invalidURL
        }
        let encoded = String(raw.dropFirst(prefix.count))
        guard encoded.utf8.count <= maximumURLBytes - prefix.utf8.count,
              encoded.utf8.allSatisfy({ byte in
                  (0x41...0x5a).contains(byte) ||
                    (0x61...0x7a).contains(byte) ||
                    (0x30...0x39).contains(byte) ||
                    byte == 0x2d || byte == 0x5f
              }),
              let payload = Base64URL.decode(encoded) else { throw InternetPairingError.invalidURL }
        try StrictPairingJSON.validate(payload, keys: OfferWire.expectedKeys, identities: ["host_identity"])
        let wire: OfferWire = try StrictPairingJSON.decode(payload)
        let offer = try wire.offer()
        try InternetPairingCanonical.validateOffer(offer)
        return offer
    }
}

enum InternetPairingDeviceRequestWire {
    static func encode(_ request: InternetPairingDeviceRequest) throws -> Data {
        try InternetPairingCanonical.validateIdentity(request.deviceIdentity)
        try WireValidation.validate(request)
        return try JSONEncoder().encode(DeviceRequestWire(request))
    }

    static func parse(_ data: Data) throws -> InternetPairingDeviceRequest {
        try StrictPairingJSON.validate(data, keys: DeviceRequestWire.expectedKeys, identities: ["device_identity"])
        let wire: DeviceRequestWire = try StrictPairingJSON.decode(data)
        return try wire.request()
    }
}

enum InternetPairingAcceptanceWire {
    static func encode(_ acceptance: InternetPairingAcceptance) throws -> Data {
        try WireValidation.validate(
            accepted: acceptance.accepted,
            offerID: acceptance.offerID,
            hostIdentity: acceptance.hostIdentity,
            sessionContext: acceptance.sessionContext,
            sessionKeyID: acceptance.sessionKeyID,
            hostSignature: acceptance.hostSignature
        )
        return try JSONEncoder().encode(AcceptanceWire(acceptance))
    }

    static func parse(_ data: Data) throws -> InternetPairingPublicAcceptance {
        try StrictPairingJSON.validate(data, keys: AcceptanceWire.expectedKeys, identities: ["host_identity"])
        let wire: AcceptanceWire = try StrictPairingJSON.decode(data)
        return try wire.acceptance()
    }
}

private struct OfferWire: Codable {
    static let expectedKeys: Set<String> = [
        "protocol_min", "protocol_max", "host_role", "device_role", "signature_algorithms",
        "key_agreement_algorithms", "aead_algorithms", "required_capabilities", "offer_id",
        "one_time_credential", "expires_at_unix_seconds", "host_identity", "challenge",
        "ephemeral_public_key"
    ]
    let protocolMin, protocolMax: UInt64
    let hostRole, deviceRole: String
    let signatureAlgorithms, keyAgreementAlgorithms, aeadAlgorithms, requiredCapabilities: [String]
    let offerID, oneTimeCredential: String
    let expiresAtUnixSeconds: UInt64
    let hostIdentity: IdentityWire
    let challenge, ephemeralPublicKey: String

    enum CodingKeys: String, CodingKey {
        case protocolMin = "protocol_min", protocolMax = "protocol_max"
        case hostRole = "host_role", deviceRole = "device_role"
        case signatureAlgorithms = "signature_algorithms"
        case keyAgreementAlgorithms = "key_agreement_algorithms"
        case aeadAlgorithms = "aead_algorithms", requiredCapabilities = "required_capabilities"
        case offerID = "offer_id", oneTimeCredential = "one_time_credential"
        case expiresAtUnixSeconds = "expires_at_unix_seconds", hostIdentity = "host_identity"
        case challenge, ephemeralPublicKey = "ephemeral_public_key"
    }

    init(_ value: InternetPairingOffer) {
        protocolMin = value.protocolMin; protocolMax = value.protocolMax
        hostRole = value.hostRole; deviceRole = value.deviceRole
        signatureAlgorithms = value.signatureAlgorithms; keyAgreementAlgorithms = value.keyAgreementAlgorithms
        aeadAlgorithms = value.aeadAlgorithms; requiredCapabilities = value.requiredCapabilities
        offerID = Base64URL.encode(value.offerID); oneTimeCredential = Base64URL.encode(value.oneTimeCredential)
        expiresAtUnixSeconds = value.expiresAtUnixSeconds; hostIdentity = IdentityWire(value.hostIdentity)
        challenge = Base64URL.encode(value.challenge); ephemeralPublicKey = Base64URL.encode(value.ephemeralPublicKey)
    }

    func offer() throws -> InternetPairingOffer {
        InternetPairingOffer(
            protocolMin: protocolMin, protocolMax: protocolMax, hostRole: hostRole, deviceRole: deviceRole,
            signatureAlgorithms: signatureAlgorithms, keyAgreementAlgorithms: keyAgreementAlgorithms,
            aeadAlgorithms: aeadAlgorithms, requiredCapabilities: requiredCapabilities,
            offerID: try Base64URL.required(offerID), oneTimeCredential: try Base64URL.required(oneTimeCredential),
            expiresAtUnixSeconds: expiresAtUnixSeconds, hostIdentity: try hostIdentity.identity(),
            challenge: try Base64URL.required(challenge), ephemeralPublicKey: try Base64URL.required(ephemeralPublicKey)
        )
    }
}

private struct DeviceRequestWire: Codable {
    static let expectedKeys: Set<String> = [
        "offer_id", "device_identity", "device_name", "ephemeral_public_key",
        "request_signature", "bootstrap_mac"
    ]
    let offerID: String
    let deviceIdentity: IdentityWire
    let deviceName, ephemeralPublicKey, requestSignature, bootstrapMAC: String
    enum CodingKeys: String, CodingKey {
        case offerID = "offer_id", deviceIdentity = "device_identity", deviceName = "device_name"
        case ephemeralPublicKey = "ephemeral_public_key", requestSignature = "request_signature"
        case bootstrapMAC = "bootstrap_mac"
    }
    init(_ value: InternetPairingDeviceRequest) {
        offerID = Base64URL.encode(value.offerID); deviceIdentity = IdentityWire(value.deviceIdentity)
        deviceName = value.deviceName; ephemeralPublicKey = Base64URL.encode(value.ephemeralPublicKey)
        requestSignature = Base64URL.encode(value.requestSignature); bootstrapMAC = Base64URL.encode(value.bootstrapMAC)
    }
    func request() throws -> InternetPairingDeviceRequest {
        let value = InternetPairingDeviceRequest(
            offerID: try Base64URL.required(offerID), deviceIdentity: try deviceIdentity.identity(),
            deviceName: deviceName, ephemeralPublicKey: try Base64URL.required(ephemeralPublicKey),
            requestSignature: try Base64URL.required(requestSignature), bootstrapMAC: try Base64URL.required(bootstrapMAC)
        )
        try InternetPairingCanonical.validateIdentity(value.deviceIdentity)
        try WireValidation.validate(value)
        return value
    }
}

private struct AcceptanceWire: Codable {
    static let expectedKeys: Set<String> = [
        "accepted", "offer_id", "host_identity", "session_context", "session_key_id", "host_signature"
    ]
    let accepted: Bool
    let offerID: String
    let hostIdentity: IdentityWire
    let sessionContext: String
    let sessionKeyID: String
    let hostSignature: String
    enum CodingKeys: String, CodingKey {
        case accepted, offerID = "offer_id", hostIdentity = "host_identity"
        case sessionContext = "session_context", sessionKeyID = "session_key_id", hostSignature = "host_signature"
    }
    init(_ value: InternetPairingAcceptance) {
        accepted = value.accepted; offerID = Base64URL.encode(value.offerID)
        hostIdentity = IdentityWire(value.hostIdentity); sessionContext = Base64URL.encode(value.sessionContext)
        sessionKeyID = value.sessionKeyID; hostSignature = Base64URL.encode(value.hostSignature)
    }
    func acceptance() throws -> InternetPairingPublicAcceptance {
        let identity = try hostIdentity.identity()
        try InternetPairingCanonical.validateIdentity(identity)
        let value = InternetPairingPublicAcceptance(
            accepted: accepted, offerID: try Base64URL.required(offerID), hostIdentity: identity,
            sessionContext: try Base64URL.required(sessionContext), sessionKeyID: sessionKeyID,
            hostSignature: try Base64URL.required(hostSignature)
        )
        try WireValidation.validate(
            accepted: value.accepted,
            offerID: value.offerID,
            hostIdentity: value.hostIdentity,
            sessionContext: value.sessionContext,
            sessionKeyID: value.sessionKeyID,
            hostSignature: value.hostSignature
        )
        return value
    }
}

private struct IdentityWire: Codable {
    static let expectedKeys: Set<String> = [
        "device_id", "key_id", "key_epoch", "signature_algorithm", "signing_public_key"
    ]
    let deviceID, keyID: String
    let keyEpoch: UInt64
    let signatureAlgorithm, signingPublicKey: String
    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id", keyID = "key_id", keyEpoch = "key_epoch"
        case signatureAlgorithm = "signature_algorithm", signingPublicKey = "signing_public_key"
    }
    init(_ value: InternetPairingPublicIdentity) {
        deviceID = value.deviceID; keyID = value.keyID; keyEpoch = value.keyEpoch
        signatureAlgorithm = value.signatureAlgorithm; signingPublicKey = Base64URL.encode(value.signingPublicKey)
    }
    func identity() throws -> InternetPairingPublicIdentity {
        InternetPairingPublicIdentity(
            deviceID: deviceID, keyID: keyID, keyEpoch: keyEpoch,
            signatureAlgorithm: signatureAlgorithm, signingPublicKey: try Base64URL.required(signingPublicKey)
        )
    }
}

private enum StrictPairingJSON {
    static func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw InternetPairingError.invalidURL }
    }
    static func validate(_ data: Data, keys: Set<String>, identities: [String]) throws {
        guard let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any], Set(dictionary.keys) == keys else {
            throw InternetPairingError.invalidURL
        }
        for name in identities {
            guard let identity = dictionary[name] as? [String: Any],
                  Set(identity.keys) == IdentityWire.expectedKeys else { throw InternetPairingError.invalidURL }
        }
    }
}

private enum WireValidation {
    static func validate(_ request: InternetPairingDeviceRequest) throws {
        guard request.offerID.count == 16,
              !request.deviceName.isEmpty, request.deviceName.utf8.count <= 256,
              request.ephemeralPublicKey.count == 65,
              !request.requestSignature.isEmpty, request.requestSignature.count <= 80,
              request.bootstrapMAC.count == SHA256.byteCount else {
            throw InternetPairingError.invalidOffer("Device request field sizes are invalid.")
        }
        do {
            _ = try P256.KeyAgreement.PublicKey(x963Representation: request.ephemeralPublicKey)
            _ = try P256.Signing.ECDSASignature(derRepresentation: request.requestSignature)
        } catch { throw InternetPairingError.invalidOffer("Device request cryptographic encoding is invalid.") }
    }

    static func validate(
        accepted: Bool,
        offerID: Data,
        hostIdentity: InternetPairingPublicIdentity,
        sessionContext: Data,
        sessionKeyID: String,
        hostSignature: Data
    ) throws {
        try InternetPairingCanonical.validateIdentity(hostIdentity)
        guard accepted, offerID.count == 16, sessionContext.count == SHA256.byteCount,
              sessionKeyID.count == 64,
              sessionKeyID.allSatisfy({ "0123456789abcdef".contains($0) }),
              !hostSignature.isEmpty, hostSignature.count <= 80 else {
            throw InternetPairingError.invalidOffer("Acceptance metadata is invalid.")
        }
        do { _ = try P256.Signing.ECDSASignature(derRepresentation: hostSignature) }
        catch { throw InternetPairingError.invalidOffer("Host signature encoding is invalid.") }
    }
}

private enum Base64URL {
    static func encode(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
    static func required(_ value: String) throws -> Data {
        guard let data = decode(value) else { throw InternetPairingError.invalidURL }
        return data
    }
    static func decode(_ value: String) -> Data? {
        guard !value.isEmpty, !value.contains("="), value.unicodeScalars.allSatisfy({
            CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_").contains($0)
        }) else { return nil }
        var base64 = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        base64.append(String(repeating: "=", count: (4 - base64.count % 4) % 4))
        guard let data = Data(base64Encoded: base64), encode(data) == value else { return nil }
        return data
    }
}
