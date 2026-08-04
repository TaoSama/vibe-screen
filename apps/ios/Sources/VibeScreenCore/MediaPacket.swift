import Foundation
import VibeScreenProtocol

public struct MediaPacket: Sendable {
    private static let maximumHeaderBytes = 64 * 1_024
    public let header: VSMediaPacketHeader
    public let payload: Data

    public init(serializedFrame: Data) throws {
        var cursor = 0
        let headerLength = try Self.readVarint(from: serializedFrame, cursor: &cursor)
        guard headerLength <= Self.maximumHeaderBytes else {
            throw MediaPacketError.headerTooLarge(headerLength)
        }
        guard headerLength <= serializedFrame.count - cursor else {
            throw MediaPacketError.truncatedHeader
        }
        let headerBytes = serializedFrame.dropFirst(cursor).prefix(headerLength)
        header = try VSMediaPacketHeader(serializedBytes: headerBytes)
        payload = Data(serializedFrame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw MediaPacketError.payloadLengthMismatch(
                declared: Int(header.payloadLength),
                actual: payload.count
            )
        }
    }

    private static func readVarint(from data: Data, cursor: inout Int) throws -> Int {
        var value = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let byte = data[data.index(data.startIndex, offsetBy: cursor)]
            cursor += 1
            value |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { return value }
            shift += 7
        }
        throw MediaPacketError.invalidHeaderLength
    }
}

public enum MediaPacketError: Error, Equatable {
    case invalidHeaderLength
    case headerTooLarge(Int)
    case truncatedHeader
    case payloadLengthMismatch(declared: Int, actual: Int)
}
