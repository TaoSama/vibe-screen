import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class VideoConfigValidatorTests: XCTestCase {
    func testProtocolBoundariesAcceptOnlyCompleteValidConfiguration() throws {
        let valid = validVideoConfig()
        XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(valid))

        for width in [UInt32(0), 15, 8_193] {
            var config = valid
            config.encodedSize.width = width
            XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(config))
        }
        for width in [UInt32(16), 8_192] {
            var config = valid
            config.encodedSize.width = width
            XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(config))
        }
        for height in [UInt32(0), 15, 8_193] {
            var config = valid
            config.encodedSize.height = height
            XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(config))
        }
        for height in [UInt32(16), 8_192] {
            var config = valid
            config.encodedSize.height = height
            XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(config))
        }
        for fps in [UInt32(0), 241] {
            var config = valid
            config.framesPerSecond = fps
            XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(config))
        }
        for fps in [UInt32(1), 240] {
            var config = valid
            config.framesPerSecond = fps
            XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(config))
        }
        for rotation in [UInt32(0), 90, 180, 270] {
            var config = valid
            config.rotationDegrees = rotation
            XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(config))
        }
        for rotation in [UInt32(1), 45, 360] {
            var config = valid
            config.rotationDegrees = rotation
            XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(config))
        }
    }

    func testProtocolRejectsMissingIdentityRateCodecAndUnknownColorEnums() throws {
        let valid = validVideoConfig()

        var missingSize = valid
        missingSize.clearEncodedSize()
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(missingSize)) {
            XCTAssertEqual($0 as? VideoConfigValidationError, .missingEncodedSize)
        }

        var invalidStream = valid
        invalidStream.streamID = 0
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidStream))
        var invalidEpoch = valid
        invalidEpoch.configEpoch = 0
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidEpoch))
        var invalidCodec = valid
        invalidCodec.codec = .unspecified
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidCodec))
        invalidCodec.codec = .UNRECOGNIZED(99)
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidCodec))
        var invalidBitrate = valid
        invalidBitrate.bitrateKbps = 0
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidBitrate))

        var invalidPrimaries = valid
        invalidPrimaries.colorDescription.primaries = .UNRECOGNIZED(99)
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidPrimaries))
        var invalidTransfer = valid
        invalidTransfer.colorDescription.transferFunction = .UNRECOGNIZED(99)
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidTransfer))
        var invalidMatrix = valid
        invalidMatrix.colorDescription.matrixCoefficients = .UNRECOGNIZED(99)
        XCTAssertThrowsError(try VideoConfigValidator.validateProtocol(invalidMatrix))
    }

    func testUnknownProtobufFieldsRemainForwardCompatible() throws {
        var bytes = try validVideoConfig().serializedData()
        // Unknown field 99, varint wire type, value 1.
        bytes.append(contentsOf: [0x98, 0x06, 0x01])
        let decoded = try VSVideoConfig(serializedBytes: bytes)
        XCTAssertFalse(decoded.unknownFields.data.isEmpty)
        XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(decoded))
        XCTAssertNoThrow(
            try VideoConfigValidator(decodeCapabilities: [decodeCapability()]).validate(decoded)
        )
    }

    func testDecodeCapabilityLimitsAndLegacyColorDefaults() throws {
        let validator = VideoConfigValidator(decodeCapabilities: [decodeCapability()])
        let valid = validVideoConfig()
        XCTAssertNoThrow(try validator.validate(valid))

        var tooWide = valid
        tooWide.encodedSize.width = 1_921
        XCTAssertThrowsError(try validator.validate(tooWide)) {
            XCTAssertEqual($0 as? VideoConfigValidationError, .unsupportedDecodeProfile)
        }
        var tooTall = valid
        tooTall.encodedSize.height = 1_081
        XCTAssertThrowsError(try validator.validate(tooTall))
        var tooFast = valid
        tooFast.framesPerSecond = 61
        XCTAssertThrowsError(try validator.validate(tooFast))
        var wrongCodec = valid
        wrongCodec.codec = .hevc
        XCTAssertThrowsError(try validator.validate(wrongCodec))

        var unsupportedDepth = valid
        unsupportedDepth.colorDescription.bitDepth = 10
        XCTAssertThrowsError(try validator.validate(unsupportedDepth))
        var unsupportedTransfer = valid
        unsupportedTransfer.colorDescription.transferFunction = .pq
        XCTAssertThrowsError(try validator.validate(unsupportedTransfer))
    }

    func testAV1ProtocolKnownButRequiresRuntimeDecodeAdmission() throws {
        var av1 = validVideoConfig()
        av1.codec = .av1
        XCTAssertNoThrow(try VideoConfigValidator.validateProtocol(av1))
        XCTAssertThrowsError(try VideoConfigValidator(decodeCapabilities: [decodeCapability()]).validate(av1)) {
            XCTAssertEqual($0 as? VideoConfigValidationError, .unsupportedDecodeProfile)
        }

        let hardwareOnly = VideoDecodeCapabilitySnapshot(
            h264HardwareDecoderAvailable: true,
            hevcHardwareDecoderAvailable: true,
            av1HardwareDecoderAvailable: true,
            av1DecoderImplementationAvailable: false
        )
        let callerRequestedAdmission = VideoDecodeCapabilitySnapshot(
            h264HardwareDecoderAvailable: true,
            hevcHardwareDecoderAvailable: true,
            av1HardwareDecoderAvailable: true,
            av1DecoderImplementationAvailable: true
        )

        XCTAssertFalse(hardwareOnly.av1StreamAdmissionAvailable)
        XCTAssertEqual(hardwareOnly.protocolCodecs, [.hevc, .h264])
        XCTAssertFalse(callerRequestedAdmission.av1StreamAdmissionAvailable)
        XCTAssertEqual(
            callerRequestedAdmission.protocolCodecs,
            [.hevc, .h264],
            "AV1 must stay closed while the shared decode implementation gate is false"
        )
        XCTAssertEqual(
            VideoConfigValidator.sdrDecodeCapabilities(for: hardwareOnly).map(\.codec),
            [.hevc, .h264]
        )
        XCTAssertEqual(
            VideoConfigValidator.sdrDecodeCapabilities(for: callerRequestedAdmission).map(\.codec),
            [.hevc, .h264]
        )
    }

    func testDecodeImplementationSupportKeepsCurrentProtocolCodecsAtHevcAndH264() {
        XCTAssertTrue(VideoDecodeImplementationSupport.hasDecodeImplementation(for: .hevc))
        XCTAssertTrue(VideoDecodeImplementationSupport.hasDecodeImplementation(for: .h264))
        XCTAssertFalse(VideoDecodeImplementationSupport.hasDecodeImplementation(for: .av1))

        let allHardwareAndCallerFlags = VideoDecodeCapabilitySnapshot(
            h264HardwareDecoderAvailable: true,
            hevcHardwareDecoderAvailable: true,
            av1HardwareDecoderAvailable: true,
            av1DecoderImplementationAvailable: true
        )

        XCTAssertEqual(allHardwareAndCallerFlags.protocolCodecs, [.hevc, .h264])
        XCTAssertEqual(
            VideoConfigValidator.sdrDecodeCapabilities(for: allHardwareAndCallerFlags).map(\.codec),
            [.hevc, .h264]
        )
    }

    func testAV1FallsBackToFirstAvailableSdrCapability() throws {
        var av1 = validVideoConfig(epoch: 11)
        av1.codec = .av1

        switch VideoColorNegotiator(decodeCapabilities: [decodeCapability()]).evaluate(av1) {
        case let .fallback(fallback):
            XCTAssertEqual(fallback.codec, .h264)
            XCTAssertEqual(fallback.configEpoch, 12)
            XCTAssertEqual(fallback.colorDescription, VideoColorNegotiator.legacySDRColor)
        case .accepted, .rejected:
            XCTFail("AV1 without a local decode capability should request a legacy SDR fallback")
        }
    }

    func testUnsupportedProfileAtMaximumEpochRejectsWithoutOverflow() {
        var config = validVideoConfig(epoch: .max)
        config.codec = .hevc
        switch VideoColorNegotiator(decodeCapabilities: [decodeCapability()]).evaluate(config) {
        case let .rejected(reason):
            XCTAssertEqual(
                reason,
                VideoConfigValidationError.fallbackConfigEpochExhausted.localizedDescription
            )
        case .accepted, .fallback:
            XCTFail("maximum config epoch unexpectedly produced a fallback")
        }
    }

    func testProductionAdmissionRejectsInvalidConfigWithoutReplacingActiveEpoch() throws {
        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        let capabilities = [decodeCapability()]
        var gate = VideoMediaGate()
        try gate.reset(owner: owner, sessionEpoch: 9)
        try gate.bindStream(7, owner: owner)

        let epochOne = validVideoConfig(streamID: 7, epoch: 1)
        guard case let .accepted(epochOneToken, _) = try gate.evaluateAndBeginConfiguration(
            epochOne,
            decodeCapabilities: capabilities,
            owner: owner
        ) else {
            return XCTFail("valid production config was rejected")
        }
        try gate.acknowledgementSent(epochOneToken, streamID: 7, owner: owner)
        XCTAssertResultSuccess(gate.admit(header(streamID: 7, sessionEpoch: 9, configEpoch: 1, frameID: 100), owner: owner))

        var invalidEpochTwo = validVideoConfig(streamID: 7, epoch: 2)
        invalidEpochTwo.encodedSize.width = 0
        guard case .rejected = try gate.evaluateAndBeginConfiguration(
            invalidEpochTwo,
            decodeCapabilities: capabilities,
            owner: owner
        ) else {
            return XCTFail("invalid production config was accepted")
        }
        XCTAssertResultSuccess(gate.admit(header(streamID: 7, sessionEpoch: 9, configEpoch: 1, frameID: 101), owner: owner))

        var unsupportedEpochTwo = validVideoConfig(streamID: 7, epoch: 2)
        unsupportedEpochTwo.codec = .hevc
        guard case let .rejected(_, fallback) = try gate.evaluateAndBeginConfiguration(
            unsupportedEpochTwo,
            decodeCapabilities: capabilities,
            owner: owner
        ), fallback != nil else {
            return XCTFail("unsupported profile did not request an explicit fallback")
        }
        XCTAssertResultSuccess(gate.admit(header(streamID: 7, sessionEpoch: 9, configEpoch: 1, frameID: 102), owner: owner))

        let epochTwo = validVideoConfig(streamID: 7, epoch: 2)
        guard case let .accepted(epochTwoToken, _) = try gate.evaluateAndBeginConfiguration(
            epochTwo,
            decodeCapabilities: capabilities,
            owner: owner
        ) else {
            return XCTFail("valid replacement config was rejected")
        }
        try gate.acknowledgementSent(epochTwoToken, streamID: 7, owner: owner)
        XCTAssertEqual(
            gate.admit(header(streamID: 7, sessionEpoch: 9, configEpoch: 1, frameID: 103), owner: owner),
            .failure(.configEpochMismatch(expected: 2, received: 1))
        )
        XCTAssertResultSuccess(gate.admit(header(streamID: 7, sessionEpoch: 9, configEpoch: 2, frameID: 1), owner: owner))
    }
}

private func validVideoConfig(streamID: UInt64 = 1, epoch: UInt64 = 1) -> VSVideoConfig {
    var config = VSVideoConfig()
    config.streamID = streamID
    config.configEpoch = epoch
    config.codec = .h264
    config.encodedSize.width = 1_920
    config.encodedSize.height = 1_080
    config.framesPerSecond = 60
    config.bitrateKbps = 8_000
    config.rotationDegrees = 0
    return config
}

private func decodeCapability() -> VSVideoDecodeCapability {
    var capability = VSVideoDecodeCapability()
    capability.codec = .h264
    capability.maximumWidth = 1_920
    capability.maximumHeight = 1_080
    capability.maximumFramesPerSecond = 60
    capability.bitDepths = [8]
    capability.transferFunctions = [.bt709]
    return capability
}

private func header(
    streamID: UInt64,
    sessionEpoch: UInt64,
    configEpoch: UInt64,
    frameID: UInt64
) -> VSMediaPacketHeader {
    var header = VSMediaPacketHeader()
    header.streamID = streamID
    header.sessionEpoch = sessionEpoch
    header.configEpoch = configEpoch
    header.frameID = frameID
    header.codec = .h264
    header.fragmentCount = 1
    return header
}

private func XCTAssertResultSuccess(
    _ result: Result<VideoMediaGate.AcceptedFrame, VideoMediaGateError>,
    file: StaticString = #filePath,
    line: UInt = #line
) {
    guard case .success = result else {
        return XCTFail("expected media admission, got \(result)", file: file, line: line)
    }
}
