import CryptoKit
import Foundation
import Security

enum InternetPairingError: Error, Equatable, LocalizedError {
    case invalidURL
    case invalidOffer(String)
    case offerExpired
    case offerAlreadyConsumed
    case downgradeDetected
    case invalidDeviceSignature
    case invalidBootstrapMAC
    case persistenceFailure(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "The Internet pairing URL is invalid."
        case .invalidOffer(let reason): return "The Internet pairing offer is invalid: \(reason)"
        case .offerExpired: return "The Internet pairing offer has expired."
        case .offerAlreadyConsumed: return "The Internet pairing offer was already consumed."
        case .downgradeDetected: return "The Internet pairing algorithms or capabilities were downgraded."
        case .invalidDeviceSignature: return "The device pairing signature is invalid."
        case .invalidBootstrapMAC: return "The one-time pairing credential proof is invalid."
        case .persistenceFailure(let reason): return "Unable to persist the paired-device secrets: \(reason)"
        }
    }
}

struct InternetPairingPublicIdentity: Codable, Equatable {
    let deviceID: String
    let keyID: String
    let keyEpoch: UInt64
    let signatureAlgorithm: String
    let signingPublicKey: Data

    init(
        deviceID: String,
        keyID: String,
        keyEpoch: UInt64,
        signatureAlgorithm: String = PlatformPublicIdentity.algorithm,
        signingPublicKey: Data
    ) {
        self.deviceID = deviceID
        self.keyID = keyID
        self.keyEpoch = keyEpoch
        self.signatureAlgorithm = signatureAlgorithm
        self.signingPublicKey = signingPublicKey
    }

    init(_ identity: PlatformPublicIdentity) {
        self.init(
            deviceID: identity.deviceID,
            keyID: identity.keyID,
            keyEpoch: identity.keyEpoch,
            signingPublicKey: identity.signingPublicKey
        )
    }
}

protocol InternetPairingSigner {
    var pairingPublicIdentity: InternetPairingPublicIdentity { get }
    func signPairingDigest(_ digest: Data) throws -> Data
}

extension KeychainDeviceIdentity: InternetPairingSigner {
    var pairingPublicIdentity: InternetPairingPublicIdentity {
        InternetPairingPublicIdentity(publicIdentity)
    }

    func signPairingDigest(_ digest: Data) throws -> Data {
        try signTranscriptDigest(digest)
    }
}

protocol InternetPairingSecretStore {
    func load(name: String) throws -> Data?
    func persist(name: String, secret: Data) throws
    func delete(name: String) throws
    func names(prefix: String) throws -> [String]
}

extension InternetPairingSecretStore {
    func names(prefix _: String) throws -> [String] { [] }
}

extension KeychainSecretStore: InternetPairingSecretStore {}

struct InternetPairingOffer: Equatable {
    let protocolMin: UInt64
    let protocolMax: UInt64
    let hostRole: String
    let deviceRole: String
    let signatureAlgorithms: [String]
    let keyAgreementAlgorithms: [String]
    let aeadAlgorithms: [String]
    let requiredCapabilities: [String]
    let offerID: Data
    let oneTimeCredential: Data
    let expiresAtUnixSeconds: UInt64
    let hostIdentity: InternetPairingPublicIdentity
    let challenge: Data
    let ephemeralPublicKey: Data
}

struct InternetPairingCreatedOffer: Equatable {
    let offer: InternetPairingOffer
    let url: URL
}

struct InternetPairingDeviceRequest: Equatable {
    let offerID: Data
    let deviceIdentity: InternetPairingPublicIdentity
    let deviceName: String
    let ephemeralPublicKey: Data
    let requestSignature: Data
    let bootstrapMAC: Data
}

/// Public acceptance metadata. Derived shared/bootstrap secrets are persisted
/// directly to the injected store and are deliberately absent from this value.
struct InternetPairingAcceptance: Equatable {
    let accepted: Bool
    let offerID: Data
    let pairingIdentifier: String
    let hostIdentity: InternetPairingPublicIdentity
    let deviceIdentity: InternetPairingPublicIdentity
    let deviceName: String
    let sessionContext: Data
    let sessionKeyID: String
    let hostSignature: Data
    let secretNames: PairedDeviceSecretNames
}

struct PendingPairingPersistenceContext: Equatable {
    let peerSecurityScopeID: String
    let pairingIdentifier: String
}

final class InternetPairingCoordinator {
    static let protocolVersion: UInt64 = 1
    static let signatureAlgorithms = ["ECDSA_P256_SHA256"]
    static let keyAgreementAlgorithms = ["ECDH_P256"]
    static let aeadAlgorithms = ["AES_256_GCM"]
    static let requiredCapabilities = [
        "application_e2ee",
        "audio_data_channel",
        "bulk_data_channel",
        "control_data_channel",
        "media_data_channel",
        "peer_identity"
    ]

    private struct PendingOffer {
        let offer: InternetPairingOffer
        let ephemeralPrivateKey: P256.KeyAgreement.PrivateKey
    }

    private let signer: any InternetPairingSigner
    private let secretStore: any InternetPairingSecretStore
    private let now: () -> Date
    private let randomBytes: (Int) throws -> Data
    private let lock = NSLock()
    private var pendingOffers: [Data: PendingOffer] = [:]

    init(
        signer: any InternetPairingSigner,
        secretStore: any InternetPairingSecretStore = KeychainSecretStore(),
        now: @escaping () -> Date = Date.init,
        randomBytes: @escaping (Int) throws -> Data = InternetPairingCoordinator.secureRandomBytes
    ) {
        self.signer = signer
        self.secretStore = secretStore
        self.now = now
        self.randomBytes = randomBytes
    }

    func createOffer(validFor lifetime: TimeInterval = 120) throws -> InternetPairingCreatedOffer {
        try retryPendingPersistenceCleanup()
        guard lifetime > 0, lifetime <= 600 else {
            throw InternetPairingError.invalidOffer("Offer lifetime must be between 1 and 600 seconds.")
        }
        let identity = signer.pairingPublicIdentity
        try InternetPairingCanonical.validateIdentity(identity)
        let ephemeral = P256.KeyAgreement.PrivateKey()
        let offer = InternetPairingOffer(
            protocolMin: Self.protocolVersion,
            protocolMax: Self.protocolVersion,
            hostRole: "host",
            deviceRole: "device",
            signatureAlgorithms: Self.signatureAlgorithms,
            keyAgreementAlgorithms: Self.keyAgreementAlgorithms,
            aeadAlgorithms: Self.aeadAlgorithms,
            requiredCapabilities: Self.requiredCapabilities,
            offerID: try randomBytes(16),
            oneTimeCredential: try randomBytes(32),
            expiresAtUnixSeconds: UInt64(now().timeIntervalSince1970 + lifetime),
            hostIdentity: identity,
            challenge: try randomBytes(32),
            ephemeralPublicKey: ephemeral.publicKey.x963Representation
        )
        try InternetPairingCanonical.validateOffer(offer)
        let url = try InternetPairingURL.encode(offer)
        try lock.withPairingLock {
            guard pendingOffers[offer.offerID] == nil else {
                throw InternetPairingError.invalidOffer("A random offer identifier was reused.")
            }
            pendingOffers[offer.offerID] = PendingOffer(offer: offer, ephemeralPrivateKey: ephemeral)
        }
        return InternetPairingCreatedOffer(offer: offer, url: url)
    }

    func accept(_ request: InternetPairingDeviceRequest) throws -> InternetPairingAcceptance {
        // Removal and lookup share one critical section: every attempt consumes
        // the credential, including malformed attempts, so it cannot be raced
        // or used as an online signature/MAC oracle.
        let pending = try lock.withPairingLock { () throws -> PendingOffer in
            guard let value = pendingOffers.removeValue(forKey: request.offerID) else {
                throw InternetPairingError.offerAlreadyConsumed
            }
            return value
        }
        let offer = pending.offer
        guard UInt64(now().timeIntervalSince1970) < offer.expiresAtUnixSeconds else {
            throw InternetPairingError.offerExpired
        }
        try InternetPairingCanonical.validateNegotiation(offer)
        try InternetPairingCanonical.validateIdentity(request.deviceIdentity)
        guard request.offerID == offer.offerID,
              !request.deviceName.isEmpty, request.deviceName.utf8.count <= 256,
              request.ephemeralPublicKey.count == 65,
              request.requestSignature.count <= 80,
              request.bootstrapMAC.count == SHA256.byteCount else {
            throw InternetPairingError.invalidOffer("Device response sizes are invalid.")
        }

        let parts = InternetPairingCanonical.transcriptParts(offer: offer, request: request)
        let requestDigest = SecurityTranscript.digest(domain: "vibescreen/pairing-request/v1", parts: parts)
        guard InternetPairingCanonical.verify(
            signature: request.requestSignature,
            digest: requestDigest,
            publicKey: request.deviceIdentity.signingPublicKey
        ) else { throw InternetPairingError.invalidDeviceSignature }

        let bootstrapDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-bootstrap/v1",
            parts: parts + [request.requestSignature]
        )
        guard HMAC<SHA256>.isValidAuthenticationCode(
            request.bootstrapMAC,
            authenticating: bootstrapDigest,
            using: SymmetricKey(data: offer.oneTimeCredential)
        ) else { throw InternetPairingError.invalidBootstrapMAC }
        let deviceEphemeral: P256.KeyAgreement.PublicKey
        do { deviceEphemeral = try P256.KeyAgreement.PublicKey(x963Representation: request.ephemeralPublicKey) }
        catch { throw InternetPairingError.invalidOffer("Device ECDH public key is invalid.") }
        let ecdh: SharedSecret
        do { ecdh = try pending.ephemeralPrivateKey.sharedSecretFromKeyAgreement(with: deviceEphemeral) }
        catch { throw InternetPairingError.invalidOffer("ECDH agreement failed.") }
        let derived = InternetPairingCanonical.derive(ecdh: ecdh, oneTime: offer.oneTimeCredential, parts: parts)
        let pairingIdentifier = InternetPairingCanonical.hexDigest(offer.offerID)
        let names = try PairedDeviceSecretNames(
            sharedSecret: "pairing.\(pairingIdentifier).shared.v1",
            bootstrapSecret: "pairing.\(pairingIdentifier).bootstrap.v1",
            identityBinding: PairedHostIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            peerIdentityBinding: PairedPeerIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            pairingIdentifier: pairingIdentifier
        )

        let acceptanceDigest = SecurityTranscript.digest(
            domain: "vibescreen/pairing-result/v1",
            parts: parts + [
                request.requestSignature,
                request.bootstrapMAC,
                Data([0x01]),
                Data(derived.sessionKeyID.utf8)
            ]
        )
        let signature = try signer.signPairingDigest(acceptanceDigest)
        try persist(
            derived: derived,
            hostIdentity: PlatformPublicIdentity(
                deviceID: offer.hostIdentity.deviceID,
                keyID: offer.hostIdentity.keyID,
                keyEpoch: offer.hostIdentity.keyEpoch,
                signingPublicKey: offer.hostIdentity.signingPublicKey
            ),
            peerIdentity: PlatformPublicIdentity(
                deviceID: request.deviceIdentity.deviceID,
                keyID: request.deviceIdentity.keyID,
                keyEpoch: request.deviceIdentity.keyEpoch,
                signingPublicKey: request.deviceIdentity.signingPublicKey
            ),
            names: names,
            peerSecurityScopeID: PairedDeviceSecurityScope.identifier(
                PlatformPublicIdentity(
                    deviceID: request.deviceIdentity.deviceID,
                    keyID: request.deviceIdentity.keyID,
                    keyEpoch: request.deviceIdentity.keyEpoch,
                    signingPublicKey: request.deviceIdentity.signingPublicKey
                )
            ),
            pairingIdentifier: pairingIdentifier
        )
        return InternetPairingAcceptance(
            accepted: true,
            offerID: offer.offerID,
            pairingIdentifier: pairingIdentifier,
            hostIdentity: offer.hostIdentity,
            deviceIdentity: request.deviceIdentity,
            deviceName: request.deviceName,
            sessionContext: derived.sessionContext,
            sessionKeyID: derived.sessionKeyID,
            hostSignature: signature,
            secretNames: names
        )
    }

    private func persist(
        derived: InternetPairingDerivedSecrets,
        hostIdentity: PlatformPublicIdentity,
        peerIdentity: PlatformPublicIdentity,
        names: PairedDeviceSecretNames,
        peerSecurityScopeID: String,
        pairingIdentifier: String
    ) throws {
        guard let identityBindingName = names.identityBinding,
              let peerIdentityBindingName = names.peerIdentityBinding else {
            throw InternetPairingError.persistenceFailure(
                "The paired host identity binding name is missing."
            )
        }
        let marker = PairingPersistenceCleanupMarker(
            remainingSecretNames: [
                names.sharedSecret,
                names.bootstrapSecret,
                identityBindingName,
                peerIdentityBindingName
            ],
            peerSecurityScopeID: peerSecurityScopeID,
            pairingIdentifier: pairingIdentifier
        )
        do {
            try secretStore.persist(
                name: Self.persistenceCleanupMarkerName(pairingIdentifier),
                secret: try JSONEncoder().encode(marker)
            )
            try secretStore.persist(name: names.sharedSecret, secret: derived.sharedSecret)
            try secretStore.persist(name: names.bootstrapSecret, secret: derived.bootstrapSecret)
            try secretStore.persist(
                name: identityBindingName,
                secret: PairedHostIdentityBinding.encode(hostIdentity)
            )
            try secretStore.persist(
                name: peerIdentityBindingName,
                secret: PairedPeerIdentityBinding.encode(peerIdentity)
            )
        } catch {
            var cleanupFailures: [Error] = []
            for name in marker.remainingSecretNames {
                do { try secretStore.delete(name: name) }
                catch { cleanupFailures.append(error) }
            }
            if cleanupFailures.isEmpty {
                do {
                    try secretStore.delete(
                        name: Self.persistenceCleanupMarkerName(pairingIdentifier)
                    )
                }
                catch { cleanupFailures.append(error) }
            }
            let details = cleanupFailures.map(\.localizedDescription).joined(separator: "; ")
            throw InternetPairingError.persistenceFailure(
                details.isEmpty
                    ? error.localizedDescription
                    : "\(error.localizedDescription); durable pairing cleanup remains pending: \(details)"
            )
        }
    }

    func commitPersistence(secretNames: PairedDeviceSecretNames) throws {
        guard let encoded = try secretStore.load(
            name: Self.persistenceCleanupMarkerName(
                try Self.requiredPairingIdentifier(secretNames)
            )
        ) else {
            throw InternetPairingError.persistenceFailure(
                "The pairing persistence transaction marker is missing."
            )
        }
        let marker = try Self.decodePersistenceCleanupMarker(encoded)
        guard let identityBindingName = secretNames.identityBinding,
              let peerIdentityBindingName = secretNames.peerIdentityBinding,
              Set(marker.remainingSecretNames) == Set([
                secretNames.sharedSecret,
                secretNames.bootstrapSecret,
                identityBindingName,
                peerIdentityBindingName
              ]) else {
            throw InternetPairingError.persistenceFailure(
                "The pairing persistence transaction targets another secret set."
            )
        }
        try secretStore.delete(
            name: Self.persistenceCleanupMarkerName(
                try Self.requiredPairingIdentifier(secretNames)
            )
        )
    }

    func completePersistence(
        secretNames: PairedDeviceSecretNames,
        commitBusinessState: () throws -> Void,
        cleanupBusinessState: () throws -> Void
    ) throws {
        do {
            try commitBusinessState()
            try commitPersistence(secretNames: secretNames)
        } catch {
            let businessError = error
            do {
                let recovered = try Self.retryPendingPersistenceCleanup(
                    pairingIdentifier: try Self.requiredPairingIdentifier(
                        secretNames
                    ),
                    secretStore: secretStore,
                    cleanupBusinessState: cleanupBusinessState
                )
                if !recovered { try cleanupBusinessState() }
            } catch let cleanupError {
                throw InternetPairingError.persistenceFailure(
                    "\(businessError.localizedDescription); cleanup remains pending: \(cleanupError.localizedDescription)"
                )
            }
            throw businessError
        }
    }

    @discardableResult
    func retryPendingPersistenceCleanup(
        cleanupBusinessState: () throws -> Void = {}
    ) throws -> Bool {
        try Self.retryPendingPersistenceCleanup(
            secretStore: secretStore,
            cleanupBusinessState: cleanupBusinessState
        )
    }

    @discardableResult
    static func retryPendingPersistenceCleanup(
        secretStore: any InternetPairingSecretStore = KeychainSecretStore(),
        cleanupBusinessState: () throws -> Void = {}
    ) throws -> Bool {
        let markerNames = try secretStore.names(
            prefix: Self.persistenceCleanupMarkerPrefix
        )
        var recovered = false
        for markerName in markerNames.sorted() {
            guard let encoded = try secretStore.load(name: markerName) else { continue }
            let marker = try Self.decodePersistenceCleanupMarker(encoded)
            try Self.retryPendingPersistenceCleanup(
                markerName: markerName,
                marker: marker,
                secretStore: secretStore,
                cleanupBusinessState: cleanupBusinessState
            )
            recovered = true
        }
        return recovered
    }

    @discardableResult
    static func retryPendingPersistenceCleanup(
        pairingIdentifier: String,
        secretStore: any InternetPairingSecretStore = KeychainSecretStore(),
        cleanupBusinessState: () throws -> Void = {}
    ) throws -> Bool {
        let markerName = Self.persistenceCleanupMarkerName(pairingIdentifier)
        guard let encoded = try secretStore.load(name: markerName) else { return false }
        let marker = try Self.decodePersistenceCleanupMarker(encoded)
        guard marker.pairingIdentifier == pairingIdentifier else {
            throw InternetPairingError.persistenceFailure(
                "The pairing cleanup marker owner is invalid."
            )
        }
        try Self.retryPendingPersistenceCleanup(
            markerName: markerName,
            marker: marker,
            secretStore: secretStore,
            cleanupBusinessState: cleanupBusinessState
        )
        return true
    }

    private static func retryPendingPersistenceCleanup(
        markerName: String,
        marker: PairingPersistenceCleanupMarker,
        secretStore: any InternetPairingSecretStore,
        cleanupBusinessState: () throws -> Void
    ) throws {
        var failures: [Error] = []
        for name in marker.remainingSecretNames {
            do { try secretStore.delete(name: name) }
            catch { failures.append(error) }
        }
        if failures.isEmpty {
            do { try cleanupBusinessState() }
            catch { failures.append(error) }
        }
        guard failures.isEmpty else {
            throw InternetPairingError.persistenceFailure(
                "Pairing cleanup remains pending after \(failures.count) failed step(s)."
            )
        }
        try secretStore.delete(name: markerName)
    }

    static func pendingPersistenceContext(
        secretStore: any InternetPairingSecretStore = KeychainSecretStore()
    ) throws -> PendingPairingPersistenceContext? {
        let contexts = try Self.pendingPersistenceContexts(secretStore: secretStore)
        guard contexts.count <= 1 else {
            throw InternetPairingError.persistenceFailure(
                "Multiple pairing persistence transactions require scoped recovery."
            )
        }
        return contexts.first
    }

    static func pendingPersistenceContexts(
        secretStore: any InternetPairingSecretStore = KeychainSecretStore()
    ) throws -> [PendingPairingPersistenceContext] {
        try secretStore.names(prefix: Self.persistenceCleanupMarkerPrefix).sorted().compactMap {
            guard let encoded = try secretStore.load(name: $0) else { return nil }
            let marker = try Self.decodePersistenceCleanupMarker(encoded)
            guard let peerSecurityScopeID = marker.peerSecurityScopeID,
                  let pairingIdentifier = marker.pairingIdentifier else { return nil }
            return PendingPairingPersistenceContext(
                peerSecurityScopeID: peerSecurityScopeID,
                pairingIdentifier: pairingIdentifier
            )
        }
    }

    private static func decodePersistenceCleanupMarker(
        _ encoded: Data
    ) throws -> PairingPersistenceCleanupMarker {
        let marker: PairingPersistenceCleanupMarker
        do { marker = try JSONDecoder().decode(PairingPersistenceCleanupMarker.self, from: encoded) }
        catch {
            throw InternetPairingError.persistenceFailure(
                "Stored pairing cleanup marker is invalid; its Keychain slot was retained."
            )
        }
        try marker.validate()
        return marker
    }

    private static let persistenceCleanupMarkerPrefix = "pairing.persistence-cleanup.v2."

    private static func persistenceCleanupMarkerName(
        _ pairingIdentifier: String
    ) -> String {
        Self.persistenceCleanupMarkerPrefix + InternetPairingCanonical.hexDigest(
            Data(pairingIdentifier.utf8)
        )
    }

    private static func requiredPairingIdentifier(
        _ secretNames: PairedDeviceSecretNames
    ) throws -> String {
        guard let pairingIdentifier = secretNames.pairingIdentifier else {
            throw InternetPairingError.persistenceFailure(
                "The pairing persistence transaction owner is missing."
            )
        }
        return pairingIdentifier
    }

    private static func secureRandomBytes(count: Int) throws -> Data {
        guard count > 0 else { throw InternetPairingError.invalidOffer("Random byte count must be positive.") }
        var data = Data(count: count)
        let status = data.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, count, bytes.baseAddress!)
        }
        guard status == errSecSuccess else {
            throw InternetPairingError.persistenceFailure("Secure random generation failed with status \(status).")
        }
        return data
    }
}

private struct PairingPersistenceCleanupMarker: Codable {
    let version: Int
    let remainingSecretNames: [String]
    let peerSecurityScopeID: String?
    let pairingIdentifier: String?

    init(
        remainingSecretNames: [String],
        peerSecurityScopeID: String,
        pairingIdentifier: String
    ) {
        version = 1
        self.remainingSecretNames = remainingSecretNames
        self.peerSecurityScopeID = peerSecurityScopeID
        self.pairingIdentifier = pairingIdentifier
    }

    func validate() throws {
        guard version == 1,
              (2...4).contains(remainingSecretNames.count),
              remainingSecretNames.allSatisfy({ !$0.isEmpty }),
              Set(remainingSecretNames).count == remainingSecretNames.count,
              peerSecurityScopeID?.isEmpty != true,
              pairingIdentifier?.isEmpty != true,
              (peerSecurityScopeID == nil) == (pairingIdentifier == nil) else {
            throw InternetPairingError.persistenceFailure(
                "Stored pairing cleanup marker is invalid; its Keychain slot was retained."
            )
        }
    }
}

private extension NSLock {
    func withPairingLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
