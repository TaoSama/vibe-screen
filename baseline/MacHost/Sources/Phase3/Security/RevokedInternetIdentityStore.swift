import Foundation
import Security

private struct LegacyRevokedInternetIdentityRecord: Codable {
    let keyID: String
    let keyEpoch: UInt64
}

struct RevokedInternetIdentityState: Codable, Equatable {
    static let currentSchemaVersion = 2

    let schemaVersion: Int
    var revokedKeyIDs: Set<String>
    var maximumRevokedEpochByDeviceID: [String: UInt64]

    init(
        revokedKeyIDs: Set<String> = [],
        maximumRevokedEpochByDeviceID: [String: UInt64] = [:]
    ) {
        self.schemaVersion = Self.currentSchemaVersion
        self.revokedKeyIDs = revokedKeyIDs
        self.maximumRevokedEpochByDeviceID = maximumRevokedEpochByDeviceID
    }
}

protocol RevokedInternetIdentityPersistence {
    func load() throws -> Data?
    func persist(_ data: Data) throws
}

struct KeychainRevokedInternetIdentityPersistence:
    RevokedInternetIdentityPersistence {
    private let service: String
    private let account: String

    init(
        service: String = "dev.telemachus.display.phase3-security",
        account: String = "revoked-internet-identities-v1"
    ) {
        self.service = service
        self.account = account
    }

    func load() throws -> Data? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else {
            throw persistenceError(status, operation: "read")
        }
        return data
    }

    func persist(_ data: Data) throws {
        let update = [kSecValueData as String: data] as CFDictionary
        let updateStatus = SecItemUpdate(baseQuery as CFDictionary, update)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw persistenceError(updateStatus, operation: "update")
        }

        var item = baseQuery
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] =
            kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        if addStatus == errSecSuccess { return }
        if addStatus == errSecDuplicateItem {
            let retryStatus = SecItemUpdate(baseQuery as CFDictionary, update)
            guard retryStatus == errSecSuccess else {
                throw persistenceError(retryStatus, operation: "update")
            }
            return
        }
        throw persistenceError(addStatus, operation: "add")
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }

    private func persistenceError(
        _ status: OSStatus,
        operation: String
    ) -> PlatformSecurityError {
        let detail = SecCopyErrorMessageString(status, nil) as String?
            ?? "OSStatus \(status)"
        return .persistenceFailure(
            "Keychain revoked identity \(operation) failed: \(detail)"
        )
    }
}

/// Keeps an irreversible global deny-set for signing keys and a monotonic
/// key-epoch floor for every stable device ID. Both checks are required:
/// changing a device ID cannot rehabilitate a revoked key, and changing a key
/// cannot roll a stable device back to an old epoch.
final class RevokedInternetIdentityStore {
    private static let persistenceLock = NSLock()
    private let persistence: RevokedInternetIdentityPersistence

    init(
        persistence: RevokedInternetIdentityPersistence =
            KeychainRevokedInternetIdentityPersistence()
    ) {
        self.persistence = persistence
    }

    func remember(_ identity: PlatformPublicIdentity) throws {
        try remember(
            deviceID: identity.deviceID,
            keyID: identity.keyID,
            keyEpoch: identity.keyEpoch
        )
    }

    func remember(deviceID: String, keyID: String, keyEpoch: UInt64) throws {
        guard !deviceID.isEmpty, !keyID.isEmpty, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput(
                "Revoked identities require a device ID, key ID and positive key epoch."
            )
        }
        try Self.persistenceLock.withLock {
            var state = try loadState()
            let insertedKey = state.revokedKeyIDs.insert(keyID).inserted
            let currentFloor =
                state.maximumRevokedEpochByDeviceID[deviceID] ?? 0
            guard insertedKey || keyEpoch > currentFloor else { return }
            state.maximumRevokedEpochByDeviceID[deviceID] = max(
                currentFloor,
                keyEpoch
            )
            try persist(state)
        }
    }

    func validateReauthorization(_ identity: PlatformPublicIdentity) throws {
        let state = try Self.persistenceLock.withLock { try loadState() }
        guard !state.revokedKeyIDs.contains(identity.keyID) else {
            throw PlatformSecurityError.revoked
        }
        if let floor = state.maximumRevokedEpochByDeviceID[identity.deviceID],
           identity.keyEpoch <= floor {
            throw PlatformSecurityError.revoked
        }
    }

    func maximumRevokedEpoch(for deviceID: String) throws -> UInt64? {
        try Self.persistenceLock.withLock {
            try loadState().maximumRevokedEpochByDeviceID[deviceID]
        }
    }

    func isKeyRevoked(_ keyID: String) throws -> Bool {
        try Self.persistenceLock.withLock {
            try loadState().revokedKeyIDs.contains(keyID)
        }
    }

    private func loadState() throws -> RevokedInternetIdentityState {
        guard let data = try persistence.load() else {
            return RevokedInternetIdentityState()
        }
        if let current = try? JSONDecoder().decode(
            RevokedInternetIdentityState.self,
            from: data
        ) {
            try validate(current)
            return current
        }

        let legacy: [String: LegacyRevokedInternetIdentityRecord]
        do {
            legacy = try JSONDecoder().decode(
                [String: LegacyRevokedInternetIdentityRecord].self,
                from: data
            )
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Stored revoked identity history is invalid."
            )
        }
        guard legacy.allSatisfy({ deviceID, record in
            !deviceID.isEmpty && !record.keyID.isEmpty && record.keyEpoch > 0
        }) else {
            throw PlatformSecurityError.persistenceFailure(
                "Legacy revoked identity history contains an invalid record."
            )
        }
        let migrated = RevokedInternetIdentityState(
            revokedKeyIDs: Set(legacy.values.map(\.keyID)),
            maximumRevokedEpochByDeviceID: legacy.mapValues(\.keyEpoch)
        )
        try persist(migrated)
        return migrated
    }

    private func validate(_ state: RevokedInternetIdentityState) throws {
        guard state.schemaVersion == RevokedInternetIdentityState.currentSchemaVersion,
              state.revokedKeyIDs.allSatisfy({ !$0.isEmpty }),
              state.maximumRevokedEpochByDeviceID.allSatisfy({ deviceID, epoch in
                  !deviceID.isEmpty && epoch > 0
              }) else {
            throw PlatformSecurityError.persistenceFailure(
                "Stored revoked identity history has an invalid v2 schema."
            )
        }
    }

    private func persist(_ state: RevokedInternetIdentityState) throws {
        do {
            try persistence.persist(try JSONEncoder().encode(state))
        } catch let error as PlatformSecurityError {
            throw error
        } catch {
            throw PlatformSecurityError.persistenceFailure(
                "Revoked identity history could not be persisted."
            )
        }
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
