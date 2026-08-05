import Foundation

public enum TrustedLANHandshakeStatus: UInt8, Sendable {
    case ok = 0x00
    case invalidToken = 0x01
    case invalidMagic = 0x02
    case invalidName = 0x03
}

public enum TrustedLANHandshakeError: Error, Equatable, LocalizedError {
    case invalidTokenLength(Int)
    case invalidDeviceName
    case invalidResponseLength(Int)
    case invalidResponseMagic
    case unknownResponseStatus(UInt8)
    case rejected(TrustedLANHandshakeStatus)

    public var errorDescription: String? {
        switch self {
        case let .invalidTokenLength(length): "认证令牌长度无效：\(length)"
        case .invalidDeviceName: "设备名称必须是 1 到 64 字节的 UTF-8 文本"
        case let .invalidResponseLength(length): "认证响应长度无效：\(length)"
        case .invalidResponseMagic: "认证响应标识无效"
        case let .unknownResponseStatus(status): "认证响应状态未知：\(status)"
        case let .rejected(status): "主机拒绝认证：\(status)"
        }
    }
}

public enum TrustedLANHandshake {
    public static let responseLength = 5
    private static let requestMagic = Data("SSWA".utf8)
    private static let responseMagic = Data("SSWR".utf8)

    public static func request(token: Data, deviceName: String) throws -> Data {
        guard token.count == TrustedLANPairing.tokenLength else {
            throw TrustedLANHandshakeError.invalidTokenLength(token.count)
        }
        guard let name = deviceName.data(using: .utf8),
              (1...64).contains(name.count), !deviceName.contains("\0") else {
            throw TrustedLANHandshakeError.invalidDeviceName
        }
        var request = requestMagic
        request.append(token)
        request.append(UInt8(name.count))
        request.append(name)
        return request
    }

    public static func validateResponse(_ response: Data) throws {
        guard response.count == responseLength else {
            throw TrustedLANHandshakeError.invalidResponseLength(response.count)
        }
        guard response.prefix(responseMagic.count) == responseMagic else {
            throw TrustedLANHandshakeError.invalidResponseMagic
        }
        let rawStatus = response[response.index(response.startIndex, offsetBy: 4)]
        guard let status = TrustedLANHandshakeStatus(rawValue: rawStatus) else {
            throw TrustedLANHandshakeError.unknownResponseStatus(rawStatus)
        }
        guard status == .ok else { throw TrustedLANHandshakeError.rejected(status) }
    }
}
