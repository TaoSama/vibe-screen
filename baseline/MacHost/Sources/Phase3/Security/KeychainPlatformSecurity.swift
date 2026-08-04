import CryptoKit
import Foundation
import Security

struct PlatformPublicIdentity: Codable, Equatable {
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

enum PairedDeviceSecurityScope {
    static func identifier(_ identity: PlatformPublicIdentity) -> String {
        "\(identity.deviceID)|key:\(identity.keyID)"
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

    func signPeerRevocation(
        peerIdentity: PlatformPublicIdentity,
        sequence: UInt64,
        revokedAtUnixSeconds: Int64,
        nonce: Data,
        reasonCode: String
    ) throws -> PairedDeviceRevocationTombstone {
        let unsigned = PairedDeviceRevocationTombstone(
            peerIdentity: peerIdentity,
            sequence: sequence,
            revokedAtUnixSeconds: revokedAtUnixSeconds,
            nonce: nonce,
            reasonCode: reasonCode,
            authority: publicIdentity,
            authoritySignature: Data()
        )
        return PairedDeviceRevocationTombstone(
            peerIdentity: peerIdentity,
            sequence: sequence,
            revokedAtUnixSeconds: revokedAtUnixSeconds,
            nonce: nonce,
            reasonCode: reasonCode,
            authority: publicIdentity,
            authoritySignature: try signTranscriptDigest(unsigned.signingDigest())
        )
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

    /// Loads an already-provisioned identity without creating a replacement.
    /// Lease issuance must fail closed when pairing has not created this key.
    func loadExisting(
        deviceID: String,
        keyEpoch: UInt64 = 1
    ) throws -> KeychainDeviceIdentity? {
        guard !deviceID.isEmpty, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput(
                "Device ID and positive key epoch are required."
            )
        }
        return try lock.withCriticalSection {
            guard let privateKey = try loadPrivateKey(
                tag: keyTag(deviceID: deviceID, epoch: keyEpoch)
            ) else { return nil }
            return try identity(
                deviceID: deviceID,
                epoch: keyEpoch,
                privateKey: privateKey
            )
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

struct KeychainSecurityStateStore:
    SecurityStateStore,
    LegacyGlobalRevocationCleanupPersistence {
    let service: String
    let account: String
    let legacyAccount: String?
    let legacyCleanupAccount: String?
    let peerID: String?

    init(
        peerID: String,
        service: String = "dev.telemachus.display.phase3-security",
        legacyAccount: String? = "durable-state-v1",
        legacyCleanupAccount: String? = "legacy-revocation-cleanup-v1"
    ) {
        precondition(!peerID.isEmpty, "Peer ID must not be empty.")
        self.service = service
        self.account = Self.accountName(peerID: peerID)
        self.legacyAccount = legacyAccount
        self.legacyCleanupAccount = legacyCleanupAccount
        self.peerID = peerID
    }

    /// Retained for injected/custom stores. Production composition uses the
    /// peer-scoped initializer and never writes the legacy global account.
    init(service: String, account: String) {
        self.service = service
        self.account = account
        self.legacyAccount = nil
        self.legacyCleanupAccount = nil
        self.peerID = nil
    }

    func load() throws -> PersistedSecurityState {
        if let current = try load(account: account, expectedPeerID: peerID) { return current }
        guard let legacyAccount,
              let legacy = try load(account: legacyAccount, expectedPeerID: nil) else {
            return PersistedSecurityState()
        }
        let migrated = try Self.migratedLegacyState(legacy)
        try persist(migrated)
        return migrated
    }

    private func load(
        account: String,
        expectedPeerID: String?
    ) throws -> PersistedSecurityState? {
        guard let data = try loadData(account: account) else { return nil }
        do {
            let state = try JSONDecoder().decode(PersistedSecurityState.self, from: data)
            guard state.usedRotationNonceHashes.allSatisfy({ value in
                value.count == 64 && value.allSatisfy { "0123456789abcdef".contains($0) }
            }) else {
                throw PlatformSecurityError.persistenceFailure("Stored rotation nonce state is invalid.")
            }
            guard state.nonceHighWatermarks.values.allSatisfy({ $0 > 0 }) else {
                throw PlatformSecurityError.persistenceFailure("Stored nonce state is invalid.")
            }
            if let tombstone = state.peerRevocation {
                guard state.revoked, state.revocationSequence == tombstone.sequence,
                      expectedPeerID == nil ||
                        PairedDeviceSecurityScope.identifier(tombstone.peerIdentity) == expectedPeerID else {
                    throw PlatformSecurityError.persistenceFailure("Stored peer revocation state is invalid.")
                }
                try tombstone.verify(
                    expectedAuthority: tombstone.authority,
                    expectedPeer: tombstone.peerIdentity
                )
            }
            if let marker = state.revocationSecretCleanup {
                guard state.revoked, state.peerRevocation != nil else {
                    throw PlatformSecurityError.persistenceFailure(
                        "Stored revocation cleanup has no peer tombstone."
                    )
                }
                try marker.validate()
            }
            return state
        }
        catch { throw PlatformSecurityError.persistenceFailure("Stored security state is invalid: \(error.localizedDescription)") }
    }

    func persist(_ state: PersistedSecurityState) throws {
        let data: Data
        do { data = try JSONEncoder().encode(state) }
        catch { throw PlatformSecurityError.persistenceFailure("Unable to encode security state: \(error.localizedDescription)") }
        try persist(data: data, account: account)
    }

    private func loadData(account: String) throws -> Data? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else {
            throw keychainError(status)
        }
        return data
    }

    private func persist(data: Data, account: String) throws {
        let query = baseQuery(account: account)
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw keychainError(status) }
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw keychainError(addStatus) }
    }

    private func delete(account: String) throws {
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw keychainError(status)
        }
    }

    static func accountName(peerID: String) -> String {
        let digest = SHA256.hash(data: Data(peerID.utf8))
        return "durable-state-v2.peer." + digest.map { String(format: "%02x", $0) }.joined()
    }

    static func migratedLegacyState(_ legacy: PersistedSecurityState) throws -> PersistedSecurityState {
        guard !legacy.revoked, legacy.peerRevocation == nil else {
            throw PlatformSecurityError.persistenceFailure(
                "Legacy global revocation state requires explicit identity migration and cannot be copied to a peer."
            )
        }
        // Only crash-safety high-watermarks are safe to conservatively copy
        // into a new peer scope. Authorization, revocation, and rotation
        // tombstones never migrate across peer identities.
        return PersistedSecurityState(
            sessionEpoch: legacy.sessionEpoch,
            nonceHighWatermarks: legacy.nonceHighWatermarks
        )
    }

    func loadCleanupMarker() throws -> LegacyGlobalRevocationCleanupMarker? {
        guard let legacyCleanupAccount,
              let data = try loadData(account: legacyCleanupAccount) else {
            return nil
        }
        do {
            let marker = try JSONDecoder().decode(
                LegacyGlobalRevocationCleanupMarker.self,
                from: data
            )
            try marker.validate()
            return marker
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Stored legacy revocation cleanup marker is invalid: \(error.localizedDescription)"
            )
        }
    }

    func loadLegacyGlobalRevocation() throws -> PersistedSecurityState? {
        guard let legacyAccount,
              let legacy = try load(account: legacyAccount, expectedPeerID: nil),
              legacy.revoked || legacy.peerRevocation != nil else {
            return nil
        }
        return legacy
    }

    func persistCleanupMarker(
        _ marker: LegacyGlobalRevocationCleanupMarker
    ) throws {
        guard let legacyCleanupAccount else {
            throw PlatformSecurityError.persistenceFailure(
                "Legacy revocation cleanup is unavailable for this store."
            )
        }
        try marker.validate()
        do {
            try persist(
                data: JSONEncoder().encode(marker),
                account: legacyCleanupAccount
            )
        } catch let error as PlatformSecurityError {
            throw error
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to encode the legacy revocation cleanup marker: \(error.localizedDescription)"
            )
        }
    }

    func deleteLegacyGlobalRevocation() throws {
        guard let legacyAccount else { return }
        try delete(account: legacyAccount)
    }

    func deleteCleanupMarker() throws {
        guard let legacyCleanupAccount else { return }
        try delete(account: legacyCleanupAccount)
    }

    private func baseQuery(account: String) -> [String: Any] {
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

protocol PairedDeviceSecretStore {
    func delete(name: String) throws
}

extension KeychainSecretStore: PairedDeviceSecretStore {}

struct PairedDeviceSecretNames: Equatable {
    let sharedSecret: String
    let bootstrapSecret: String

    init(sharedSecret: String, bootstrapSecret: String) throws {
        guard !sharedSecret.isEmpty, !bootstrapSecret.isEmpty, sharedSecret != bootstrapSecret else {
            throw PlatformSecurityError.invalidInput("Distinct paired-device secret names are required.")
        }
        self.sharedSecret = sharedSecret
        self.bootstrapSecret = bootstrapSecret
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
    private let peerID: String
    private let identityStore: KeychainDeviceIdentityStore
    private let lifecycle: SecurityLifecycle

    init(
        deviceID: String,
        peerID: String? = nil,
        identityStore: KeychainDeviceIdentityStore = KeychainDeviceIdentityStore(),
        stateStore: (any SecurityStateStore)? = nil
    ) {
        self.deviceID = deviceID
        self.peerID = peerID ?? "unpaired.\(deviceID)"
        self.identityStore = identityStore
        self.lifecycle = SecurityLifecycle(
            store: stateStore ?? KeychainSecurityStateStore(peerID: self.peerID)
        )
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

    func startSession(
        agreedSessionEpoch: UInt64,
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
        let sessionEpoch = try lifecycle.reserveSessionEpoch(agreedSessionEpoch)
        let identity = try identityStore.loadOrCreate(deviceID: deviceID, keyEpoch: identityEpoch)
        return ActivePlatformSecuritySession(identity: identity, sessionEpoch: sessionEpoch, trafficKeys: keys)
    }

    func advanceSessionEpoch() throws -> UInt64 {
        try lifecycle.advanceSessionEpoch()
    }

    func reserveSessionEpoch(_ agreedSessionEpoch: UInt64) throws -> UInt64 {
        try lifecycle.reserveSessionEpoch(agreedSessionEpoch)
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

    func reserveNonce(
        sessionEpoch: UInt64,
        channel: UInt32,
        senderRole: UInt32,
        keyEpoch: UInt64
    ) throws -> Data {
        try lifecycle.reserveNonce(
            sessionEpoch: sessionEpoch,
            channel: channel,
            senderRole: senderRole,
            keyEpoch: keyEpoch
        )
    }

    func consumeRotationNonce(authority: PlatformPublicIdentity, nonce: Data) throws {
        try lifecycle.consumeRotationNonceHash(authority.rotationNonceHash(nonce: nonce))
    }

    func revoke(sequence: UInt64, identityEpoch _: UInt64) throws {
        // Compatibility path: this state is peer-scoped. Never delete the
        // local identity when a paired device is revoked.
        try lifecycle.applyRevocation(sequence: sequence)
    }

    func revokePeer(
        _ tombstone: PairedDeviceRevocationTombstone,
        expectedAuthority: PlatformPublicIdentity,
        expectedPeer: PlatformPublicIdentity,
        secretNames: PairedDeviceSecretNames,
        secretStore: any PairedDeviceSecretStore = KeychainSecretStore()
    ) throws {
        guard PairedDeviceSecurityScope.identifier(expectedPeer) == peerID else {
            throw PlatformSecurityError.invalidInput("The revocation target does not match this peer scope.")
        }
        // Commit the signed tombstone before deleting secrets. A deletion
        // failure remains fail-closed and can be retried safely.
        try lifecycle.applyPeerRevocation(
            tombstone,
            expectedAuthority: expectedAuthority,
            expectedPeer: expectedPeer,
            secretNames: secretNames
        )
        try lifecycle.retryRevocationSecretCleanup(secretStore: secretStore)
    }

    func hasPendingRevocationSecretCleanup() throws -> Bool {
        try lifecycle.hasPendingRevocationSecretCleanup()
    }

    func retryRevocationSecretCleanup(
        secretStore: any PairedDeviceSecretStore = KeychainSecretStore()
    ) throws {
        try lifecycle.retryRevocationSecretCleanup(secretStore: secretStore)
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
