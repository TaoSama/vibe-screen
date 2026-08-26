import Foundation

package enum MacHostLoopbackTestConfigurationError: Error, Equatable, LocalizedError {
    case invalidPort(String)

    package var errorDescription: String? {
        switch self {
        case .invalidPort(let value):
            return "\(MacHostLoopbackTestConfiguration.portEnvironmentVariable) " +
                "必须是 1 到 65535 的 ASCII 十进制端口；收到“\(value)”"
        }
    }
}

package enum MacHostLoopbackTestConfiguration {
    package static let portEnvironmentVariable = "VIBE_SCREEN_IOS_LOOPBACK_PORT"
    package static let legacyPlaintextEnvironmentVariable = "VIBE_SCREEN_IOS_LOOPBACK_LEGACY_PLAINTEXT"

    package static func port(environment: [String: String]) throws -> UInt16 {
        guard let value = environment[portEnvironmentVariable] else {
            return TrustedLANPairing.defaultPort
        }
        guard !value.isEmpty,
              value.utf8.allSatisfy({ (48...57).contains($0) }),
              let port = UInt16(value),
              port != 0 else {
            throw MacHostLoopbackTestConfigurationError.invalidPort(value)
        }
        return port
    }

    package static func allowsLegacyPlaintext(environment: [String: String]) -> Bool {
        environment[legacyPlaintextEnvironmentVariable] == "1"
    }
}
