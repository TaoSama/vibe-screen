import Foundation

public enum ProtocolV1UpgradeError: Error, Equatable, LocalizedError {
    case invalidAcknowledgement(Data)

    public var errorDescription: String? {
        switch self {
        case let .invalidAcknowledgement(data):
            "主机未接受 Protocol v1 升级：\(data.map { String(format: "%02x", $0) }.joined())"
        }
    }
}

public enum ProtocolV1Upgrade {
    public static let offer = Data([0x0D])
    public static let acknowledgement = Data([0x0D, 0x01])

    public static func validateAcknowledgement(_ data: Data) throws {
        guard data == acknowledgement else {
            throw ProtocolV1UpgradeError.invalidAcknowledgement(data)
        }
    }
}
