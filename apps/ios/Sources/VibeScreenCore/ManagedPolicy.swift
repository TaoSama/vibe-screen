import Foundation
import VibeScreenProtocol

public struct ManagedRestrictionResult: Equatable, Sendable {
    public static let clipboard = "clipboard"
    public static let fileTransfer = "file_transfer"
    public static let audio = "audio"
    public static let wake = "wake"
    public static let customGestures = "custom_gestures"
    public static let hostActions = "host_actions"
    public static let maximumFileBytes = "maximum_file_bytes"
    public static let allowedHosts = "allowed_hosts"
    public static let deniedHosts = "denied_hosts"

    public let restriction: String
    public let allowed: Bool
    public let source: String
    public let reason: String

    public var protocolResult: VSManagedRestrictionResult {
        var result = VSManagedRestrictionResult()
        result.restriction = restriction
        result.allowed = allowed
        result.source = source
        result.reason = reason
        return result
    }

    public init(restriction: String, allowed: Bool, source: String, reason: String) {
        self.restriction = restriction
        self.allowed = allowed
        self.source = source
        self.reason = reason
    }

    init(protocolResult: VSManagedRestrictionResult) {
        self.restriction = protocolResult.restriction
        self.allowed = protocolResult.allowed
        self.source = protocolResult.source
        self.reason = protocolResult.reason
    }
}

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
    public let allowedHostsRestricted: Bool
    public let deniedHosts: Set<String>
    public let restrictionResults: [ManagedRestrictionResult]

    public static let unmanaged = ManagedPolicy(
        isManaged: false,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
        hostActionsAllowed: true,
        maximumFileBytes: defaultMaximumFileBytes,
        allowedHosts: [],
        allowedHostsRestricted: false,
        restrictionResults: Self.results(
            source: "unmanaged",
            reason: "No local managed configuration is present.",
            clipboardAllowed: true,
            fileTransferAllowed: true,
            audioAllowed: true,
            wakeAllowed: true,
            customGesturesAllowed: true,
            hostActionsAllowed: true,
            maximumFileBytes: defaultMaximumFileBytes,
            allowedHostsRestricted: false,
            allowedHosts: [],
            deniedHosts: []
        )
    )

    public static let failClosed = ManagedPolicy(
        isManaged: true,
        clipboardAllowed: false,
        fileTransferAllowed: false,
        audioAllowed: false,
        wakeAllowed: false,
        customGesturesAllowed: false,
        hostActionsAllowed: false,
        maximumFileBytes: 0,
        allowedHosts: [],
        allowedHostsRestricted: true,
        restrictionResults: Self.results(
            source: "local_parse_error",
            reason: "Invalid local managed configuration; all product restrictions deny by default.",
            clipboardAllowed: false,
            fileTransferAllowed: false,
            audioAllowed: false,
            wakeAllowed: false,
            customGesturesAllowed: false,
            hostActionsAllowed: false,
            maximumFileBytes: 0,
            allowedHostsRestricted: true,
            allowedHosts: [],
            deniedHosts: []
        )
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
        allowedHosts: Set<String>,
        allowedHostsRestricted: Bool? = nil,
        deniedHosts: Set<String> = [],
        restrictionResults: [ManagedRestrictionResult]? = nil
    ) {
        let normalizedHosts = Self.normalizedHosts(allowedHosts)
        let normalizedDeniedHosts = Self.normalizedHosts(deniedHosts)
        let restricted = allowedHostsRestricted ?? !normalizedHosts.isEmpty
        self.isManaged = isManaged
        self.clipboardAllowed = clipboardAllowed
        let effectiveFileTransferAllowed = fileTransferAllowed && maximumFileBytes > 0
        self.fileTransferAllowed = effectiveFileTransferAllowed
        self.audioAllowed = audioAllowed
        self.wakeAllowed = wakeAllowed
        self.customGesturesAllowed = customGesturesAllowed
        self.hostActionsAllowed = hostActionsAllowed
        self.maximumFileBytes = maximumFileBytes
        self.allowedHosts = normalizedHosts
        self.allowedHostsRestricted = restricted
        self.deniedHosts = normalizedDeniedHosts
        self.restrictionResults = restrictionResults ?? Self.results(
            source: isManaged ? "managed_configuration" : "unmanaged",
            reason: isManaged ? "Local managed configuration result." : "No local managed configuration is present.",
            clipboardAllowed: clipboardAllowed,
            fileTransferAllowed: effectiveFileTransferAllowed,
            audioAllowed: audioAllowed,
            wakeAllowed: wakeAllowed,
            customGesturesAllowed: customGesturesAllowed,
            hostActionsAllowed: hostActionsAllowed,
            maximumFileBytes: maximumFileBytes,
            allowedHostsRestricted: restricted,
            allowedHosts: normalizedHosts,
            deniedHosts: normalizedDeniedHosts
        )
    }

    public init(managedConfiguration: [String: Any]?) throws {
        let parsed = try ManagedConfigurationSchema.parse(managedConfiguration)
        guard let configuration = parsed else {
            self = .unmanaged
            return
        }
        self.init(
            isManaged: true,
            clipboardAllowed: configuration.clipboardAllowed,
            fileTransferAllowed: configuration.fileTransferAllowed,
            audioAllowed: configuration.audioAllowed,
            wakeAllowed: configuration.wakeAllowed,
            customGesturesAllowed: configuration.customGesturesAllowed,
            hostActionsAllowed: configuration.hostActionsAllowed,
            maximumFileBytes: configuration.maximumFileBytes,
            allowedHosts: configuration.allowedHosts,
            deniedHosts: configuration.deniedHosts
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
        let hosts = Set(remoteStatus.allowedHosts.filter { !Self.isBlankHost($0) })
        let deniedHosts = Set(remoteStatus.deniedHosts.filter { !Self.isBlankHost($0) })
        let results = remoteStatus.restrictionResults.map(ManagedRestrictionResult.init(protocolResult:))
        self.init(
            isManaged: true,
            clipboardAllowed: remoteStatus.clipboardAllowed,
            fileTransferAllowed: remoteStatus.fileTransferAllowed,
            audioAllowed: remoteStatus.audioAllowed,
            wakeAllowed: remoteStatus.wakeAllowed,
            customGesturesAllowed: remoteStatus.customGesturesAllowed,
            hostActionsAllowed: remoteStatus.hostActionsAllowed,
            maximumFileBytes: remoteStatus.maximumFileBytes,
            allowedHosts: hosts,
            allowedHostsRestricted: remoteStatus.allowedHostsRestricted || !hosts.isEmpty,
            deniedHosts: deniedHosts,
            restrictionResults: results.isEmpty ? nil : results
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
        status.allowedHostsRestricted = allowedHostsRestricted
        status.restrictionResults = restrictionResults.map(\.protocolResult)
        status.deniedHosts = deniedHosts.sorted()
        return status
    }

    public func applying(remote: ManagedPolicy) -> ManagedPolicy {
        // An unmanaged remote (including legacy peers that never set the
        // managed flag) imposes no restrictions, so it must not tighten any
        // local policy field (e.g. it must not lower maximumFileBytes).
        guard remote.isManaged else { return self }
        let restricted = allowedHostsRestricted || remote.allowedHostsRestricted
        let hosts: Set<String>
        switch (allowedHostsRestricted, remote.allowedHostsRestricted) {
        case (true, true): hosts = allowedHosts.intersection(remote.allowedHosts)
        case (true, false): hosts = allowedHosts
        case (false, true): hosts = remote.allowedHosts
        case (false, false): hosts = []
        }
        let effectiveDeniedHosts = self.deniedHosts.union(remote.deniedHosts)
        let effectiveHosts = hosts.subtracting(effectiveDeniedHosts)
        let clipboard = clipboardAllowed && remote.clipboardAllowed
        let audio = audioAllowed && remote.audioAllowed
        let wake = wakeAllowed && remote.wakeAllowed
        let gestures = customGesturesAllowed && remote.customGesturesAllowed
        let hostActions = hostActionsAllowed && remote.hostActionsAllowed
        let maximum = min(maximumFileBytes, remote.maximumFileBytes)
        let fileTransfer = fileTransferAllowed && remote.fileTransferAllowed && maximum > 0
        return ManagedPolicy(
            isManaged: true,
            clipboardAllowed: clipboard,
            fileTransferAllowed: fileTransfer,
            audioAllowed: audio,
            wakeAllowed: wake,
            customGesturesAllowed: gestures,
            hostActionsAllowed: hostActions,
            maximumFileBytes: maximum,
            allowedHosts: effectiveHosts,
            allowedHostsRestricted: restricted,
            deniedHosts: effectiveDeniedHosts,
            restrictionResults: Self.results(
                source: "effective_deny_wins",
                reason: "Local and remote managed policy were combined with deny-wins semantics.",
                clipboardAllowed: clipboard,
                fileTransferAllowed: fileTransfer,
                audioAllowed: audio,
                wakeAllowed: wake,
                customGesturesAllowed: gestures,
                hostActionsAllowed: hostActions,
                maximumFileBytes: maximum,
                allowedHostsRestricted: restricted,
                allowedHosts: effectiveHosts,
                deniedHosts: effectiveDeniedHosts
            )
        )
    }

    public func allows(host: String) -> Bool {
        guard let normalized = Self.normalizedHost(host) else { return !allowedHostsRestricted }
        guard !deniedHosts.contains(normalized) else { return false }
        return !allowedHostsRestricted || allowedHosts.contains(normalized)
    }

    public static func validateRestrictionResults(_ status: VSManagedPolicyStatus) -> Bool {
        guard status.managed else { return true }
        let results = status.restrictionResults
        guard results.count == requiredRestrictionNames.count else { return false }
        let grouped = Dictionary(grouping: results, by: \.restriction)
        guard Set(grouped.keys) == requiredRestrictionNames,
              grouped.values.allSatisfy({ $0.count == 1 }) else { return false }
        let normalizedHosts = Set(status.allowedHosts.compactMap(normalizedHost))
        let deniedHosts = Set(status.deniedHosts.compactMap(normalizedHost))
        return results.allSatisfy { result in
            guard !result.source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  !result.reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
            switch result.restriction {
            case ManagedRestrictionResult.clipboard: return result.allowed == status.clipboardAllowed
            case ManagedRestrictionResult.fileTransfer: return result.allowed == (status.fileTransferAllowed && status.maximumFileBytes > 0)
            case ManagedRestrictionResult.audio: return result.allowed == status.audioAllowed
            case ManagedRestrictionResult.wake: return result.allowed == status.wakeAllowed
            case ManagedRestrictionResult.customGestures: return result.allowed == status.customGesturesAllowed
            case ManagedRestrictionResult.hostActions: return result.allowed == status.hostActionsAllowed
            case ManagedRestrictionResult.maximumFileBytes: return result.allowed == (status.maximumFileBytes > 0)
            case ManagedRestrictionResult.allowedHosts:
                let restricted = status.allowedHostsRestricted || !normalizedHosts.isEmpty
                return result.allowed == (!restricted || !normalizedHosts.subtracting(deniedHosts).isEmpty)
            case ManagedRestrictionResult.deniedHosts:
                return result.allowed == deniedHosts.isEmpty
            default: return false
            }
        }
    }

    private static func normalizedHosts(_ hosts: Set<String>) -> Set<String> {
        Set(hosts.compactMap(normalizedHost))
    }

    public static let requiredRestrictionNames: Set<String> = [
        ManagedRestrictionResult.clipboard,
        ManagedRestrictionResult.fileTransfer,
        ManagedRestrictionResult.audio,
        ManagedRestrictionResult.wake,
        ManagedRestrictionResult.customGestures,
        ManagedRestrictionResult.hostActions,
        ManagedRestrictionResult.maximumFileBytes,
        ManagedRestrictionResult.allowedHosts,
        ManagedRestrictionResult.deniedHosts
    ]

    private static func results(
        source: String,
        reason: String,
        clipboardAllowed: Bool,
        fileTransferAllowed: Bool,
        audioAllowed: Bool,
        wakeAllowed: Bool,
        customGesturesAllowed: Bool,
        hostActionsAllowed: Bool,
        maximumFileBytes: UInt64,
        allowedHostsRestricted: Bool,
        allowedHosts: Set<String>,
        deniedHosts: Set<String>
    ) -> [ManagedRestrictionResult] {
        let effectiveAllowedHosts = allowedHosts.subtracting(deniedHosts)
        return [
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.clipboard, allowed: clipboardAllowed, source: source, reason: reason),
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.fileTransfer, allowed: fileTransferAllowed, source: source, reason: reason),
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.audio, allowed: audioAllowed, source: source, reason: reason),
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.wake, allowed: wakeAllowed, source: source, reason: reason),
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.customGestures, allowed: customGesturesAllowed, source: source, reason: reason),
            ManagedRestrictionResult(restriction: ManagedRestrictionResult.hostActions, allowed: hostActionsAllowed, source: source, reason: reason),
            ManagedRestrictionResult(
                restriction: ManagedRestrictionResult.maximumFileBytes,
                allowed: maximumFileBytes > 0,
                source: source,
                reason: "\(reason) maximum_file_bytes=\(maximumFileBytes)."
            ),
            ManagedRestrictionResult(
                restriction: ManagedRestrictionResult.allowedHosts,
                allowed: !allowedHostsRestricted || !effectiveAllowedHosts.isEmpty,
                source: source,
                reason: allowedHostsRestricted
                    ? "\(reason) allowed_hosts=\(effectiveAllowedHosts.sorted().joined(separator: ","))."
                    : "\(reason) allowed_hosts unrestricted."
            ),
            ManagedRestrictionResult(
                restriction: ManagedRestrictionResult.deniedHosts,
                allowed: deniedHosts.isEmpty,
                source: source,
                reason: deniedHosts.isEmpty
                    ? "\(reason) denied_hosts empty."
                    : "\(reason) denied_hosts=\(deniedHosts.sorted().joined(separator: ","))."
            )
        ]
    }

    private static func isBlankHost(_ host: String) -> Bool {
        normalizedHost(host) == nil
    }

    private static func normalizedHost(_ host: String) -> String? {
        let trimmed = host.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed.lowercased()
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
        static let deniedHosts = "DeniedHosts"
    }

    public struct ManagedConfigurationSchema: Equatable, Sendable {
        public static let managedConfigurationKey = "com.apple.configuration.managed"

        public let clipboardAllowed: Bool
        public let fileTransferAllowed: Bool
        public let audioAllowed: Bool
        public let wakeAllowed: Bool
        public let customGesturesAllowed: Bool
        public let hostActionsAllowed: Bool
        public let maximumFileBytes: UInt64
        public let allowedHosts: Set<String>
        public let deniedHosts: Set<String>

        public static func parse(_ raw: [String: Any]?) throws -> ManagedConfigurationSchema? {
            guard let raw, !raw.isEmpty else { return nil }
            return ManagedConfigurationSchema(
                clipboardAllowed: try requiredBool(Keys.clipboardAllowed, in: raw),
                fileTransferAllowed: try requiredBool(Keys.fileTransferAllowed, in: raw),
                audioAllowed: try requiredBool(Keys.audioAllowed, in: raw),
                wakeAllowed: try requiredBool(Keys.wakeAllowed, in: raw),
                customGesturesAllowed: try requiredBool(Keys.customGesturesAllowed, in: raw),
                hostActionsAllowed: try requiredBool(Keys.hostActionsAllowed, in: raw),
                maximumFileBytes: try optionalUInt64(Keys.maximumFileBytes, in: raw) ?? 0,
                allowedHosts: try optionalStringSet(Keys.allowedHosts, in: raw) ?? [],
                deniedHosts: try optionalStringSet(Keys.deniedHosts, in: raw) ?? []
            )
        }

        private static func requiredBool(_ key: String, in raw: [String: Any]) throws -> Bool {
            guard let value = raw[key] else { return false }
            guard let value = value as? Bool else { throw ManagedPolicyError.invalidType(key) }
            return value
        }

        private static func optionalUInt64(_ key: String, in raw: [String: Any]) throws -> UInt64? {
            guard let value = raw[key] else { return nil }
            guard let number = value as? NSNumber, !Self.isBooleanNumber(number) else {
                throw ManagedPolicyError.invalidType(key)
            }
            switch String(cString: number.objCType) {
            case "c", "s", "i", "l", "q":
                let signedValue = number.int64Value
                guard signedValue >= 0 else { throw ManagedPolicyError.invalidType(key) }
                return UInt64(signedValue)
            case "C", "S", "I", "L", "Q":
                return number.uint64Value
            default:
                break
            }
            let doubleValue = number.doubleValue
            guard doubleValue.isFinite,
                  doubleValue >= 0,
                  doubleValue < Double(UInt64.max),
                  doubleValue.rounded(.towardZero) == doubleValue else {
                throw ManagedPolicyError.invalidType(key)
            }
            return UInt64(doubleValue)
        }

        private static func optionalStringSet(_ key: String, in raw: [String: Any]) throws -> Set<String>? {
            guard let value = raw[key] else { return nil }
            guard let strings = value as? [String] else { throw ManagedPolicyError.invalidType(key) }
            return Set(strings.filter { !ManagedPolicy.isBlankHost($0) })
        }

        private static func isBooleanNumber(_ number: NSNumber) -> Bool {
            CFGetTypeID(number) == CFBooleanGetTypeID()
        }
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

public enum ManagedPolicyError: LocalizedError, Equatable {
    case invalidType(String)

    public var errorDescription: String? {
        switch self {
        case .invalidType(let key):
            return "Invalid managed configuration value for \(key)."
        }
    }
}
