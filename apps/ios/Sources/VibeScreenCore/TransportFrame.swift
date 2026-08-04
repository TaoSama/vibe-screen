import Foundation

public enum LogicalChannel: UInt8, Sendable {
    case control = 1
    case video = 2
    case audio = 3
    case bulkTransfer = 4
}

public struct TransportFrame: Equatable, Sendable {
    public let channel: LogicalChannel
    public let payload: Data

    public init(channel: LogicalChannel, payload: Data) {
        self.channel = channel
        self.payload = payload
    }

    public func encoded() throws -> Data {
        guard payload.count <= TransportFramer.maximumPayloadBytes else {
            throw TransportFramerError.payloadTooLarge(payload.count)
        }
        var data = Data([channel.rawValue])
        var length = UInt32(payload.count).bigEndian
        withUnsafeBytes(of: &length) { data.append(contentsOf: $0) }
        data.append(payload)
        return data
    }
}

public enum TransportFramerError: Error, Equatable {
    case unknownChannel(UInt8)
    case payloadTooLarge(Int)
}

public struct TransportFramer: Sendable {
    public static let headerLength = 5
    public static let maximumPayloadBytes = 16 * 1_024 * 1_024

    private var buffer = Data()

    public init() {}

    public mutating func append(_ incoming: Data) throws -> [TransportFrame] {
        buffer.append(incoming)
        var frames: [TransportFrame] = []

        while buffer.count >= Self.headerLength {
            guard let channel = LogicalChannel(rawValue: buffer[buffer.startIndex]) else {
                throw TransportFramerError.unknownChannel(buffer[buffer.startIndex])
            }
            let lengthBytes = buffer.dropFirst().prefix(4)
            let length = lengthBytes.reduce(UInt32.zero) { ($0 << 8) | UInt32($1) }
            guard length <= Self.maximumPayloadBytes else {
                throw TransportFramerError.payloadTooLarge(Int(length))
            }
            let totalLength = Self.headerLength + Int(length)
            guard buffer.count >= totalLength else { break }
            let payload = Data(buffer.dropFirst(Self.headerLength).prefix(Int(length)))
            frames.append(TransportFrame(channel: channel, payload: payload))
            buffer.removeFirst(totalLength)
        }

        return frames
    }
}
