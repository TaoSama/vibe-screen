import Foundation
import VibeScreenProtocol

public enum VideoColorDecision: Sendable {
    case accepted(VSVideoConfig)
    case fallback(VSVideoConfig, reason: String)
}

public struct VideoColorNegotiator: Sendable {
    public let decodeCapabilities: [VSVideoDecodeCapability]

    public init(decodeCapabilities: [VSVideoDecodeCapability]) {
        self.decodeCapabilities = decodeCapabilities
    }

    public func evaluate(_ requested: VSVideoConfig) -> VideoColorDecision {
        let color = requested.hasColorDescription ? requested.colorDescription : Self.legacySDRColor
        let bitDepth = color.bitDepth == 0 ? 8 : color.bitDepth
        let transfer = color.transferFunction == .unspecified ? .bt709 : color.transferFunction
        let matchingCodec = decodeCapabilities.first { capability in
            capability.codec == requested.codec &&
                capability.maximumWidth >= requested.encodedSize.width &&
                capability.maximumHeight >= requested.encodedSize.height &&
                capability.maximumFramesPerSecond >= requested.framesPerSecond &&
                capability.bitDepths.contains(bitDepth) &&
                capability.transferFunctions.contains(transfer)
        }
        if matchingCodec != nil { return .accepted(requested) }

        var fallback = requested
        let fallbackCapability = decodeCapabilities.first { capability in
            capability.bitDepths.contains(8) &&
                (capability.transferFunctions.contains(.bt709) || capability.transferFunctions.contains(.srgb))
        }
        fallback.codec = fallbackCapability?.codec ?? .h264
        fallback.configEpoch = requested.configEpoch + 1
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
