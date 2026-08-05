import Foundation

public enum TrustedLANPairingError: Error, Equatable, LocalizedError {
    case invalidURL
    case invalidScheme
    case missingHost
    case invalidPort
    case invalidQuery
    case invalidToken
    case invalidName

    public var errorDescription: String? {
        switch self {
        case .invalidURL: "配对链接无效"
        case .invalidScheme: "配对链接协议必须是 telemachus"
        case .missingHost: "配对链接缺少主机"
        case .invalidPort: "配对链接端口无效"
        case .invalidQuery: "配对链接参数无效"
        case .invalidToken: "配对令牌必须是 32 字节 base64url 数据"
        case .invalidName: "配对链接中的主机名称无效"
        }
    }
}

public struct TrustedLANPairing: Equatable, Sendable {
    public static let tokenLength = 32
    public static let defaultPort: UInt16 = 54_321

    public let host: String
    public let port: UInt16
    public let token: Data
    public let hostName: String

    public init(
        host: String,
        port: UInt16 = defaultPort,
        token: Data,
        hostName: String
    ) throws {
        guard !host.isEmpty else { throw TrustedLANPairingError.missingHost }
        guard port != 0 else { throw TrustedLANPairingError.invalidPort }
        guard token.count == Self.tokenLength else { throw TrustedLANPairingError.invalidToken }
        guard Self.isValidName(hostName) else { throw TrustedLANPairingError.invalidName }
        self.host = host
        self.port = port
        self.token = token
        self.hostName = hostName
    }

    public init(urlString: String) throws {
        guard let components = URLComponents(string: urlString) else {
            throw TrustedLANPairingError.invalidURL
        }
        guard components.scheme?.lowercased() == "telemachus" else {
            throw TrustedLANPairingError.invalidScheme
        }
        guard components.user == nil, components.password == nil,
              components.path.isEmpty, components.fragment == nil else {
            throw TrustedLANPairingError.invalidURL
        }
        guard let host = components.host, !host.isEmpty else {
            throw TrustedLANPairingError.missingHost
        }
        guard components.port == nil || (components.port! > 0 && components.port! <= Int(UInt16.max)) else {
            throw TrustedLANPairingError.invalidPort
        }
        let port = components.port.map(UInt16.init) ?? Self.defaultPort
        guard let items = components.queryItems, items.count == 2,
              Set(items.map(\.name)) == Set(["t", "name"]),
              items.filter({ $0.name == "t" }).count == 1,
              items.filter({ $0.name == "name" }).count == 1 else {
            throw TrustedLANPairingError.invalidQuery
        }
        guard let encodedToken = items.first(where: { $0.name == "t" })?.value,
              let token = Self.decodeBase64URL(encodedToken),
              token.count == Self.tokenLength,
              Self.encodeBase64URL(token) == encodedToken else {
            throw TrustedLANPairingError.invalidToken
        }
        guard let hostName = items.first(where: { $0.name == "name" })?.value,
              Self.isValidName(hostName) else {
            throw TrustedLANPairingError.invalidName
        }

        self.host = host
        self.port = port
        self.token = token
        self.hostName = hostName
    }

    private static func isValidName(_ name: String) -> Bool {
        guard let bytes = name.data(using: .utf8) else { return false }
        return (1...64).contains(bytes.count) && !name.contains("\0")
    }

    private static func decodeBase64URL(_ encoded: String) -> Data? {
        guard !encoded.isEmpty,
              encoded.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }) else {
            return nil
        }
        var base64 = encoded.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = base64.count % 4
        if remainder != 0 {
            base64.append(String(repeating: "=", count: 4 - remainder))
        }
        return Data(base64Encoded: base64)
    }

    private static func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
