import Foundation

public struct ManagedPolicy: Equatable, Sendable {
    public static let defaultMaximumFileBytes: UInt64 = 512 * 1_024 * 1_024

    public let isManaged: Bool
    public let clipboardAllowed: Bool
    public let fileTransferAllowed: Bool
    public let audioAllowed: Bool
    public let wakeAllowed: Bool
    public let customGesturesAllowed: Bool
    public let maximumFileBytes: UInt64
    public let allowedHosts: Set<String>

    public static let unmanaged = ManagedPolicy(
        isManaged: false,
        clipboardAllowed: true,
        fileTransferAllowed: true,
        audioAllowed: true,
        wakeAllowed: true,
        customGesturesAllowed: true,
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
        maximumFileBytes: UInt64,
        allowedHosts: Set<String>
    ) {
        self.isManaged = isManaged
        self.clipboardAllowed = clipboardAllowed
        self.fileTransferAllowed = fileTransferAllowed
        self.audioAllowed = audioAllowed
        self.wakeAllowed = wakeAllowed
        self.customGesturesAllowed = customGesturesAllowed
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
            maximumFileBytes: maximum,
            allowedHosts: hosts
        )
    }

    public func applying(remote: ManagedPolicy) -> ManagedPolicy {
        ManagedPolicy(
            isManaged: isManaged || remote.isManaged,
            clipboardAllowed: clipboardAllowed && remote.clipboardAllowed,
            fileTransferAllowed: fileTransferAllowed && remote.fileTransferAllowed,
            audioAllowed: audioAllowed && remote.audioAllowed,
            wakeAllowed: wakeAllowed && remote.wakeAllowed,
            customGesturesAllowed: customGesturesAllowed && remote.customGesturesAllowed,
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
        static let maximumFileBytes = "MaximumFileBytes"
        static let allowedHosts = "AllowedHosts"
    }
}

public enum ManagedPolicyError: Error, Equatable {
    case invalidType(String)
}
