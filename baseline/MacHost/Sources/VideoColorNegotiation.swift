import Foundation
import VibeScreenProtocol

enum HostVideoColorDecision: Equatable {
    case accepted(VSColorDescription)
    case fallback(VSColorDescription, reason: String)
}

struct HostVideoColorNegotiator {
    static let unsupportedHDRFallbackReason = "unsupported_color_or_decode_profile"

    let clientCapabilities: Set<VSCapability>
    let decodeCapabilities: [VSVideoDecodeCapability]

    func evaluate(_ requested: VSColorDescription) -> HostVideoColorDecision {
        let color = Self.normalized(requested)
        if Self.isHDR(color), !clientCapabilities.contains(.hdrVideo) {
            return .fallback(Self.legacySDRColor, reason: Self.unsupportedHDRFallbackReason)
        }
        guard supports(color) else {
            return .fallback(Self.legacySDRColor, reason: Self.unsupportedHDRFallbackReason)
        }
        return .accepted(color)
    }

    func validatedFallback(
        _ selected: VSColorDescription,
        codec: VSCodec,
        encodedSize: VSDimensions,
        framesPerSecond: UInt32
    ) -> VSColorDescription? {
        let color = Self.normalized(selected)
        guard !Self.isHDR(color), supports(
            color,
            codec: codec,
            encodedSize: encodedSize,
            framesPerSecond: framesPerSecond
        ) else { return nil }
        return color
    }

    func supportsLegacySDR(
        codec: VSCodec,
        encodedSize: VSDimensions,
        framesPerSecond: UInt32
    ) -> Bool {
        supports(
            Self.legacySDRColor,
            codec: codec,
            encodedSize: encodedSize,
            framesPerSecond: framesPerSecond
        )
    }

    static var legacySDRColor: VSColorDescription {
        var color = VSColorDescription()
        color.primaries = .bt709
        color.transferFunction = .bt709
        color.matrixCoefficients = .bt709
        color.fullRange = false
        color.bitDepth = 8
        return color
    }

    static func normalized(_ color: VSColorDescription) -> VSColorDescription {
        var normalized = color
        if normalized.primaries == .unspecified { normalized.primaries = .bt709 }
        if normalized.transferFunction == .unspecified { normalized.transferFunction = .bt709 }
        if normalized.matrixCoefficients == .unspecified { normalized.matrixCoefficients = .bt709 }
        if normalized.bitDepth == 0 { normalized.bitDepth = 8 }
        return normalized
    }

    private func supports(
        _ color: VSColorDescription,
        codec: VSCodec? = nil,
        encodedSize: VSDimensions? = nil,
        framesPerSecond: UInt32? = nil
    ) -> Bool {
        decodeCapabilities.isEmpty || decodeCapabilities.contains(where: { capability in
            let transfer = color.transferFunction == .unspecified ? .bt709 : color.transferFunction
            let sizeMatches = encodedSize.map { size in
                size.width <= capability.maximumWidth && size.height <= capability.maximumHeight
            } ?? true
            let frameRateMatches = framesPerSecond.map { $0 <= capability.maximumFramesPerSecond } ?? true
            return (codec == nil || capability.codec == codec)
                && sizeMatches
                && frameRateMatches
                && capability.bitDepths.contains(color.bitDepth == 0 ? 8 : color.bitDepth)
                && capability.transferFunctions.contains(transfer)
        })
    }

    static func isHDR(_ color: VSColorDescription) -> Bool {
        color.bitDepth > 8
            || color.transferFunction == .pq
            || color.transferFunction == .hlg
            || color.primaries == .bt2020
            || color.matrixCoefficients == .bt2020NonConstant
    }
}
