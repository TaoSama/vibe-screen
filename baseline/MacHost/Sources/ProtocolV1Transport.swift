import Foundation
import VibeScreenProtocol

enum ProtocolV1Upgrade {
    static let offer: UInt8 = 0x0D
    static let acknowledgement = Data([offer, 0x01])
}

enum ProtocolV1LogicalChannel: UInt8, Equatable {
    case control = 1
    case video = 2
}

struct ProtocolV1TransportFrame: Equatable {
    let channel: ProtocolV1LogicalChannel
    let payload: Data

    func encoded() throws -> Data {
        guard payload.count <= ProtocolV1Framer.maximumPayloadBytes else {
            throw ProtocolV1FramerError.payloadTooLarge(payload.count)
        }
        var result = Data([channel.rawValue])
        var length = UInt32(payload.count).bigEndian
        withUnsafeBytes(of: &length) { result.append(contentsOf: $0) }
        result.append(payload)
        return result
    }
}

enum ProtocolV1FramerError: Error, Equatable {
    case unknownChannel(UInt8)
    case payloadTooLarge(Int)
}

struct ProtocolV1Framer {
    static let headerBytes = 5
    static let maximumPayloadBytes = 16 * 1_024 * 1_024

    private var buffer = Data()

    mutating func append(_ bytes: Data) throws -> [ProtocolV1TransportFrame] {
        buffer.append(bytes)
        var frames: [ProtocolV1TransportFrame] = []
        while buffer.count >= Self.headerBytes {
            let rawChannel = buffer[buffer.startIndex]
            guard let channel = ProtocolV1LogicalChannel(rawValue: rawChannel) else {
                throw ProtocolV1FramerError.unknownChannel(rawChannel)
            }
            let length = buffer.dropFirst().prefix(4).reduce(UInt32.zero) {
                ($0 << 8) | UInt32($1)
            }
            guard length <= Self.maximumPayloadBytes else {
                throw ProtocolV1FramerError.payloadTooLarge(Int(length))
            }
            let frameBytes = Self.headerBytes + Int(length)
            guard buffer.count >= frameBytes else { break }
            frames.append(ProtocolV1TransportFrame(
                channel: channel,
                payload: Data(buffer.dropFirst(Self.headerBytes).prefix(Int(length)))
            ))
            buffer.removeFirst(frameBytes)
        }
        return frames
    }
}

enum ProtocolV1MediaPacketError: Error, Equatable {
    case headerTooLarge(Int)
    case payloadTooLarge(Int)
}

enum ProtocolV1MediaPacketCodec {
    private static let maximumHeaderBytes = 64 * 1_024

    static func encode(header: VSMediaPacketHeader, payload: Data) throws -> Data {
        guard payload.count <= ProtocolV1Framer.maximumPayloadBytes else {
            throw ProtocolV1MediaPacketError.payloadTooLarge(payload.count)
        }
        var header = header
        header.payloadLength = UInt32(payload.count)
        let headerBytes = try header.serializedData()
        guard headerBytes.count <= maximumHeaderBytes else {
            throw ProtocolV1MediaPacketError.headerTooLarge(headerBytes.count)
        }
        var result = encodeVarint(headerBytes.count)
        result.append(headerBytes)
        result.append(payload)
        return result
    }

    private static func encodeVarint(_ value: Int) -> Data {
        var remaining = UInt64(value)
        var result = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining != 0 { byte |= 0x80 }
            result.append(byte)
        } while remaining != 0
        return result
    }
}

struct ProtocolV1LegacyTouchDispatch: Equatable {
    let x1: Float
    let y1: Float
    let action: Int
    let pointerCount: Int
    let x2: Float
    let y2: Float
}

struct ProtocolV1TouchAggregator {
    private var activePointers: [UInt32: (x: Float, y: Float)] = [:]

    mutating func reset() {
        activePointers.removeAll(keepingCapacity: true)
    }

    mutating func handle(
        pointerID: UInt32,
        x: Float,
        y: Float,
        phase: VSInputPhase
    ) -> ProtocolV1LegacyTouchDispatch? {
        let action: Int
        switch phase {
        case .began: action = 0
        case .changed: action = 1
        case .ended, .cancelled: action = 2
        default: return nil
        }
        guard activePointers[pointerID] != nil || activePointers.count < 2 else { return nil }
        activePointers[pointerID] = (x, y)
        let ordered = activePointers.sorted { $0.key < $1.key }.map(\.value)
        guard let first = ordered.first else { return nil }
        let dispatch = ProtocolV1LegacyTouchDispatch(
            x1: first.x,
            y1: first.y,
            action: action,
            pointerCount: ordered.count,
            x2: ordered.count > 1 ? ordered[1].x : 0,
            y2: ordered.count > 1 ? ordered[1].y : 0
        )
        if phase == .ended || phase == .cancelled {
            activePointers.removeValue(forKey: pointerID)
        }
        return dispatch
    }
}
