import Foundation
import Security

enum PlatformSecurityError: Error, Equatable, LocalizedError {
    case invalidInput(String)
    case revoked
    case exhausted(String)
    case persistenceFailure(String)

    var errorDescription: String? {
        switch self {
        case .invalidInput(let reason), .exhausted(let reason), .persistenceFailure(let reason):
            return reason
        case .revoked:
            return "The paired device has been revoked."
        }
    }
}

struct PairedDeviceRevocationTombstone: Codable, Equatable {
    let peerIdentity: PlatformPublicIdentity
    let sequence: UInt64
    let revokedAtUnixSeconds: Int64
    let nonce: Data
    let reasonCode: String
    let authority: PlatformPublicIdentity
    let authoritySignature: Data

    func signingDigest() -> Data {
        SecurityTranscript.digest(
            domain: "vibescreen/device-revocation/v1",
            parts: [
                identityDigest(authority),
                Data(peerIdentity.deviceID.utf8),
                Data(peerIdentity.keyID.utf8),
                SecurityTranscript.uint64(sequence),
                SecurityTranscript.uint64(UInt64(bitPattern: revokedAtUnixSeconds)),
                nonce,
                Data(reasonCode.utf8)
            ]
        )
    }

    func verify(expectedAuthority: PlatformPublicIdentity, expectedPeer: PlatformPublicIdentity) throws {
        guard authority == expectedAuthority, peerIdentity == expectedPeer,
              sequence > 0, revokedAtUnixSeconds >= 0, nonce.count >= 16,
              !reasonCode.isEmpty, !authoritySignature.isEmpty else {
            throw PlatformSecurityError.invalidInput("The paired-device revocation tombstone is invalid.")
        }
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeyClass as String: kSecAttrKeyClassPublic,
            kSecAttrKeySizeInBits as String: 256
        ]
        guard let publicKey = SecKeyCreateWithData(
            authority.signingPublicKey as CFData,
            attributes as CFDictionary,
            nil
        ) else {
            throw PlatformSecurityError.invalidInput("The paired-device revocation signature is invalid.")
        }
        guard SecKeyVerifySignature(
            publicKey,
            .ecdsaSignatureDigestX962SHA256,
            signingDigest() as CFData,
            authoritySignature as CFData,
            nil
        ) else {
            throw PlatformSecurityError.invalidInput("The paired-device revocation signature is invalid.")
        }
    }

    private func identityDigest(_ identity: PlatformPublicIdentity) -> Data {
        SecurityTranscript.digest(
            domain: "vibescreen/public-identity/v1",
            parts: [
                Data(identity.deviceID.utf8), Data(identity.keyID.utf8),
                SecurityTranscript.uint64(identity.keyEpoch),
                Data(PlatformPublicIdentity.algorithm.utf8), identity.signingPublicKey
            ]
        )
    }
}

struct PersistedSecurityState: Codable, Equatable {
    var sessionEpoch: UInt64 = 0
    var revocationSequence: UInt64 = 0
    var revoked = false
    var nonceHighWatermarks: [String: UInt64] = [:]
    var usedRotationNonceHashes: Set<String> = []
    var peerRevocation: PairedDeviceRevocationTombstone?
    var revocationSecretCleanup: RevocationSecretCleanupMarker?

    init(
        sessionEpoch: UInt64 = 0,
        revocationSequence: UInt64 = 0,
        revoked: Bool = false,
        nonceHighWatermarks: [String: UInt64] = [:],
        usedRotationNonceHashes: Set<String> = [],
        peerRevocation: PairedDeviceRevocationTombstone? = nil,
        revocationSecretCleanup: RevocationSecretCleanupMarker? = nil
    ) {
        self.sessionEpoch = sessionEpoch
        self.revocationSequence = revocationSequence
        self.revoked = revoked
        self.nonceHighWatermarks = nonceHighWatermarks
        self.usedRotationNonceHashes = usedRotationNonceHashes
        self.peerRevocation = peerRevocation
        self.revocationSecretCleanup = revocationSecretCleanup
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sessionEpoch = try container.decodeIfPresent(UInt64.self, forKey: .sessionEpoch) ?? 0
        revocationSequence = try container.decodeIfPresent(UInt64.self, forKey: .revocationSequence) ?? 0
        revoked = try container.decodeIfPresent(Bool.self, forKey: .revoked) ?? false
        nonceHighWatermarks = try container.decodeIfPresent([String: UInt64].self, forKey: .nonceHighWatermarks) ?? [:]
        usedRotationNonceHashes = try container.decodeIfPresent(Set<String>.self, forKey: .usedRotationNonceHashes) ?? []
        peerRevocation = try container.decodeIfPresent(PairedDeviceRevocationTombstone.self, forKey: .peerRevocation)
        revocationSecretCleanup = try container.decodeIfPresent(
            RevocationSecretCleanupMarker.self,
            forKey: .revocationSecretCleanup
        )
    }
}

/// Durable, peer-scoped work remaining after a revocation tombstone commits.
/// Secret values are never persisted here; only their Keychain account names.
struct RevocationSecretCleanupMarker: Codable, Equatable {
    private static let currentVersion = 1

    let version: Int
    var remainingSecretNames: [String]

    init(secretNames: PairedDeviceSecretNames) {
        version = Self.currentVersion
        remainingSecretNames = [
            secretNames.sharedSecret,
            secretNames.bootstrapSecret
        ] + [
            secretNames.identityBinding,
            secretNames.peerIdentityBinding
        ].compactMap { $0 }
    }

    func validate() throws {
        guard version == Self.currentVersion,
              !remainingSecretNames.isEmpty,
              remainingSecretNames.allSatisfy({ !$0.isEmpty }),
              Set(remainingSecretNames).count == remainingSecretNames.count else {
            throw PlatformSecurityError.persistenceFailure(
                "Stored revocation secret cleanup marker is invalid."
            )
        }
    }
}

protocol SecurityStateStore {
    func load() throws -> PersistedSecurityState
    func persist(_ state: PersistedSecurityState) throws
    func validatePairingBinding(pairingIdentifier: String) throws -> PersistedSecurityState
    func withExclusiveTransaction<T>(_ operation: () throws -> T) throws -> T
}

extension SecurityStateStore {
    func validatePairingBinding(pairingIdentifier _: String) throws -> PersistedSecurityState {
        try load()
    }

    func withExclusiveTransaction<T>(_ operation: () throws -> T) throws -> T {
        try SecurityStateStoreFallbackLock.lock.withLock(operation)
    }
}

private enum SecurityStateStoreFallbackLock {
    static let lock = NSRecursiveLock()
}

/// Every durable counter mutation runs inside the store's exclusive
/// transaction. Production Keychain stores provide an OS-level cross-process
/// lock; injected stores retain the recursive in-process fallback.
final class SecurityLifecycle {
    static let maximumCrossPlatformSessionEpoch = UInt64(Int64.max)
    private let store: any SecurityStateStore
    private var pairingIdentifier: String?

    init(store: any SecurityStateStore) {
        self.store = store
    }

    func advanceSessionEpoch() throws -> UInt64 {
        try store.withExclusiveTransaction {
            var state = try loadState()
            try requireActive(state)
            guard state.sessionEpoch < Self.maximumCrossPlatformSessionEpoch else {
                throw PlatformSecurityError.exhausted("Session epoch is exhausted; pair the device again.")
            }
            state.sessionEpoch += 1
            try persistState(state)
            return state.sessionEpoch
        }
    }

    func advanceSessionEpoch(pairingIdentifier: String) throws -> UInt64 {
        try store.withExclusiveTransaction {
            self.pairingIdentifier = pairingIdentifier
            var state = try loadState()
            try requireActive(state)
            guard state.sessionEpoch < Self.maximumCrossPlatformSessionEpoch else {
                throw PlatformSecurityError.exhausted("Session epoch is exhausted; pair the device again.")
            }
            state.sessionEpoch += 1
            try persistState(state)
            return state.sessionEpoch
        }
    }

    func requirePairingBinding(
        _ pairingIdentifier: String,
        allowRevoked: Bool = false
    ) throws {
        try store.withExclusiveTransaction {
            let state = try store.validatePairingBinding(
                pairingIdentifier: pairingIdentifier
            )
            if !allowRevoked { try requireActive(state) }
            self.pairingIdentifier = pairingIdentifier
        }
    }

    /// Reserves an authority-agreed epoch before any packet uses it. Equal or
    /// lower values are rejected so a crash can skip an epoch but never reuse it.
    func reserveSessionEpoch(_ proposedEpoch: UInt64) throws -> UInt64 {
        guard proposedEpoch > 0,
              proposedEpoch <= Self.maximumCrossPlatformSessionEpoch else {
            throw PlatformSecurityError.invalidInput(
                "Session epoch must be positive and fit the cross-platform signed 64-bit range."
            )
        }
        return try store.withExclusiveTransaction {
            var state = try loadState()
            try requireActive(state)
            guard proposedEpoch > state.sessionEpoch else {
                throw PlatformSecurityError.invalidInput("Session epoch must advance and cannot be reused.")
            }
            state.sessionEpoch = proposedEpoch
            try persistState(state)
            return proposedEpoch
        }
    }

    /// Compatibility alias for callers that locally allocate the next epoch.
    func beginSession() throws -> UInt64 {
        try advanceSessionEpoch()
    }

    func requireCurrentSessionEpoch(_ expectedEpoch: UInt64) throws {
        try withActiveSessionEpoch(expectedEpoch) {}
    }

    func withActiveSessionEpoch<T>(
        _ expectedEpoch: UInt64,
        operation: () throws -> T
    ) throws -> T {
        try store.withExclusiveTransaction {
            let state = try loadState()
            try requireActive(state)
            guard expectedEpoch > 0, state.sessionEpoch == expectedEpoch else {
                throw PlatformSecurityError.invalidInput(
                    "The session epoch is stale or was not reserved."
                )
            }
            return try operation()
        }
    }

    func reserveNonce(channel: UInt32, senderRole: UInt32, keyEpoch: UInt64) throws -> Data {
        try reserveNonce(sessionEpoch: nil, channel: channel, senderRole: senderRole, keyEpoch: keyEpoch)
    }

    func reserveNonce(
        sessionEpoch: UInt64?,
        channel: UInt32,
        senderRole: UInt32,
        keyEpoch: UInt64
    ) throws -> Data {
        guard channel > 0, senderRole > 0, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput("Channel, sender role, and key epoch must be positive.")
        }
        return try store.withExclusiveTransaction {
            var state = try loadState()
            try requireActive(state)
            if let sessionEpoch, sessionEpoch != state.sessionEpoch {
                throw PlatformSecurityError.invalidInput("The session epoch is stale or was not reserved.")
            }
            let counterKey = "\(channel):\(senderRole):\(keyEpoch)"
            let current = state.nonceHighWatermarks[counterKey] ?? 0
            guard current < UInt64.max else {
                throw PlatformSecurityError.exhausted("Nonce sequence is exhausted; rotate traffic keys.")
            }
            let sequence = current + 1
            state.nonceHighWatermarks[counterKey] = sequence
            try persistState(state, verifyReadBack: false)

            var channelValue = channel.bigEndian
            var sequenceValue = sequence.bigEndian
            var nonce = Data(bytes: &channelValue, count: MemoryLayout<UInt32>.size)
            nonce.append(Data(bytes: &sequenceValue, count: MemoryLayout<UInt64>.size))
            return nonce
        }
    }

    func applyRevocation(sequence: UInt64) throws {
        try store.withExclusiveTransaction {
            var state = try loadState()
            guard sequence > state.revocationSequence else {
                throw PlatformSecurityError.invalidInput("Revocation sequence must increase.")
            }
            state.revocationSequence = sequence
            state.revoked = true
            try persistState(state)
        }
    }

    func applyPeerRevocation(
        _ tombstone: PairedDeviceRevocationTombstone,
        expectedAuthority: PlatformPublicIdentity,
        expectedPeer: PlatformPublicIdentity,
        secretNames: PairedDeviceSecretNames? = nil
    ) throws {
        try tombstone.verify(expectedAuthority: expectedAuthority, expectedPeer: expectedPeer)
        try store.withExclusiveTransaction {
            var state = try loadState()
            if state.peerRevocation == tombstone { return }
            guard tombstone.sequence > state.revocationSequence else {
                throw PlatformSecurityError.invalidInput("Revocation sequence must increase.")
            }
            state.revocationSequence = tombstone.sequence
            state.revoked = true
            state.peerRevocation = tombstone
            state.revocationSecretCleanup = secretNames.map(
                RevocationSecretCleanupMarker.init(secretNames:)
            )
            try persistState(state)
        }
    }

    func hasPendingRevocationSecretCleanup() throws -> Bool {
        try store.withExclusiveTransaction {
            try loadState().revocationSecretCleanup != nil
        }
    }

    /// Deletes every pending secret independently. Each successful deletion is
    /// durably removed from the marker before moving to the next item, so a
    /// crash can only cause an idempotent re-delete and never lose work.
    func retryRevocationSecretCleanup(
        secretStore: any PairedDeviceSecretStore
    ) throws {
        let pendingNames = try store.withExclusiveTransaction { () -> [String] in
            let state = try loadState()
            guard state.revoked, state.peerRevocation != nil else {
                if state.revocationSecretCleanup != nil {
                    throw PlatformSecurityError.persistenceFailure(
                        "Revocation secret cleanup exists without a peer tombstone."
                    )
                }
                return []
            }
            try state.revocationSecretCleanup?.validate()
            return state.revocationSecretCleanup?.remainingSecretNames ?? []
        }

        var failureCount = 0
        for name in pendingNames {
            do {
                try secretStore.delete(name: name)
                try markRevocationSecretDeleted(name)
            } catch {
                failureCount += 1
            }
        }
        guard failureCount == 0 else {
            throw PlatformSecurityError.persistenceFailure(
                "Could not delete \(failureCount) revoked pairing secret(s); cleanup remains pending."
            )
        }
    }

    private func markRevocationSecretDeleted(_ name: String) throws {
        try store.withExclusiveTransaction {
            var state = try loadState()
            guard var marker = state.revocationSecretCleanup else { return }
            try marker.validate()
            marker.remainingSecretNames.removeAll { $0 == name }
            state.revocationSecretCleanup = marker.remainingSecretNames.isEmpty ? nil : marker
            try persistState(state)
        }
    }

    /// Commits an authority-scoped nonce tombstone before a successful
    /// identity rotation is acknowledged to the peer.
    func consumeRotationNonceHash(_ nonceHash: Data) throws {
        guard nonceHash.count == 32 else {
            throw PlatformSecurityError.invalidInput("Rotation nonce hashes must be SHA-256 values.")
        }
        try store.withExclusiveTransaction {
            var state = try loadState()
            try requireActive(state)
            let encoded = nonceHash.map { String(format: "%02x", $0) }.joined()
            guard !state.usedRotationNonceHashes.contains(encoded) else {
                throw PlatformSecurityError.invalidInput("Rotation nonce was already used.")
            }
            state.usedRotationNonceHashes.insert(encoded)
            try persistState(state)
        }
    }
    private func requireActive(_ state: PersistedSecurityState) throws {
        guard !state.revoked, state.peerRevocation == nil else { throw PlatformSecurityError.revoked }
    }

    private func loadState() throws -> PersistedSecurityState {
        if let pairingIdentifier {
            return try store.validatePairingBinding(
                pairingIdentifier: pairingIdentifier
            )
        }
        return try store.load()
    }

    private func persistState(
        _ state: PersistedSecurityState,
        verifyReadBack: Bool = true
    ) throws {
        try store.persist(state)
        guard verifyReadBack else { return }
        let verified = try loadState()
        guard verified == state else {
            throw PlatformSecurityError.persistenceFailure(
                "Durable security state changed during its exclusive transaction."
            )
        }
    }
}

private extension NSRecursiveLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
