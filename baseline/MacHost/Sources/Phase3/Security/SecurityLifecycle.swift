import Foundation

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
            return "The local device identity has been revoked."
        }
    }
}

struct PersistedSecurityState: Codable, Equatable {
    var sessionEpoch: UInt64 = 0
    var revocationSequence: UInt64 = 0
    var revoked = false
    var nonceHighWatermarks: [String: UInt64] = [:]
    var usedRotationNonceHashes: Set<String> = []

    init(
        sessionEpoch: UInt64 = 0,
        revocationSequence: UInt64 = 0,
        revoked: Bool = false,
        nonceHighWatermarks: [String: UInt64] = [:],
        usedRotationNonceHashes: Set<String> = []
    ) {
        self.sessionEpoch = sessionEpoch
        self.revocationSequence = revocationSequence
        self.revoked = revoked
        self.nonceHighWatermarks = nonceHighWatermarks
        self.usedRotationNonceHashes = usedRotationNonceHashes
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sessionEpoch = try container.decodeIfPresent(UInt64.self, forKey: .sessionEpoch) ?? 0
        revocationSequence = try container.decodeIfPresent(UInt64.self, forKey: .revocationSequence) ?? 0
        revoked = try container.decodeIfPresent(Bool.self, forKey: .revoked) ?? false
        nonceHighWatermarks = try container.decodeIfPresent([String: UInt64].self, forKey: .nonceHighWatermarks) ?? [:]
        usedRotationNonceHashes = try container.decodeIfPresent(Set<String>.self, forKey: .usedRotationNonceHashes) ?? []
    }
}

protocol SecurityStateStore {
    func load() throws -> PersistedSecurityState
    func persist(_ state: PersistedSecurityState) throws
}

/// Serializes all durable counters in-process. Every value is committed before
/// it is returned, so a crash can skip values but cannot reuse them.
final class SecurityLifecycle {
    private static let persistenceLock = NSLock()
    private let store: any SecurityStateStore

    init(store: any SecurityStateStore) {
        self.store = store
    }

    func beginSession() throws -> UInt64 {
        try Self.persistenceLock.withLock {
            var state = try store.load()
            guard !state.revoked else { throw PlatformSecurityError.revoked }
            guard state.sessionEpoch < UInt64.max else {
                throw PlatformSecurityError.exhausted("Session epoch is exhausted; rotate the device identity.")
            }
            state.sessionEpoch += 1
            try store.persist(state)
            return state.sessionEpoch
        }
    }

    func reserveNonce(channel: UInt32, senderRole: UInt32, keyEpoch: UInt64) throws -> Data {
        guard channel > 0, senderRole > 0, keyEpoch > 0 else {
            throw PlatformSecurityError.invalidInput("Channel, sender role, and key epoch must be positive.")
        }
        return try Self.persistenceLock.withLock {
            var state = try store.load()
            guard !state.revoked else { throw PlatformSecurityError.revoked }
            let counterKey = "\(channel):\(senderRole):\(keyEpoch)"
            let current = state.nonceHighWatermarks[counterKey] ?? 0
            guard current < UInt64.max else {
                throw PlatformSecurityError.exhausted("Nonce sequence is exhausted; rotate traffic keys.")
            }
            let sequence = current + 1
            state.nonceHighWatermarks[counterKey] = sequence
            try store.persist(state)

            var channelValue = channel.bigEndian
            var sequenceValue = sequence.bigEndian
            var nonce = Data(bytes: &channelValue, count: MemoryLayout<UInt32>.size)
            nonce.append(Data(bytes: &sequenceValue, count: MemoryLayout<UInt64>.size))
            return nonce
        }
    }

    func applyRevocation(sequence: UInt64) throws {
        try Self.persistenceLock.withLock {
            var state = try store.load()
            guard sequence > state.revocationSequence else {
                throw PlatformSecurityError.invalidInput("Revocation sequence must increase.")
            }
            state.revocationSequence = sequence
            state.revoked = true
            try store.persist(state)
        }
    }

    /// Commits an authority-scoped nonce tombstone before a successful
    /// identity rotation is acknowledged to the peer.
    func consumeRotationNonceHash(_ nonceHash: Data) throws {
        guard nonceHash.count == 32 else {
            throw PlatformSecurityError.invalidInput("Rotation nonce hashes must be SHA-256 values.")
        }
        try Self.persistenceLock.withLock {
            var state = try store.load()
            guard !state.revoked else { throw PlatformSecurityError.revoked }
            let encoded = nonceHash.map { String(format: "%02x", $0) }.joined()
            guard !state.usedRotationNonceHashes.contains(encoded) else {
                throw PlatformSecurityError.invalidInput("Rotation nonce was already used.")
            }
            state.usedRotationNonceHashes.insert(encoded)
            try store.persist(state)
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
