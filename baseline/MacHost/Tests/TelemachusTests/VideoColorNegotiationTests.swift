import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class VideoColorNegotiationTests: XCTestCase {
    func testHDRWithoutNegotiatedCapabilityFallsBackToSDR() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement],
            decodeCapabilities: sdrDecodeCapabilities()
        )

        switch negotiator.evaluate(hdrColor()) {
        case let .fallback(color, reason):
            XCTAssertEqual(reason, HostVideoColorNegotiator.unsupportedHDRFallbackReason)
            XCTAssertEqual(color, HostVideoColorNegotiator.legacySDRColor)
        case .accepted:
            XCTFail("HDR was accepted without CAPABILITY_HDR_VIDEO")
        }
    }

    func testValidatedFallbackAcceptsOnlyLocallySupportedSDR() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement],
            decodeCapabilities: sdrDecodeCapabilities()
        )

        XCTAssertEqual(
            negotiator.validatedFallback(
                HostVideoColorNegotiator.legacySDRColor,
                codec: .hevc,
                encodedSize: dimensions(),
                framesPerSecond: 60
            ),
            HostVideoColorNegotiator.legacySDRColor
        )
        XCTAssertNil(negotiator.validatedFallback(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        ))
    }

    private func sdrDecodeCapabilities() -> [VSVideoDecodeCapability] {
        var capability = VSVideoDecodeCapability()
        capability.codec = .hevc
        capability.maximumWidth = 3_840
        capability.maximumHeight = 2_160
        capability.maximumFramesPerSecond = 120
        capability.bitDepths = [8]
        capability.transferFunctions = [.bt709, .srgb]
        return [capability]
    }

    private func hdrColor() -> VSColorDescription {
        var color = VSColorDescription()
        color.primaries = .bt2020
        color.transferFunction = .pq
        color.matrixCoefficients = .bt2020NonConstant
        color.bitDepth = 10
        return color
    }

    private func dimensions() -> VSDimensions {
        var size = VSDimensions()
        size.width = 1_920
        size.height = 1_080
        return size
    }
}
