import CoreMedia
import AudioToolbox
import Foundation
import VibeScreenProtocol

protocol EncodedAudioSink: AnyObject {
    var currentSessionEpoch: UInt64 { get }
    func sendAudioPCM(_ data: Data, frameCount: UInt32, sessionEpoch: UInt64)
}

struct PCMAudioFormat: Equatable {
    static let production = PCMAudioFormat(
        sampleRateHz: 48_000,
        channelCount: 2,
        framesPerPacket: 480
    )

    let sampleRateHz: UInt32
    let channelCount: UInt32
    let framesPerPacket: UInt32

    var bytesPerPacket: Int {
        Int(framesPerPacket) * Int(channelCount) * MemoryLayout<Int16>.size
    }
}

struct PCMAudioPacketizer {
    let format: PCMAudioFormat
    private var pending = Data()

    init(format: PCMAudioFormat = .production) {
        self.format = format
        pending.reserveCapacity(format.bytesPerPacket * 2)
    }

    mutating func append(interleavedS16LE bytes: Data) -> [Data] {
        guard !bytes.isEmpty else { return [] }
        pending.append(bytes)
        var packets: [Data] = []
        while pending.count >= format.bytesPerPacket {
            packets.append(Data(pending.prefix(format.bytesPerPacket)))
            pending.removeFirst(format.bytesPerPacket)
        }
        return packets
    }

    mutating func reset() { pending.removeAll(keepingCapacity: true) }
}

final class SystemAudioPCMConverter {
    private let queue = DispatchQueue(label: "com.vibescreen.audio-pcm-converter")
    private var packetizer = PCMAudioPacketizer()

    func convert(_ sampleBuffer: CMSampleBuffer) -> [Data] {
        queue.sync { convertLocked(sampleBuffer) }
    }

    func reset() {
        queue.sync { packetizer.reset() }
    }

    private func convertLocked(_ sampleBuffer: CMSampleBuffer) -> [Data] {
        guard let description = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPointer = CMAudioFormatDescriptionGetStreamBasicDescription(description) else {
            return []
        }
        let asbd = asbdPointer.pointee
        guard UInt32(asbd.mSampleRate.rounded()) == PCMAudioFormat.production.sampleRateHz,
              asbd.mChannelsPerFrame == PCMAudioFormat.production.channelCount else { return [] }

        var requiredBytes = 0
        var blockBuffer: CMBlockBuffer?
        var status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: &requiredBytes,
            bufferListOut: nil,
            bufferListSize: 0,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr, requiredBytes > 0 else { return [] }
        let storage = UnsafeMutableRawPointer.allocate(
            byteCount: requiredBytes,
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { storage.deallocate() }
        let list = storage.assumingMemoryBound(to: AudioBufferList.self)
        status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: list,
            bufferListSize: requiredBytes,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr else { return [] }

        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        let buffers = UnsafeMutableAudioBufferListPointer(list)
        let isFloat = asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0
        let isSignedInteger = asbd.mFormatFlags & kAudioFormatFlagIsSignedInteger != 0
        let isNonInterleaved = asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
        var output = Data(capacity: frames * Int(asbd.mChannelsPerFrame) * 2)

        func append(_ sample: Float) {
            let clamped = max(-1, min(1, sample))
            var value = Int16((clamped * Float(Int16.max)).rounded()).littleEndian
            withUnsafeBytes(of: &value) { output.append(contentsOf: $0) }
        }

        for frame in 0..<frames {
            for channel in 0..<Int(asbd.mChannelsPerFrame) {
                let bufferIndex = isNonInterleaved ? channel : 0
                guard bufferIndex < buffers.count, let base = buffers[bufferIndex].mData else { return [] }
                let sampleIndex = isNonInterleaved ? frame : frame * Int(asbd.mChannelsPerFrame) + channel
                if isFloat, asbd.mBitsPerChannel == 32 {
                    append(base.assumingMemoryBound(to: Float.self)[sampleIndex])
                } else if isSignedInteger, asbd.mBitsPerChannel == 16 {
                    var value = base.assumingMemoryBound(to: Int16.self)[sampleIndex].littleEndian
                    withUnsafeBytes(of: &value) { output.append(contentsOf: $0) }
                } else {
                    return []
                }
            }
        }
        return packetizer.append(interleavedS16LE: output)
    }

}

enum ProtocolV1AudioPacketError: Error, Equatable {
    case invalidHeaderLength
    case headerTooLarge(Int)
    case truncatedHeader
    case payloadLengthMismatch
    case invalidPCMByteCount
}

enum ProtocolV1AudioPacketCodec {
    private static let maximumHeaderBytes = 64 * 1_024

    static func encode(header: VSAudioPacketHeader, payload: Data) throws -> Data {
        guard payload.count == PCMAudioFormat.production.bytesPerPacket,
              header.frameCount == PCMAudioFormat.production.framesPerPacket else {
            throw ProtocolV1AudioPacketError.invalidPCMByteCount
        }
        var header = header
        header.payloadLength = UInt32(payload.count)
        let headerBytes = try header.serializedData()
        guard headerBytes.count <= maximumHeaderBytes else {
            throw ProtocolV1AudioPacketError.headerTooLarge(headerBytes.count)
        }
        return encodeVarint(headerBytes.count) + headerBytes + payload
    }

    static func decode(_ frame: Data) throws -> (header: VSAudioPacketHeader, payload: Data) {
        var cursor = 0
        let headerLength = try decodeVarint(frame, cursor: &cursor)
        guard headerLength <= maximumHeaderBytes else {
            throw ProtocolV1AudioPacketError.headerTooLarge(headerLength)
        }
        guard headerLength <= frame.count - cursor else {
            throw ProtocolV1AudioPacketError.truncatedHeader
        }
        let header = try VSAudioPacketHeader(
            serializedBytes: frame.dropFirst(cursor).prefix(headerLength)
        )
        let payload = Data(frame.dropFirst(cursor + headerLength))
        guard payload.count == Int(header.payloadLength) else {
            throw ProtocolV1AudioPacketError.payloadLengthMismatch
        }
        guard payload.count == PCMAudioFormat.production.bytesPerPacket,
              header.frameCount == PCMAudioFormat.production.framesPerPacket else {
            throw ProtocolV1AudioPacketError.invalidPCMByteCount
        }
        return (header, payload)
    }

    private static func encodeVarint(_ value: Int) -> Data {
        var remaining = value
        var result = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining > 0 { byte |= 0x80 }
            result.append(byte)
        } while remaining > 0
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
        throw ProtocolV1AudioPacketError.invalidHeaderLength
    }
}
