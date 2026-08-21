import Foundation

struct AdvancedChannelOwner: Equatable {
    let sessionIdentifier: String
    let sessionEpoch: UInt64
    let generation: UInt64

    var isValid: Bool {
        !sessionIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            sessionEpoch > 0 && generation > 0
    }
}

enum AdvancedChannelBinding: Equatable {
    case audio(displayID: String, streamID: UInt64)
    case bulk(transferID: Data)

    var channel: PlatformSecurityChannel {
        switch self {
        case .audio: return .audio
        case .bulk: return .bulk
        }
    }

    var isValid: Bool {
        switch self {
        case .audio(let displayID, let streamID):
            return !displayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                displayID.utf8.count <= 128 && streamID > 0
        case .bulk(let transferID):
            return (16...64).contains(transferID.count)
        }
    }
}

struct AdvancedChannelAdmission: Equatable {
    let identifier: UInt64
    let owner: AdvancedChannelOwner
    let binding: AdvancedChannelBinding
    let plaintextBytes: Int
}

enum AdvancedChannelSecurityError: Error, Equatable {
    case invalidOwner
    case invalidLimits
    case invalidBinding
    case emptyPayload
    case payloadTooLarge(maximum: Int)
    case backlogExceeded(maximum: Int)
    case staleOwner
    case unknownAdmission
    case sequenceExhausted
}

/// Bounded admission for Phase 5 channels. The caller must reserve before
/// sealing and finish after the corresponding DataChannel send completes.
final class AdvancedChannelSecurityGate {
    struct Limits: Equatable {
        static let standard = Limits(
            maximumAudioRecordBytes: InternetAudioRecordContract.maximumPlaintextRecordBytes,
            maximumAudioBacklogBytes: 1024 * 1_024,
            maximumBulkRecordBytes: InternetBulkRecordContract.maximumPlaintextRecordBytes,
            maximumBulkBacklogBytes: 4 * 1024 * 1024
        )

        let maximumAudioRecordBytes: Int
        let maximumAudioBacklogBytes: Int
        let maximumBulkRecordBytes: Int
        let maximumBulkBacklogBytes: Int
    }

    private let limits: Limits
    private let lock = NSLock()
    private var owner: AdvancedChannelOwner
    private var nextIdentifier: UInt64 = 1
    private var admissions: [UInt64: AdvancedChannelAdmission] = [:]
    private var bufferedBytes: [PlatformSecurityChannel: Int] = [:]

    init(owner: AdvancedChannelOwner, limits: Limits = .standard) throws {
        guard owner.isValid else {
            throw AdvancedChannelSecurityError.invalidOwner
        }
        guard limits.maximumAudioRecordBytes > 0,
              limits.maximumAudioBacklogBytes >= limits.maximumAudioRecordBytes,
              limits.maximumBulkRecordBytes > 0,
              limits.maximumBulkBacklogBytes >= limits.maximumBulkRecordBytes else {
            throw AdvancedChannelSecurityError.invalidLimits
        }
        self.owner = owner
        self.limits = limits
    }

    func reserve(
        payloadBytes: Int,
        binding: AdvancedChannelBinding,
        owner candidate: AdvancedChannelOwner
    ) throws -> AdvancedChannelAdmission {
        try synchronized {
            guard candidate == owner else { throw AdvancedChannelSecurityError.staleOwner }
            guard binding.isValid else { throw AdvancedChannelSecurityError.invalidBinding }
            guard payloadBytes > 0 else { throw AdvancedChannelSecurityError.emptyPayload }
            let channel = binding.channel
            let maximumRecord = channel == .audio
                ? limits.maximumAudioRecordBytes
                : limits.maximumBulkRecordBytes
            let maximumBacklog = channel == .audio
                ? limits.maximumAudioBacklogBytes
                : limits.maximumBulkBacklogBytes
            guard payloadBytes <= maximumRecord else {
                throw AdvancedChannelSecurityError.payloadTooLarge(maximum: maximumRecord)
            }
            let buffered = bufferedBytes[channel] ?? 0
            guard buffered <= maximumBacklog - payloadBytes else {
                throw AdvancedChannelSecurityError.backlogExceeded(maximum: maximumBacklog)
            }
            guard nextIdentifier < UInt64.max else {
                throw AdvancedChannelSecurityError.sequenceExhausted
            }
            let admission = AdvancedChannelAdmission(
                identifier: nextIdentifier,
                owner: candidate,
                binding: binding,
                plaintextBytes: payloadBytes
            )
            nextIdentifier += 1
            admissions[admission.identifier] = admission
            bufferedBytes[channel] = buffered + payloadBytes
            return admission
        }
    }

    func finish(_ admission: AdvancedChannelAdmission) throws {
        try synchronized {
            guard admission.owner == owner else { throw AdvancedChannelSecurityError.staleOwner }
            guard admissions[admission.identifier] == admission else {
                throw AdvancedChannelSecurityError.unknownAdmission
            }
            admissions.removeValue(forKey: admission.identifier)
            let channel = admission.binding.channel
            bufferedBytes[channel] = max(0, (bufferedBytes[channel] ?? 0) - admission.plaintextBytes)
        }
    }

    func replaceOwner(with replacement: AdvancedChannelOwner) throws {
        try synchronized {
            guard replacement.isValid else { throw AdvancedChannelSecurityError.invalidOwner }
            owner = replacement
            nextIdentifier = 1
            admissions.removeAll()
            bufferedBytes.removeAll()
        }
    }

    func bufferedBytes(for channel: PlatformSecurityChannel) -> Int {
        synchronized { bufferedBytes[channel] ?? 0 }
    }

    private func synchronized<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
