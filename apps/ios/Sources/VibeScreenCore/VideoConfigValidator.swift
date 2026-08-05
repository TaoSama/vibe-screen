import Foundation
import VibeScreenProtocol

public enum VideoConfigValidationError: Error, Equatable, LocalizedError, Sendable {
    case invalidStreamID
    case invalidConfigEpoch
    case invalidCodec
    case missingEncodedSize
    case invalidEncodedWidth(UInt32)
    case invalidEncodedHeight(UInt32)
    case invalidFramesPerSecond(UInt32)
    case invalidBitrate(UInt32)
    case invalidRotation(UInt32)
    case invalidColorDescription
    case unsupportedDecodeProfile
    case fallbackConfigEpochExhausted

    public var errorDescription: String? {
        switch self {
        case .invalidStreamID: "视频 stream_id 必须大于 0"
        case .invalidConfigEpoch: "视频 config_epoch 必须大于 0"
        case .invalidCodec: "视频 codec 无效"
        case .missingEncodedSize: "视频 encoded_size 缺失"
        case let .invalidEncodedWidth(width): "视频编码宽度无效：\(width)"
        case let .invalidEncodedHeight(height): "视频编码高度无效：\(height)"
        case let .invalidFramesPerSecond(fps): "视频帧率无效：\(fps)"
        case let .invalidBitrate(bitrate): "视频码率无效：\(bitrate) kbps"
        case let .invalidRotation(rotation): "视频旋转角度无效：\(rotation)"
        case .invalidColorDescription: "视频色彩描述包含未知枚举值"
        case .unsupportedDecodeProfile: "设备不支持请求的视频解码配置"
        case .fallbackConfigEpochExhausted: "视频 config_epoch 已耗尽，无法协商回退配置"
        }
    }
}

public struct VideoConfigValidator: Sendable {
    public static let minimumDimension: UInt32 = 16
    public static let maximumDimension: UInt32 = 8_192
    public static let minimumFramesPerSecond: UInt32 = 1
    public static let maximumFramesPerSecond: UInt32 = 240
    public static let validRotations: Set<UInt32> = [0, 90, 180, 270]

    public let decodeCapabilities: [VSVideoDecodeCapability]

    public init(decodeCapabilities: [VSVideoDecodeCapability]) {
        self.decodeCapabilities = decodeCapabilities
    }

    /// Validates transport-independent Protocol v1 invariants. Unknown protobuf
    /// fields remain forward-compatible and are intentionally ignored.
    public static func validateProtocol(_ config: VSVideoConfig) throws {
        guard config.streamID > 0 else { throw VideoConfigValidationError.invalidStreamID }
        guard config.configEpoch > 0 else { throw VideoConfigValidationError.invalidConfigEpoch }
        guard isKnownCodec(config.codec) else { throw VideoConfigValidationError.invalidCodec }
        guard config.hasEncodedSize else { throw VideoConfigValidationError.missingEncodedSize }
        guard (minimumDimension...maximumDimension).contains(config.encodedSize.width) else {
            throw VideoConfigValidationError.invalidEncodedWidth(config.encodedSize.width)
        }
        guard (minimumDimension...maximumDimension).contains(config.encodedSize.height) else {
            throw VideoConfigValidationError.invalidEncodedHeight(config.encodedSize.height)
        }
        guard (minimumFramesPerSecond...maximumFramesPerSecond).contains(config.framesPerSecond) else {
            throw VideoConfigValidationError.invalidFramesPerSecond(config.framesPerSecond)
        }
        guard config.bitrateKbps > 0 else {
            throw VideoConfigValidationError.invalidBitrate(config.bitrateKbps)
        }
        guard validRotations.contains(config.rotationDegrees) else {
            throw VideoConfigValidationError.invalidRotation(config.rotationDegrees)
        }
        if config.hasColorDescription {
            guard isKnown(config.colorDescription.primaries),
                  isKnown(config.colorDescription.transferFunction),
                  isKnown(config.colorDescription.matrixCoefficients) else {
                throw VideoConfigValidationError.invalidColorDescription
            }
        }
    }

    /// Adds the local decoder capability boundary to the protocol invariants.
    public func validate(_ config: VSVideoConfig) throws {
        try Self.validateProtocol(config)
        let color = config.hasColorDescription ? config.colorDescription : VideoColorNegotiator.legacySDRColor
        let bitDepth = color.bitDepth == 0 ? 8 : color.bitDepth
        let transfer = color.transferFunction == .unspecified ? .bt709 : color.transferFunction
        guard decodeCapabilities.contains(where: { capability in
            capability.codec == config.codec &&
                config.encodedSize.width <= capability.maximumWidth &&
                config.encodedSize.height <= capability.maximumHeight &&
                config.framesPerSecond <= capability.maximumFramesPerSecond &&
                capability.bitDepths.contains(bitDepth) &&
                capability.transferFunctions.contains(transfer)
        }) else {
            throw VideoConfigValidationError.unsupportedDecodeProfile
        }
    }

    private static func isKnownCodec(_ codec: VSCodec) -> Bool {
        switch codec {
        case .h264, .hevc, .av1: true
        case .unspecified, .UNRECOGNIZED: false
        }
    }

    private static func isKnown(_ value: VSColorPrimaries) -> Bool {
        if case .UNRECOGNIZED = value { return false }
        return true
    }

    private static func isKnown(_ value: VSTransferFunction) -> Bool {
        if case .UNRECOGNIZED = value { return false }
        return true
    }

    private static func isKnown(_ value: VSMatrixCoefficients) -> Bool {
        if case .UNRECOGNIZED = value { return false }
        return true
    }
}
