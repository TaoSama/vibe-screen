import Foundation

struct LegacyGlobalRevocationCleanupMarker: Codable, Equatable {
    static let currentVersion: UInt8 = 1

    let version: UInt8
    let revokedIdentity: PlatformPublicIdentity?
    let sharedSecretName: String?
    let bootstrapSecretName: String?

    init(
        revokedIdentity: PlatformPublicIdentity?,
        sharedSecretName: String?,
        bootstrapSecretName: String?
    ) {
        self.version = Self.currentVersion
        self.revokedIdentity = revokedIdentity
        self.sharedSecretName = sharedSecretName
        self.bootstrapSecretName = bootstrapSecretName
    }

    func validate() throws {
        guard version == Self.currentVersion,
              sharedSecretName?.isEmpty != true,
              bootstrapSecretName?.isEmpty != true else {
            throw PlatformSecurityError.persistenceFailure(
                "The legacy revocation cleanup marker version is unsupported."
            )
        }
    }
}

protocol LegacyGlobalRevocationCleanupPersistence {
    func loadCleanupMarker() throws -> LegacyGlobalRevocationCleanupMarker?
    func loadLegacyGlobalRevocation() throws -> PersistedSecurityState?
    func persistCleanupMarker(_ marker: LegacyGlobalRevocationCleanupMarker) throws
    func deleteLegacyGlobalRevocation() throws
    func deleteCleanupMarker() throws
}

/// Crash-safe two-phase cleanup. `begin` durably records fail-closed intent;
/// the product then invalidates all pairing material and calls `complete`.
/// A marker is always resumed before inspecting the legacy account, including
/// when a crash happened after deleting the legacy revocation.
struct LegacyGlobalRevocationCleanupTransaction {
    private let persistence: any LegacyGlobalRevocationCleanupPersistence

    init(persistence: any LegacyGlobalRevocationCleanupPersistence) {
        self.persistence = persistence
    }

    func begin(
        fallbackRevokedIdentity: PlatformPublicIdentity?,
        sharedSecretName: String?,
        bootstrapSecretName: String?
    ) throws -> LegacyGlobalRevocationCleanupMarker? {
        if let marker = try persistence.loadCleanupMarker() {
            try marker.validate()
            return marker
        }
        guard let legacy = try persistence.loadLegacyGlobalRevocation(),
              legacy.revoked || legacy.peerRevocation != nil else {
            return nil
        }
        let marker = LegacyGlobalRevocationCleanupMarker(
            revokedIdentity: legacy.peerRevocation?.peerIdentity
                ?? fallbackRevokedIdentity,
            sharedSecretName: sharedSecretName,
            bootstrapSecretName: bootstrapSecretName
        )
        try persistence.persistCleanupMarker(marker)
        return marker
    }

    func complete() throws {
        guard let marker = try persistence.loadCleanupMarker() else {
            throw PlatformSecurityError.persistenceFailure(
                "Legacy revocation cleanup cannot complete without its durable marker."
            )
        }
        try marker.validate()
        try persistence.deleteLegacyGlobalRevocation()
        try persistence.deleteCleanupMarker()
    }
}

/// Pure in-memory boundary checks used by the executable Phase 3 self-test.
enum LegacyGlobalRevocationCleanupSelfTest {
    static func run() -> Bool {
        let identity = PlatformPublicIdentity(
            deviceID: "legacy-device",
            keyID: "legacy-key",
            keyEpoch: 7,
            signingPublicKey: Data([0x04] + Array(repeating: 0x22, count: 64))
        )
        let store = MemoryLegacyCleanupPersistence(
            legacy: PersistedSecurityState(revoked: true)
        )
        do {
            let transaction = LegacyGlobalRevocationCleanupTransaction(
                persistence: store
            )
            let marker = try transaction.begin(
                fallbackRevokedIdentity: identity,
                sharedSecretName: "legacy-shared",
                bootstrapSecretName: "legacy-bootstrap"
            )
            guard marker?.revokedIdentity == identity,
                  marker?.sharedSecretName == "legacy-shared",
                  marker?.bootstrapSecretName == "legacy-bootstrap",
                  store.legacy != nil,
                  store.operations == ["persist-marker"] else {
                return false
            }

            // Restart after marker persistence or pairing invalidation resumes
            // from the marker and never recreates a paired state.
            let resumed = LegacyGlobalRevocationCleanupTransaction(
                persistence: store
            )
            guard try resumed.begin(
                fallbackRevokedIdentity: nil,
                sharedSecretName: nil,
                bootstrapSecretName: nil
            ) == marker,
                  store.operations == ["persist-marker"] else {
                return false
            }

            // Restart after legacy deletion but before marker deletion also
            // resumes fail closed and finishes idempotently.
            store.legacy = nil
            guard try resumed.begin(
                fallbackRevokedIdentity: nil,
                sharedSecretName: nil,
                bootstrapSecretName: nil
            ) == marker else {
                return false
            }
            try resumed.complete()
            return store.legacy == nil && store.marker == nil &&
                store.operations == [
                    "persist-marker", "delete-legacy", "delete-marker"
                ]
        } catch {
            return false
        }
    }
}

private final class MemoryLegacyCleanupPersistence:
    LegacyGlobalRevocationCleanupPersistence {
    var legacy: PersistedSecurityState?
    var marker: LegacyGlobalRevocationCleanupMarker?
    var operations: [String] = []

    init(legacy: PersistedSecurityState?) {
        self.legacy = legacy
    }

    func loadCleanupMarker() throws -> LegacyGlobalRevocationCleanupMarker? {
        marker
    }

    func loadLegacyGlobalRevocation() throws -> PersistedSecurityState? {
        legacy
    }

    func persistCleanupMarker(
        _ marker: LegacyGlobalRevocationCleanupMarker
    ) throws {
        self.marker = marker
        operations.append("persist-marker")
    }

    func deleteLegacyGlobalRevocation() throws {
        legacy = nil
        operations.append("delete-legacy")
    }

    func deleteCleanupMarker() throws {
        marker = nil
        operations.append("delete-marker")
    }
}
