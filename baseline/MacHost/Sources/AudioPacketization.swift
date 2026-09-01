import Foundation
import VibeScreenProtocol

enum MacHostAudioStopReason {
    static let reconfigure = "audio_reconfigure"
}

struct MacHostAudioFormat: Equatable, Sendable {
    static let minimumSampleRateHz: UInt32 = 8_000
    static let maximumSampleRateHz: UInt32 = 192_000
    static let maximumChannelCount: UInt32 = 8

    let streamID: UInt64
    let configEpoch: UInt64
    let sampleRateHz: UInt32
    let channelCount: UInt32
    let framesPerPacket: UInt32

    init(config: VSAudioConfig) throws {
        guard config.streamID != 0 else { throw MacHostAudioError.invalidStreamID }
        guard config.configEpoch != 0 else { throw MacHostAudioError.invalidConfigEpoch }
        guard config.codec == .pcmS16Le else { throw MacHostAudioError.unsupportedCodec(config.codec) }
        guard (Self.minimumSampleRateHz...Self.maximumSampleRateHz).contains(config.sampleRateHz) else {
            throw MacHostAudioError.invalidSampleRate(config.sampleRateHz)
        }
        guard (1...Self.maximumChannelCount).contains(config.channelCount) else {
            throw MacHostAudioError.invalidChannelCount(config.channelCount)
        }
        guard config.framesPerPacket > 0 else {
            throw MacHostAudioError.invalidFramesPerPacket(config.framesPerPacket)
        }

        let bytesPerFrame = Int(config.channelCount) * MemoryLayout<Int16>.size
        let bytesPerPacket = Int(config.framesPerPacket) * bytesPerFrame
        guard bytesPerPacket <= ProtocolV1Framer.maximumPayloadBytes else {
            throw MacHostAudioError.payloadTooLarge(bytesPerPacket)
        }

        streamID = config.streamID
        configEpoch = config.configEpoch
        sampleRateHz = config.sampleRateHz
        channelCount = config.channelCount
        framesPerPacket = config.framesPerPacket
    }

    var bytesPerFrame: Int {
        Int(channelCount) * MemoryLayout<Int16>.size
    }

    var bytesPerPacket: Int {
        Int(framesPerPacket) * bytesPerFrame
    }

    var audioConfig: VSAudioConfig {
        var config = VSAudioConfig()
        config.streamID = streamID
        config.configEpoch = configEpoch
        config.codec = .pcmS16Le
        config.sampleRateHz = sampleRateHz
        config.channelCount = channelCount
        config.framesPerPacket = framesPerPacket
        return config
    }
}

enum MacHostAudioError: Error, Equatable, LocalizedError {
    case invalidStreamID
    case invalidSessionEpoch
    case invalidConfigEpoch
    case unsupportedCodec(VSAudioCodec)
    case invalidSampleRate(UInt32)
    case invalidChannelCount(UInt32)
    case invalidFramesPerPacket(UInt32)
    case payloadTooLarge(Int)
    case invalidPCMByteCount(expected: Int, actual: Int)
    case invalidFrameCount(UInt32)
    case invalidHeaderLength
    case truncatedHeader(declared: Int, available: Int)
    case headerTooLarge(Int)
    case payloadLengthMismatch(declared: Int, actual: Int)
    case alreadyRunning
    case notRunning
    case captureStartFailed(String)
    case sequenceOverflow

    var errorDescription: String? {
        switch self {
        case .invalidStreamID:
            return "Audio stream ID must be nonzero."
        case .invalidSessionEpoch:
            return "Audio session epoch must be nonzero."
        case .invalidConfigEpoch:
            return "Audio config epoch must be nonzero."
        case .unsupportedCodec(let codec):
            return "Unsupported audio codec: \(codec)."
        case .invalidSampleRate(let sampleRate):
            return "Invalid audio sample rate: \(sampleRate)."
        case .invalidChannelCount(let channelCount):
            return "Invalid audio channel count: \(channelCount)."
        case .invalidFramesPerPacket(let framesPerPacket):
            return "Invalid audio frames per packet: \(framesPerPacket)."
        case .payloadTooLarge(let byteCount):
            return "Audio packet payload is too large: \(byteCount) bytes."
        case .invalidPCMByteCount(let expected, let actual):
            return "Invalid PCM byte count: expected \(expected), got \(actual)."
        case .invalidFrameCount(let frameCount):
            return "Invalid captured audio frame count: \(frameCount)."
        case .invalidHeaderLength:
            return "Audio packet header length is invalid."
        case .truncatedHeader(let declared, let available):
            return "Audio packet header is truncated: declared \(declared), available \(available)."
        case .headerTooLarge(let byteCount):
            return "Audio packet header is too large: \(byteCount) bytes."
        case .payloadLengthMismatch(let declared, let actual):
            return "Audio packet payload length mismatch: declared \(declared), got \(actual)."
        case .alreadyRunning:
            return "Audio capture is already running."
        case .notRunning:
            return "Audio capture is not running."
        case .captureStartFailed(let reason):
            return "Audio capture failed to start: \(reason)."
        case .sequenceOverflow:
            return "Audio packet sequence overflowed."
        }
    }
}

enum MacHostAudioConfigValidator {
    static func validate(_ config: VSAudioConfig) throws -> MacHostAudioFormat {
        try MacHostAudioFormat(config: config)
    }

    static func result(for config: VSAudioConfig) -> VSAudioConfigResult {
        var result = VSAudioConfigResult()
        // Echo IDs even on rejection so peers can correlate the response to the
        // requested audio stream/config. `accepted` remains the authoritative state.
        result.streamID = config.streamID
        result.configEpoch = config.configEpoch
        do {
            _ = try validate(config)
            result.accepted = true
        } catch {
            result.accepted = false
            result.rejectionReason = error.localizedDescription
        }
        return result
    }
}

struct MacHostAudioCaptureBuffer: Equatable, Sendable {
    let pcmS16LE: Data
    let frameCount: UInt32
    let timestampMonotonicNs: UInt64

    init(pcmS16LE: Data, frameCount: UInt32, timestampMonotonicNs: UInt64) {
        self.pcmS16LE = pcmS16LE
        self.frameCount = frameCount
        self.timestampMonotonicNs = timestampMonotonicNs
    }
}

struct MacHostAudioPacket: Equatable, Sendable {
    let header: VSAudioPacketHeader
    let payload: Data
    let timestampMonotonicNs: UInt64
    let serializedFrame: Data
}

enum MacHostAudioPacketCodec {
    private static let maximumHeaderBytes = 64 * 1_024

    static func encode(header: VSAudioPacketHeader, payload: Data) throws -> Data {
        guard payload.count == Int(header.payloadLength) else {
            throw MacHostAudioError.payloadLengthMismatch(
                declared: Int(header.payloadLength),
                actual: payload.count
            )
        }
        let headerBytes = try header.serializedData()
        guard headerBytes.count <= maximumHeaderBytes else {
            throw MacHostAudioError.headerTooLarge(headerBytes.count)
        }
        var result = encodeVarint(headerBytes.count)
        result.append(headerBytes)
        result.append(payload)
        return result
    }

    static func decode(_ frame: Data) throws -> (header: VSAudioPacketHeader, payload: Data) {
        var cursor = 0
        let headerLength = try decodeVarint(frame, cursor: &cursor)
        guard headerLength <= maximumHeaderBytes else {
            throw MacHostAudioError.headerTooLarge(headerLength)
        }
        guard headerLength <= frame.count - cursor else {
            throw MacHostAudioError.truncatedHeader(
                declared: headerLength,
                available: frame.count - cursor
            )
        }
        let header = try VSAudioPacketHeader(
            serializedBytes: frame.dropFirst(cursor).prefix(headerLength)
        )
        let payload = Data(frame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw MacHostAudioError.payloadLengthMismatch(
                declared: Int(header.payloadLength),
                actual: payload.count
            )
        }
        return (header, payload)
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

    private static func decodeVarint(_ data: Data, cursor: inout Int) throws -> Int {
        var value = 0
        var shift = 0
        while cursor < data.count, shift <= 28 {
            let byte = data[data.index(data.startIndex, offsetBy: cursor)]
            cursor += 1
            value |= Int(byte & 0x7f) << shift
            if byte & 0x80 == 0 { return value }
            shift += 7
        }
        throw MacHostAudioError.invalidHeaderLength
    }
}

struct MacHostAudioPacketizer: Sendable {
    let format: MacHostAudioFormat
    let sessionEpoch: UInt64
    private var nextSequence: UInt64
    private var partialPCM = Data()
    private var partialTimestampNs: UInt64?

    init(format: MacHostAudioFormat, sessionEpoch: UInt64, firstSequence: UInt64 = 0) {
        self.format = format
        self.sessionEpoch = sessionEpoch
        nextSequence = firstSequence
    }

    mutating func append(_ capture: MacHostAudioCaptureBuffer) throws -> [MacHostAudioPacket] {
        guard capture.frameCount > 0 else {
            throw MacHostAudioError.invalidFrameCount(capture.frameCount)
        }
        let expectedBytes = Int(capture.frameCount) * format.bytesPerFrame
        guard capture.pcmS16LE.count == expectedBytes else {
            throw MacHostAudioError.invalidPCMByteCount(
                expected: expectedBytes,
                actual: capture.pcmS16LE.count
            )
        }

        if partialPCM.isEmpty { partialTimestampNs = capture.timestampMonotonicNs }
        partialPCM.append(capture.pcmS16LE)

        var packets: [MacHostAudioPacket] = []
        while partialPCM.count >= format.bytesPerPacket {
            guard nextSequence < UInt64.max else { throw MacHostAudioError.sequenceOverflow }
            let payload = Data(partialPCM.prefix(format.bytesPerPacket))
            partialPCM.removeFirst(format.bytesPerPacket)
            var header = VSAudioPacketHeader()
            header.streamID = format.streamID
            header.sessionEpoch = sessionEpoch
            header.configEpoch = format.configEpoch
            header.sequence = nextSequence
            header.frameCount = format.framesPerPacket
            header.payloadLength = UInt32(payload.count)
            let timestamp = partialTimestampNs ?? capture.timestampMonotonicNs
            let serializedFrame = try MacHostAudioPacketCodec.encode(header: header, payload: payload)
            packets.append(MacHostAudioPacket(
                header: header,
                payload: payload,
                timestampMonotonicNs: timestamp,
                serializedFrame: serializedFrame
            ))
            nextSequence += 1
            partialTimestampNs = partialPCM.isEmpty ? nil : capture.timestampMonotonicNs
        }
        return packets
    }

    mutating func reset(firstSequence: UInt64 = 0) {
        nextSequence = firstSequence
        partialPCM.removeAll(keepingCapacity: true)
        partialTimestampNs = nil
    }
}

struct MacHostAudioBacklogResult: Equatable, Sendable {
    let accepted: Bool
    let droppedPacketCount: Int
}

struct MacHostAudioPacketBacklog: Sendable {
    let maximumPackets: Int
    private var packets: [MacHostAudioPacket] = []

    init(maximumPackets: Int = 8) {
        self.maximumPackets = max(1, maximumPackets)
    }

    mutating func enqueue(_ packet: MacHostAudioPacket) -> MacHostAudioBacklogResult {
        var dropped = 0
        packets.append(packet)
        while packets.count > maximumPackets {
            packets.removeFirst()
            dropped += 1
        }
        return MacHostAudioBacklogResult(accepted: dropped == 0, droppedPacketCount: dropped)
    }

    mutating func drain() -> [MacHostAudioPacket] {
        let drained = packets
        packets.removeAll(keepingCapacity: true)
        return drained
    }

    mutating func reset() {
        packets.removeAll(keepingCapacity: true)
    }

    var queuedPacketCount: Int { packets.count }
}
