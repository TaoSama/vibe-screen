import Foundation
import VibeScreenProtocol

public enum VideoColorDecision: Sendable {
    case accepted(VSVideoConfig)
    case fallback(VSVideoConfig, reason: String)
    case rejected(reason: String)
}

public struct VideoColorNegotiator: Sendable {
    public let decodeCapabilities: [VSVideoDecodeCapability]

    public init(decodeCapabilities: [VSVideoDecodeCapability]) {
        self.decodeCapabilities = decodeCapabilities
    }

    public func evaluate(_ requested: VSVideoConfig) -> VideoColorDecision {
        do {
            try VideoConfigValidator(decodeCapabilities: decodeCapabilities).validate(requested)
            return .accepted(requested)
        } catch let error as VideoConfigValidationError {
            guard error == .unsupportedDecodeProfile else {
                return .rejected(reason: error.localizedDescription)
            }
        } catch {
            return .rejected(reason: error.localizedDescription)
        }

        var fallback = requested
        let nextEpoch = requested.configEpoch.addingReportingOverflow(1)
        guard !nextEpoch.overflow else {
            return .rejected(
                reason: VideoConfigValidationError.fallbackConfigEpochExhausted.localizedDescription
            )
        }
        let fallbackCapability = decodeCapabilities.first { capability in
            capability.bitDepths.contains(8) &&
                (capability.transferFunctions.contains(.bt709) || capability.transferFunctions.contains(.srgb))
        }
        fallback.codec = fallbackCapability?.codec ?? .h264
        fallback.configEpoch = nextEpoch.partialValue
        fallback.colorDescription = Self.legacySDRColor
        return .fallback(fallback, reason: "unsupported_color_or_decode_profile")
    }

    public static var legacySDRColor: VSColorDescription {
        var color = VSColorDescription()
        color.primaries = .bt709
        color.transferFunction = .bt709
        color.matrixCoefficients = .bt709
        color.fullRange = false
        color.bitDepth = 8
        return color
    }
}
