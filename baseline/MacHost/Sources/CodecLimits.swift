import CoreMedia
import VideoToolbox
import VibeScreenProtocol

/// Video codec used for the encode session and wire stream.
enum StreamCodec {
    case hevc
    case h264

    /// Wire id used in the codecSelected (type 10) message.
    var wireId: UInt8 {
        switch self {
        case .hevc: return 0
        case .h264: return 1
        }
    }
}

struct VideoCodecCapabilitySnapshot: Equatable {
    let h264HardwareEncoderAvailable: Bool
    let hevcHardwareEncoderAvailable: Bool
    let av1HardwareEncoderAvailable: Bool

    static let stableDefault = VideoCodecCapabilitySnapshot(
        h264HardwareEncoderAvailable: true,
        hevcHardwareEncoderAvailable: true,
        av1HardwareEncoderAvailable: false
    )

    static func probe(width: Int = 640, height: Int = 480) -> VideoCodecCapabilitySnapshot {
        VideoCodecCapabilitySnapshot(
            h264HardwareEncoderAvailable: Self.canCreateHardwareEncoder(
                codecType: kCMVideoCodecType_H264,
                width: width,
                height: height
            ),
            hevcHardwareEncoderAvailable: Self.canCreateHardwareEncoder(
                codecType: kCMVideoCodecType_HEVC,
                width: width,
                height: height
            ),
            av1HardwareEncoderAvailable: Self.canCreateHardwareEncoder(
                codecType: kCMVideoCodecType_AV1,
                width: width,
                height: height
            )
        )
    }

    var protocolV1SupportedCodecs: [VSCodec] {
        var codecs: [VSCodec] = []
        if hevcHardwareEncoderAvailable { codecs.append(.hevc) }
        if h264HardwareEncoderAvailable { codecs.append(.h264) }
        // AV1 remains intentionally unadvertised until the Host has a real
        // AV1 encoder implementation and matching frame packaging. A hardware
        // capability probe alone is not enough to admit a Protocol v1 stream.
        return codecs
    }

    var legacyStreamCodecs: [StreamCodec] {
        var codecs: [StreamCodec] = []
        if hevcHardwareEncoderAvailable { codecs.append(.hevc) }
        if h264HardwareEncoderAvailable { codecs.append(.h264) }
        return codecs
    }

    private static func canCreateHardwareEncoder(
        codecType: CMVideoCodecType,
        width: Int,
        height: Int
    ) -> Bool {
        var session: VTCompressionSession?
        let specification = [
            kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder: true
        ] as CFDictionary
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: Int32(width),
            height: Int32(height),
            codecType: codecType,
            encoderSpecification: specification,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: nil,
            refcon: nil,
            compressionSessionOut: &session
        )
        if let session {
            VTCompressionSessionInvalidate(session)
        }
        return status == noErr && session != nil
    }
}

enum VideoCodecAdmissionPolicy {
    static func streamCodec(for codec: VSCodec) -> StreamCodec? {
        switch codec {
        case .hevc: return .hevc
        case .h264: return .h264
        case .av1, .unspecified, .UNRECOGNIZED: return nil
        }
    }

    static func protocolCodecs(
        from configuredCodecs: [VSCodec],
        capabilities: VideoCodecCapabilitySnapshot = .stableDefault
    ) -> [VSCodec] {
        let available = Set(capabilities.protocolV1SupportedCodecs)
        return configuredCodecs.filter { available.contains($0) && streamCodec(for: $0) != nil }
    }
}

enum CodecLimits {
    /// Conservative floor every AVC hardware decoder meets (H.264 level 4.x).
    /// AVC-only devices are low-end; their real cap is at or above this.
    static let avcMaxWidth = 1920
    static let avcMaxHeight = 1088

    /// Scale (width, height) down to fit within the AVC limit, preserving
    /// aspect ratio, flooring each dimension to a multiple of 16 (codec
    /// macroblock alignment). Sizes already within the limit pass through
    /// unchanged so HEVC-era resolutions keep working verbatim.
    static func clampForAvc(width: Int, height: Int) -> (width: Int, height: Int) {
        guard width > avcMaxWidth || height > avcMaxHeight else {
            return (width, height)
        }
        let scale = min(Double(avcMaxWidth) / Double(width),
                        Double(avcMaxHeight) / Double(height))
        let w = max(16, Int((Double(width) * scale).rounded()) & ~15)
        let h = max(16, Int((Double(height) * scale).rounded()) & ~15)
        return (w, h)
    }
}
