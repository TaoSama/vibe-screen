import CoreMedia
import Foundation
import VideoToolbox
import VibeScreenCore
import VibeScreenProtocol

public enum VideoDecoderError: Error, Equatable {
    case unsupportedCodec(VSCodec)
    case missingParameterSets
    case formatDescription(OSStatus)
    case decompressionSession(OSStatus)
    case blockBuffer(OSStatus)
    case sampleBuffer(OSStatus)
    case decode(OSStatus)
}

public final class VideoDecoder: @unchecked Sendable {
    public typealias FrameHandler = @Sendable (CVPixelBuffer, CMTime) -> Void

    private let lock = NSLock()
    private var session: VTDecompressionSession?
    private var formatDescription: CMVideoFormatDescription?
    private var codec: VSCodec = .unspecified
    private let onFrame: FrameHandler

    public init(onFrame: @escaping FrameHandler) {
        self.onFrame = onFrame
    }

    deinit {
        invalidate()
    }

    public func configure(codec: VSCodec, parameterSets: [Data]) throws {
        lock.lock()
        defer { lock.unlock() }

        guard VideoDecodeImplementationSupport.hasDecodeImplementation(for: codec) else {
            throw VideoDecoderError.unsupportedCodec(codec)
        }

        let description: CMVideoFormatDescription
        switch codec {
        case .h264:
            guard parameterSets.count >= 2 else { throw VideoDecoderError.missingParameterSets }
            description = try Self.makeH264Description(parameterSets: Array(parameterSets.prefix(2)))
        case .hevc:
            guard parameterSets.count >= 3 else { throw VideoDecoderError.missingParameterSets }
            description = try Self.makeHEVCDescription(parameterSets: Array(parameterSets.prefix(3)))
        default:
            throw VideoDecoderError.unsupportedCodec(codec)
        }

        if let session {
            VTDecompressionSessionInvalidate(session)
        }
        var callback = VTDecompressionOutputCallbackRecord(
            decompressionOutputCallback: Self.outputCallback,
            decompressionOutputRefCon: Unmanaged.passUnretained(self).toOpaque()
        )
        let attributes: [CFString: Any] = [
            kCVPixelBufferMetalCompatibilityKey: true,
            kCVPixelBufferIOSurfacePropertiesKey: [:],
        ]
        var newSession: VTDecompressionSession?
        let status = VTDecompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            formatDescription: description,
            decoderSpecification: nil,
            imageBufferAttributes: attributes as CFDictionary,
            outputCallback: &callback,
            decompressionSessionOut: &newSession
        )
        guard status == noErr, let newSession else {
            throw VideoDecoderError.decompressionSession(status)
        }
        self.codec = codec
        formatDescription = description
        session = newSession
    }

    public func decode(annexB: Data, presentationTime: CMTime) throws {
        lock.lock()
        defer { lock.unlock() }
        guard let session, let formatDescription else {
            throw VideoDecoderError.missingParameterSets
        }

        let sampleData = AnnexB.lengthPrefixedSample(from: annexB)
        var blockBuffer: CMBlockBuffer?
        var status = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: nil,
            blockLength: sampleData.count,
            blockAllocator: kCFAllocatorDefault,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: sampleData.count,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == kCMBlockBufferNoErr, let blockBuffer else {
            throw VideoDecoderError.blockBuffer(status)
        }
        status = sampleData.withUnsafeBytes { bytes in
            guard let baseAddress = bytes.baseAddress else { return kCMBlockBufferBadLengthParameterErr }
            return CMBlockBufferReplaceDataBytes(
                with: baseAddress,
                blockBuffer: blockBuffer,
                offsetIntoDestination: 0,
                dataLength: sampleData.count
            )
        }
        guard status == kCMBlockBufferNoErr else { throw VideoDecoderError.blockBuffer(status) }

        var timing = CMSampleTimingInfo(
            duration: .invalid,
            presentationTimeStamp: presentationTime,
            decodeTimeStamp: .invalid
        )
        var sampleBuffer: CMSampleBuffer?
        var sampleSize = sampleData.count
        status = CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault,
            dataBuffer: blockBuffer,
            formatDescription: formatDescription,
            sampleCount: 1,
            sampleTimingEntryCount: 1,
            sampleTimingArray: &timing,
            sampleSizeEntryCount: 1,
            sampleSizeArray: &sampleSize,
            sampleBufferOut: &sampleBuffer
        )
        guard status == noErr, let sampleBuffer else {
            throw VideoDecoderError.sampleBuffer(status)
        }
        var infoFlags = VTDecodeInfoFlags()
        status = VTDecompressionSessionDecodeFrame(
            session,
            sampleBuffer: sampleBuffer,
            flags: [._EnableAsynchronousDecompression, ._EnableTemporalProcessing],
            frameRefcon: nil,
            infoFlagsOut: &infoFlags
        )
        guard status == noErr else { throw VideoDecoderError.decode(status) }
    }

    public func invalidate() {
        lock.lock()
        defer { lock.unlock() }
        if let session {
            VTDecompressionSessionWaitForAsynchronousFrames(session)
            VTDecompressionSessionInvalidate(session)
        }
        session = nil
        formatDescription = nil
    }

    public static func parameterSets(codec: VSCodec, from accessUnit: Data) -> [Data] {
        AnnexB.nalUnits(in: accessUnit).filter { unit in
            guard let first = unit.first else { return false }
            switch codec {
            case .h264:
                return [7, 8].contains(first & 0x1f)
            case .hevc:
                return [32, 33, 34].contains((first >> 1) & 0x3f)
            default:
                return false
            }
        }
    }

    private static let outputCallback: VTDecompressionOutputCallback = {
        refcon, _, status, _, imageBuffer, presentationTime, _ in
        guard status == noErr, let refcon, let imageBuffer else { return }
        let decoder = Unmanaged<VideoDecoder>.fromOpaque(refcon).takeUnretainedValue()
        decoder.onFrame(imageBuffer, presentationTime)
    }

    private static func makeH264Description(parameterSets: [Data]) throws -> CMVideoFormatDescription {
        try makeDescription(parameterSets: parameterSets) { count, pointers, sizes, description in
            CMVideoFormatDescriptionCreateFromH264ParameterSets(
                allocator: kCFAllocatorDefault,
                parameterSetCount: count,
                parameterSetPointers: pointers,
                parameterSetSizes: sizes,
                nalUnitHeaderLength: 4,
                formatDescriptionOut: &description
            )
        }
    }

    private static func makeHEVCDescription(parameterSets: [Data]) throws -> CMVideoFormatDescription {
        try makeDescription(parameterSets: parameterSets) { count, pointers, sizes, description in
            CMVideoFormatDescriptionCreateFromHEVCParameterSets(
                allocator: kCFAllocatorDefault,
                parameterSetCount: count,
                parameterSetPointers: pointers,
                parameterSetSizes: sizes,
                nalUnitHeaderLength: 4,
                extensions: nil,
                formatDescriptionOut: &description
            )
        }
    }

    private static func makeDescription(
        parameterSets: [Data],
        create: (
            Int,
            UnsafePointer<UnsafePointer<UInt8>>,
            UnsafePointer<Int>,
            inout CMFormatDescription?
        ) -> OSStatus
    ) throws -> CMVideoFormatDescription {
        let storage = parameterSets.map { data -> UnsafeMutablePointer<UInt8> in
            let pointer = UnsafeMutablePointer<UInt8>.allocate(capacity: data.count)
            data.copyBytes(to: pointer, count: data.count)
            return pointer
        }
        defer {
            for pointer in storage { pointer.deallocate() }
        }
        let pointers = storage.map { UnsafePointer($0) }
        let sizes = parameterSets.map(\.count)
        var description: CMFormatDescription?
        let status = pointers.withUnsafeBufferPointer { pointerBuffer in
            sizes.withUnsafeBufferPointer { sizeBuffer in
                create(parameterSets.count, pointerBuffer.baseAddress!, sizeBuffer.baseAddress!, &description)
            }
        }
        guard status == noErr, let description else {
            throw VideoDecoderError.formatDescription(status)
        }
        return description
    }
}
