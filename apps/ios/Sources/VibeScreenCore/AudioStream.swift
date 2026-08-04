import Foundation
import VibeScreenProtocol

public struct PCMStreamFormat: Equatable, Sendable {
    public let sampleRate: UInt32
    public let channelCount: UInt32
    public let framesPerPacket: UInt32

    public init(config: VSAudioConfig) throws {
        guard config.codec == .pcmS16Le else { throw AudioStreamError.unsupportedCodec(config.codec) }
        guard (8_000...192_000).contains(config.sampleRateHz) else {
            throw AudioStreamError.invalidSampleRate(config.sampleRateHz)
        }
        guard (1...8).contains(config.channelCount), config.framesPerPacket > 0 else {
            throw AudioStreamError.invalidChannelCount(config.channelCount)
        }
        sampleRate = config.sampleRateHz
        channelCount = config.channelCount
        framesPerPacket = config.framesPerPacket
    }

    public var bytesPerPacket: Int {
        Int(framesPerPacket) * Int(channelCount) * MemoryLayout<Int16>.size
    }
}

public struct AudioPacket: Sendable {
    public let header: VSAudioPacketHeader
    public let payload: Data

    public init(serializedFrame: Data) throws {
        var cursor = 0
        let headerLength = try DelimitedPayload.readVarint(from: serializedFrame, cursor: &cursor)
        guard headerLength <= 64 * 1_024, headerLength <= serializedFrame.count - cursor else {
            throw AudioStreamError.invalidHeader
        }
        header = try VSAudioPacketHeader(
            serializedBytes: serializedFrame.dropFirst(cursor).prefix(headerLength)
        )
        payload = Data(serializedFrame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw AudioStreamError.payloadLengthMismatch
        }
    }
}

public enum AudioEnqueueResult: Equatable, Sendable {
    case queued
    case duplicate
    case stale
    case advancedPastGap(droppedPackets: UInt64)
    case queueFullDropped(sequence: UInt64)
}

public struct AudioJitterBuffer: Sendable {
    public let maximumPackets: Int
    private(set) var expectedSequence: UInt64
    private(set) var packets: [UInt64: AudioPacket] = [:]

    public init(firstSequence: UInt64, maximumPackets: Int = 8) {
        expectedSequence = firstSequence
        self.maximumPackets = max(2, maximumPackets)
    }

    public mutating func enqueue(
        _ packet: AudioPacket,
        sessionEpoch: UInt64,
        configEpoch: UInt64,
        format: PCMStreamFormat
    ) throws -> AudioEnqueueResult {
        guard packet.header.sessionEpoch == sessionEpoch else { throw AudioStreamError.staleSessionEpoch }
        guard packet.header.configEpoch == configEpoch else { throw AudioStreamError.staleConfigEpoch }
        guard packet.payload.count == format.bytesPerPacket,
              packet.header.frameCount == format.framesPerPacket else {
            throw AudioStreamError.invalidPCMByteCount
        }
        let sequence = packet.header.sequence
        guard sequence >= expectedSequence else { return .stale }
        guard packets[sequence] == nil else { return .duplicate }
        packets[sequence] = packet
        if packets.count > maximumPackets, let earliest = packets.keys.min() {
            if earliest > expectedSequence {
                let dropped = earliest - expectedSequence
                expectedSequence = earliest
                while packets.count > maximumPackets, let newest = packets.keys.max() {
                    packets.removeValue(forKey: newest)
                }
                return .advancedPastGap(droppedPackets: dropped)
            }
            if let newest = packets.keys.max() {
                packets.removeValue(forKey: newest)
                return .queueFullDropped(sequence: newest)
            }
        }
        return .queued
    }

    public mutating func drainReady() -> [AudioPacket] {
        var ready: [AudioPacket] = []
        while let packet = packets.removeValue(forKey: expectedSequence) {
            ready.append(packet)
            expectedSequence += 1
        }
        return ready
    }

    public mutating func reset(firstSequence: UInt64) {
        packets.removeAll(keepingCapacity: true)
        expectedSequence = firstSequence
    }

    public var queuedPacketCount: Int { packets.count }
}

public enum AudioStreamError: Error, Equatable {
    case unsupportedCodec(VSAudioCodec)
    case invalidSampleRate(UInt32)
    case invalidChannelCount(UInt32)
    case invalidHeader
    case payloadLengthMismatch
    case staleSessionEpoch
    case staleConfigEpoch
    case invalidPCMByteCount
}

enum DelimitedPayload {
    static func readVarint(from data: Data, cursor: inout Int) throws -> Int {
        var value = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let index = data.index(data.startIndex, offsetBy: cursor)
            let byte = data[index]
            cursor += 1
            value |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { return value }
            shift += 7
        }
        throw AudioStreamError.invalidHeader
    }

    static func encodeVarint(_ value: Int) -> Data {
        var remaining = value
        var data = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining > 0 { byte |= 0x80 }
            data.append(byte)
        } while remaining > 0
        return data
    }
}
