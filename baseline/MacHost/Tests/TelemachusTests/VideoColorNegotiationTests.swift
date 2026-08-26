import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class VideoColorNegotiationTests: XCTestCase {
    func testHDRWithNegotiatedCapabilityAndDecodeProfileIsAccepted() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement, .hdrVideo],
            decodeCapabilities: hdrDecodeCapabilities()
        )

        switch negotiator.evaluate(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        ) {
        case let .accepted(color):
            XCTAssertEqual(color, hdrColor())
        case .fallback, .rejected:
            XCTFail("HDR should be accepted only when capability and decode profile both match")
        }
    }

    func testHDRWithoutNegotiatedCapabilityFallsBackToSDR() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement],
            decodeCapabilities: sdrDecodeCapabilities()
        )

        switch negotiator.evaluate(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        ) {
        case let .fallback(color, reason):
            XCTAssertEqual(reason, HostVideoColorNegotiator.unsupportedHDRFallbackReason)
            assertLegacySDR(color)
        case .accepted:
            XCTFail("HDR was accepted without CAPABILITY_HDR_VIDEO")
        case .rejected:
            XCTFail("HDR color mismatch should fall back when the SDR profile is supported")
        }
    }

    func testHDRWithoutDecodeProfileFallsBackToSDR() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement, .hdrVideo],
            decodeCapabilities: []
        )

        switch negotiator.evaluate(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        ) {
        case let .fallback(color, reason):
            XCTAssertEqual(reason, HostVideoColorNegotiator.unsupportedHDRFallbackReason)
            assertLegacySDR(color)
        case .accepted:
            XCTFail("HDR must require an explicit decode profile")
        case .rejected:
            XCTFail("Missing HDR decode profile should fall back when legacy SDR is supported")
        }
    }

    func testUnsupportedDecodeProfileRejectsWithoutSDRFallback() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement],
            decodeCapabilities: sdrDecodeCapabilities()
        )

        switch negotiator.evaluate(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 144
        ) {
        case let .rejected(reason):
            XCTAssertEqual(reason, HostVideoColorNegotiator.unsupportedHDRFallbackReason)
        case .accepted, .fallback:
            XCTFail("Unsupported decode profile must not advertise a selected SDR fallback")
        }
    }

    func testValidatedFallbackAcceptsOnlyLocallySupportedSDR() {
        let negotiator = HostVideoColorNegotiator(
            clientCapabilities: [.colorManagement],
            decodeCapabilities: sdrDecodeCapabilities()
        )

        let validFallback = negotiator.validatedFallback(
            legacySDRColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        )
        XCTAssertNotNil(validFallback)
        if let validFallback { assertLegacySDR(validFallback) }
        XCTAssertNil(negotiator.validatedFallback(
            hdrColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 60
        ))
        XCTAssertNil(negotiator.validatedFallback(
            legacySDRColor(),
            codec: .hevc,
            encodedSize: dimensions(),
            framesPerSecond: 144
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

    private func hdrDecodeCapabilities() -> [VSVideoDecodeCapability] {
        var capability = sdrDecodeCapabilities()[0]
        capability.bitDepths = [8, 10]
        capability.transferFunctions = [.bt709, .srgb, .pq]
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

    private func legacySDRColor() -> VSColorDescription {
        HostVideoColorNegotiator.legacySDRColor
    }

    private func assertLegacySDR(
        _ color: VSColorDescription,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(color.primaries, .bt709, file: file, line: line)
        XCTAssertEqual(color.transferFunction, .bt709, file: file, line: line)
        XCTAssertEqual(color.matrixCoefficients, .bt709, file: file, line: line)
        XCTAssertFalse(color.fullRange, file: file, line: line)
        XCTAssertEqual(color.bitDepth, 8, file: file, line: line)
    }

    private func dimensions() -> VSDimensions {
        var size = VSDimensions()
        size.width = 1_920
        size.height = 1_080
        return size
    }
}
