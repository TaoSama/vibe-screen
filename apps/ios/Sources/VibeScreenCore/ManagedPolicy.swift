import Foundation
import VibeScreenProtocol

public struct ManagedPolicy: Equatable, Sendable {
    public static let defaultMaximumFileBytes: UInt64 = 512 * 1_024 * 1_024

    public let isManaged: Bool
    public let clipboardAllowed: Bool
    public let fileTransferAllowed: Bool
    public let audioAllowed: Bool
    public let wakeAllowed: Bool
    public let customGesturesAllowed: Bool
    public let hostActionsAllowed: Bool
    public let maximumFileBytes: UInt64
    public let allowedHosts: Set<String>

    public static let unmanaged = ManagedPolicy(
        isManaged: false,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: defaultMaximumFileBytes,
        allowedHosts: []
    )

    public init(
        isManaged: Bool,
        clipboardAllowed: Bool,
        fileTransferAllowed: Bool,
        audioAllowed: Bool,
        wakeAllowed: Bool,
        customGesturesAllowed: Bool,
        hostActionsAllowed: Bool,
        maximumFileBytes: UInt64,
        allowedHosts: Set<String>
    ) {
        self.isManaged = isManaged
        self.clipboardAllowed = clipboardAllowed
        self.fileTransferAllowed = fileTransferAllowed
        self.audioAllowed = audioAllowed
        self.wakeAllowed = wakeAllowed
        self.customGesturesAllowed = customGesturesAllowed
        self.hostActionsAllowed = hostActionsAllowed
        self.maximumFileBytes = maximumFileBytes
        self.allowedHosts = allowedHosts
    }

    public init(managedConfiguration: [String: Any]?) throws {
        guard let configuration = managedConfiguration, !configuration.isEmpty else {
            self = .unmanaged
            return
        }
        func requiredBool(_ key: String) throws -> Bool {
            guard let value = configuration[key] else { return false }
            guard let value = value as? Bool else { throw ManagedPolicyError.invalidType(key) }
            return value
        }
        let maximum: UInt64
        if let value = configuration[Keys.maximumFileBytes] {
            guard let number = value as? NSNumber, number.int64Value >= 0 else {
                throw ManagedPolicyError.invalidType(Keys.maximumFileBytes)
            }
            maximum = UInt64(number.int64Value)
        } else {
            maximum = 0
        }
        let hosts: Set<String>
        if let value = configuration[Keys.allowedHosts] {
            guard let strings = value as? [String] else {
                throw ManagedPolicyError.invalidType(Keys.allowedHosts)
            }
            hosts = Set(strings.filter { !$0.isEmpty })
        } else {
            hosts = []
        }
        self.init(
            isManaged: true,
            clipboardAllowed: try requiredBool(Keys.clipboardAllowed),
            fileTransferAllowed: try requiredBool(Keys.fileTransferAllowed),
            audioAllowed: try requiredBool(Keys.audioAllowed),
            wakeAllowed: try requiredBool(Keys.wakeAllowed),
            customGesturesAllowed: try requiredBool(Keys.customGesturesAllowed),
            hostActionsAllowed: try requiredBool(Keys.hostActionsAllowed),
            maximumFileBytes: maximum,
            allowedHosts: hosts
        )
    }

    /// Creates a policy from a peer's ``VSManagedPolicyStatus``.
    ///
    /// When the peer does not advertise managed policy support (`managed == false`,
    /// including legacy peers that never set the field), the remote policy is
    /// treated as fully permissive so it cannot accidentally deny local features.
    /// When `managed == true`, every field is taken verbatim from the status;
    /// because protobuf defaults booleans to `false`, any unset capability is
    /// denied (fail-closed).
    public init(remoteStatus: VSManagedPolicyStatus) {
        guard remoteStatus.managed else {
            self = .unmanaged
            return
        }
        self.init(
            isManaged: true,
            clipboardAllowed: remoteStatus.clipboardAllowed,
            fileTransferAllowed: remoteStatus.fileTransferAllowed,
            audioAllowed: remoteStatus.audioAllowed,
            wakeAllowed: remoteStatus.wakeAllowed,
            customGesturesAllowed: remoteStatus.customGesturesAllowed,
            hostActionsAllowed: remoteStatus.hostActionsAllowed,
            maximumFileBytes: remoteStatus.maximumFileBytes,
            allowedHosts: Set(remoteStatus.allowedHosts.filter { !$0.isEmpty })
        )
    }

    public var protocolStatus: VSManagedPolicyStatus {
        var status = VSManagedPolicyStatus()
        status.managed = isManaged
        status.clipboardAllowed = clipboardAllowed
        status.fileTransferAllowed = fileTransferAllowed
        status.audioAllowed = audioAllowed
        status.wakeAllowed = wakeAllowed
        status.customGesturesAllowed = customGesturesAllowed
        status.hostActionsAllowed = hostActionsAllowed
        status.maximumFileBytes = maximumFileBytes
        status.allowedHosts = allowedHosts.sorted()
        return status
    }

    public func applying(remote: ManagedPolicy) -> ManagedPolicy {
        // An unmanaged remote (including legacy peers that never set the
        // managed flag) imposes no restrictions, so it must not tighten any
        // local policy field (e.g. it must not lower maximumFileBytes).
        guard remote.isManaged else { return self }
        return ManagedPolicy(
            isManaged: isManaged || remote.isManaged,
            clipboardAllowed: clipboardAllowed && remote.clipboardAllowed,
            fileTransferAllowed: fileTransferAllowed && remote.fileTransferAllowed,
            audioAllowed: audioAllowed && remote.audioAllowed,
            wakeAllowed: wakeAllowed && remote.wakeAllowed,
            customGesturesAllowed: customGesturesAllowed && remote.customGesturesAllowed,
            hostActionsAllowed: hostActionsAllowed && remote.hostActionsAllowed,
            maximumFileBytes: min(maximumFileBytes, remote.maximumFileBytes),
            allowedHosts: allowedHosts.isEmpty ? remote.allowedHosts :
                (remote.allowedHosts.isEmpty ? allowedHosts : allowedHosts.intersection(remote.allowedHosts))
        )
    }

    private enum Keys {
        static let clipboardAllowed = "ClipboardAllowed"
        static let fileTransferAllowed = "FileTransferAllowed"
        static let audioAllowed = "AudioAllowed"
        static let wakeAllowed = "WakeAllowed"
        static let customGesturesAllowed = "CustomGesturesAllowed"
        static let hostActionsAllowed = "HostActionsAllowed"
        static let maximumFileBytes = "MaximumFileBytes"
        static let allowedHosts = "AllowedHosts"
    }
}

/// Holds the local (MDM) and remote (peer) managed policies and derives the
/// effective policy by applying the remote on top of the local one.
///
/// The effective policy is always recomputed from the stored local and remote
/// policies, so updating the remote policy never accumulates denials on top of
/// a previously computed effective policy.
public struct ManagedPolicyResolver: Equatable, Sendable {
    public private(set) var localPolicy: ManagedPolicy
    public private(set) var remotePolicy: ManagedPolicy?

    public var effectivePolicy: ManagedPolicy {
        remotePolicy.map { localPolicy.applying(remote: $0) } ?? localPolicy
    }

    public init(localPolicy: ManagedPolicy = .unmanaged, remotePolicy: ManagedPolicy? = nil) {
        self.localPolicy = localPolicy
        self.remotePolicy = remotePolicy
    }

    public mutating func setLocal(_ policy: ManagedPolicy) {
        localPolicy = policy
    }

    public mutating func setRemote(_ policy: ManagedPolicy?) {
        remotePolicy = policy
    }

    /// Clears the remote policy so the effective policy falls back to the local
    /// policy only. Call this when a session ends to avoid applying a stale
    /// remote policy from a previous peer to the next session.
    public mutating func clearRemote() {
        remotePolicy = nil
    }
}

public enum ManagedPolicyError: Error, Equatable {
    case invalidType(String)
}
