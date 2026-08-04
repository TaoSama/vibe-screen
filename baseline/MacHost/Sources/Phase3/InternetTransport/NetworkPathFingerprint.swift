import CryptoKit
import Foundation
import Network

enum NetworkPathFingerprint {
    static func make(_ path: NWPath) -> String {
        var components = [
            "status=\(status(path.status))",
            "expensive=\(path.isExpensive)",
            "constrained=\(path.isConstrained)",
            "dns=\(path.supportsDNS)",
            "ipv4=\(path.supportsIPv4)",
            "ipv6=\(path.supportsIPv6)",
        ]
        components += path.availableInterfaces.map {
            "interface=\(interfaceType($0.type)):\($0.name)"
        }.sorted()
        components += path.gateways.map {
            // Endpoint text may contain an address, but it exists only in this
            // in-memory preimage. Only the SHA-256 digest leaves this function.
            "gateway=\(String(describing: $0))"
        }.sorted()
        // Network.framework's description includes endpoint-relevant route
        // generation details that are not otherwise public (for example a
        // same-interface address/VPN transition). It is hashed immediately and
        // is never logged or returned as plaintext.
        components.append("path-generation=\(String(describing: path))")
        return digest(components: components)
    }

    static func digest(components: [String]) -> String {
        let canonical = components.sorted().joined(separator: "\u{1f}")
        return Data(SHA256.hash(data: Data(canonical.utf8)))
            .prefix(16)
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private static func status(_ status: NWPath.Status) -> String {
        switch status {
        case .satisfied: return "satisfied"
        case .unsatisfied: return "unsatisfied"
        case .requiresConnection: return "requires-connection"
        @unknown default: return "unknown"
        }
    }

    private static func interfaceType(_ type: NWInterface.InterfaceType) -> String {
        switch type {
        case .wifi: return "wifi"
        case .wiredEthernet: return "wired"
        case .cellular: return "cellular"
        case .loopback: return "loopback"
        case .other: return "other"
        @unknown default: return "unknown"
        }
    }
}
