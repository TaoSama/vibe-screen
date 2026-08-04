import CryptoKit
import Foundation
import Security

struct PlatformPublicIdentity: Equatable {
    static let algorithm = "ECDSA_P256_SHA256"

    let deviceID: String
    let keyID: String
    let keyEpoch: UInt64
    let signingPublicKey: Data

    func rotationNonceHash(nonce: Data) throws -> Data {
        guard nonce.count >= 16 else {
            throw PlatformSecurityError.invalidInput("Identity rotation requires at least 16 nonce bytes.")
        }
        let identity = SecurityTranscript.digest(
            domain: "vibescreen/public-identity/v1",
            parts: [
                Data(deviceID.utf8), Data(keyID.utf8), SecurityTranscript.uint64(keyEpoch),
                Data(Self.algorithm.utf8), signingPublicKey
            ]
        )
        let transcript = SecurityTranscript.digest(
            domain: "vibescreen/key-rotation-nonce/v1",
            parts: [identity, nonce]
        )
        return Data(SHA256.hash(data: transcript))
    }
}

final class KeychainDeviceIdentity {
    let publicIdentity: PlatformPublicIdentity
    private let privateKey: SecKey

    fileprivate init(publicIdentity: PlatformPublicIdentity, privateKey: SecKey) {
        self.publicIdentity = publicIdentity
        self.privateKey = privateKey
    }

    /// Signs an already domain-separated SHA-256 transcript digest and returns
    /// the ASN.1 DER representation required by Protocol v1.
    func signTranscriptDigest(_ digest: Data) throws -> Data {
        guard digest.count == SHA256.byteCount else {
            throw PlatformSecurityError.invalidInput("Identity signatures require a SHA-256 transcript digest.")
        }
        var error: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            privateKey,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            &error
        ) as Data? else {
            if let underlying = error?.takeRetainedValue() { throw underlying }
            throw PlatformSecurityError.persistenceFailure("Keychain signing failed.")
        }
        return signature
    }
}

final class KeychainDeviceIdentityStore {
    private let service: String
    private let lock = NSLock()

    init(service: String = "dev.telemachus.display.phase3-security") {
        self.service = service
    }

    func loadOrCreate(deviceID: String, keyEpoch: UInt64 = 1) throws -> KeychainDeviceIdentity {
        guard !deviceID.isEmpty, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput("Device ID and positive key epoch are required.")
        }
        return try lock.withCriticalSection {
            let tag = keyTag(deviceID: deviceID, epoch: keyEpoch)
            let privateKey = try loadPrivateKey(tag: tag) ?? createPrivateKey(tag: tag)
            return try identity(deviceID: deviceID, epoch: keyEpoch, privateKey: privateKey)
        }
    }

    func delete(deviceID: String, keyEpoch: UInt64) throws {
        try lock.withCriticalSection {
            let status = SecItemDelete([
                kSecClass as String: kSecClassKey,
                kSecAttrApplicationTag as String: keyTag(deviceID: deviceID, epoch: keyEpoch),
                kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom
            ] as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else {
                throw keychainError(status)
            }
        }
    }

    private func loadPrivateKey(tag: Data) throws -> SecKey? {
        var result: CFTypeRef?
        let status = SecItemCopyMatching([
            kSecClass as String: kSecClassKey,
            kSecAttrApplicationTag as String: tag,
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecReturnRef as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ] as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let key = result as! SecKey? else {
            throw keychainError(status)
        }
        return key
    }

    private func createPrivateKey(tag: Data) throws -> SecKey {
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits as String: 256,
            kSecPrivateKeyAttrs as String: [
                kSecAttrIsPermanent as String: true,
                kSecAttrApplicationTag as String: tag,
                kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            ]
        ]
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateRandomKey(attributes as CFDictionary, &error) else {
            if let underlying = error?.takeRetainedValue() { throw underlying }
            throw PlatformSecurityError.persistenceFailure("Unable to create the Keychain identity key.")
        }
        return key
    }

    private func identity(deviceID: String, epoch: UInt64, privateKey: SecKey) throws -> KeychainDeviceIdentity {
        guard let publicKey = SecKeyCopyPublicKey(privateKey) else {
            throw PlatformSecurityError.persistenceFailure("Keychain identity has no public key.")
        }
        var error: Unmanaged<CFError>?
        guard let external = SecKeyCopyExternalRepresentation(publicKey, &error) as Data? else {
            if let underlying = error?.takeRetainedValue() { throw underlying }
            throw PlatformSecurityError.persistenceFailure("Unable to encode the public identity key.")
        }
        guard external.count == 65, external.first == 0x04 else {
            throw PlatformSecurityError.persistenceFailure("Keychain returned an unsupported P-256 public-key encoding.")
        }
        let keyID = Data(SHA256.hash(data: external)).map { String(format: "%02x", $0) }.joined()
        return KeychainDeviceIdentity(
            publicIdentity: PlatformPublicIdentity(
                deviceID: deviceID,
                keyID: keyID,
                keyEpoch: epoch,
                signingPublicKey: external
            ),
            privateKey: privateKey
        )
    }

    private func keyTag(deviceID: String, epoch: UInt64) -> Data {
        Data("\(service).identity.\(deviceID).\(epoch)".utf8)
    }
}

struct KeychainSecurityStateStore: SecurityStateStore {
    let service: String
    let account: String

    init(service: String = "dev.telemachus.display.phase3-security", account: String = "durable-state-v1") {
        self.service = service
        self.account = account
    }

    func load() throws -> PersistedSecurityState {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return PersistedSecurityState() }
        guard status == errSecSuccess, let data = result as? Data else { throw keychainError(status) }
        do {
            let state = try JSONDecoder().decode(PersistedSecurityState.self, from: data)
            guard state.usedRotationNonceHashes.allSatisfy({ value in
                value.count == 64 && value.allSatisfy { "0123456789abcdef".contains($0) }
            }) else {
                throw PlatformSecurityError.persistenceFailure("Stored rotation nonce state is invalid.")
            }
            return state
        }
        catch { throw PlatformSecurityError.persistenceFailure("Stored security state is invalid: \(error.localizedDescription)") }
    }

    func persist(_ state: PersistedSecurityState) throws {
        let data: Data
        do { data = try JSONEncoder().encode(state) }
        catch { throw PlatformSecurityError.persistenceFailure("Unable to encode security state: \(error.localizedDescription)") }
        let status = SecItemUpdate(baseQuery as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw keychainError(status) }
        var item = baseQuery
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw keychainError(addStatus) }
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any
        ]
    }
}

/// Stores issued pairing credentials as device-local Keychain data. Traffic
/// keys remain memory-only and are never written here.
struct KeychainSecretStore {
    let service: String

    init(service: String = "dev.telemachus.display.phase3-secrets") {
        self.service = service
    }

    func load(name: String) throws -> Data? {
        var query = baseQuery(name: name)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw keychainError(status) }
        return data
    }

    func persist(name: String, secret: Data) throws {
        guard !name.isEmpty, !secret.isEmpty else {
            throw PlatformSecurityError.invalidInput("Secret name and value are required.")
        }
        let query = baseQuery(name: name)
        let status = SecItemUpdate(
            query as CFDictionary,
            [kSecValueData as String: secret] as CFDictionary
        )
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw keychainError(status) }
        var item = query
        item[kSecValueData as String] = secret
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw keychainError(addStatus) }
    }

    func delete(name: String) throws {
        let status = SecItemDelete(baseQuery(name: name) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw keychainError(status) }
    }

    private func baseQuery(name: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: name,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any
        ]
    }
}

struct ActivePlatformSecuritySession {
    let identity: KeychainDeviceIdentity
    let sessionEpoch: UInt64
    let trafficKeys: PlatformSessionKeys
}

/// Composes the Keychain identity, crash-safe session epoch, and traffic-key
/// derivation into the lifecycle consumed by a concrete Internet adapter.
final class PlatformSessionSecurity {
    private let deviceID: String
    private let identityStore: KeychainDeviceIdentityStore
    private let lifecycle: SecurityLifecycle

    init(
        deviceID: String,
        identityStore: KeychainDeviceIdentityStore = KeychainDeviceIdentityStore(),
        stateStore: any SecurityStateStore = KeychainSecurityStateStore()
    ) {
        self.deviceID = deviceID
        self.identityStore = identityStore
        self.lifecycle = SecurityLifecycle(store: stateStore)
    }

    func startSession(
        identityEpoch: UInt64,
        sharedSecret: Data,
        bootstrapSecret: Data,
        transcriptContext: Data
    ) throws -> ActivePlatformSecuritySession {
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: sharedSecret,
            bootstrapSecret: bootstrapSecret,
            context: transcriptContext
        )
        let sessionEpoch = try lifecycle.beginSession()
        let identity = try identityStore.loadOrCreate(deviceID: deviceID, keyEpoch: identityEpoch)
        return ActivePlatformSecuritySession(identity: identity, sessionEpoch: sessionEpoch, trafficKeys: keys)
    }

    func rotateTrafficKeys(
        _ current: PlatformSessionKeys,
        updateNonce: Data
    ) throws -> PlatformSessionKeys {
        guard current.keyEpoch < UInt64.max else {
            throw PlatformSecurityError.exhausted("Traffic-key epoch is exhausted.")
        }
        return try TrafficKeyDerivation.rotate(
            current: current,
            nextEpoch: current.keyEpoch + 1,
            updateNonce: updateNonce
        )
    }

    func reserveNonce(channel: UInt32, senderRole: UInt32, keyEpoch: UInt64) throws -> Data {
        try lifecycle.reserveNonce(channel: channel, senderRole: senderRole, keyEpoch: keyEpoch)
    }

    func consumeRotationNonce(authority: PlatformPublicIdentity, nonce: Data) throws {
        try lifecycle.consumeRotationNonceHash(authority.rotationNonceHash(nonce: nonce))
    }

    func revoke(sequence: UInt64, identityEpoch: UInt64) throws {
        // Persist revocation first. A subsequent key deletion failure remains
        // fail-closed and can be retried without re-authorizing the identity.
        try lifecycle.applyRevocation(sequence: sequence)
        try identityStore.delete(deviceID: deviceID, keyEpoch: identityEpoch)
    }
}

private func keychainError(_ status: OSStatus) -> PlatformSecurityError {
    let message = SecCopyErrorMessageString(status, nil) as String? ?? "status \(status)"
    return .persistenceFailure("Keychain operation failed: \(message)")
}

private extension NSLock {
    func withCriticalSection<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
