import Foundation
import CoreMedia
import VibeScreenProtocol
import XCTest
@testable import Telemachus

final class InternetProductProtocolCodecTests: XCTestCase {
    func testCaptureReconfigurationSkipsRateOnlyAdaptiveChange() {
        XCTAssertEqual(CaptureReconfigurationPolicy.action(
            currentWidth: 1920,
            currentHeight: 1080,
            currentFrameRate: 30,
            targetWidth: 1920,
            targetHeight: 1080,
            targetFrameRate: 60
        ), .updateFrameRate)
    }

    func testCaptureReconfigurationSkipsUnchangedAdaptiveConfiguration() {
        XCTAssertEqual(CaptureReconfigurationPolicy.action(
            currentWidth: 1920,
            currentHeight: 1080,
            currentFrameRate: 60,
            targetWidth: 1920,
            targetHeight: 1080,
            targetFrameRate: 60
        ), .none)
    }

    func testCaptureReconfigurationRebuildsForDimensionChange() {
        XCTAssertEqual(CaptureReconfigurationPolicy.action(
            currentWidth: 1920,
            currentHeight: 1080,
            currentFrameRate: 60,
            targetWidth: 1280,
            targetHeight: 720,
            targetFrameRate: 30
        ), .rebuild)
    }

    func testCaptureStreamConfigurationUsesTargetAdaptiveFrameRate() {
        let configuration = CaptureStreamConfigurationFactory.make(
            width: 1920,
            height: 1080,
            frameRate: 30,
            preservesAspectRatio: true
        )

        XCTAssertEqual(configuration.width, 1920)
        XCTAssertEqual(configuration.height, 1080)
        XCTAssertEqual(configuration.minimumFrameInterval, CMTime(value: 1, timescale: 30))
    }

    func testMediaFrameCarriesAuthenticatedProtocolHeaderBeforeAnnexBPayload() throws {
        var codec = try makeCodec()
        let annexB = Data([0, 0, 0, 1, 0x26, 0x01])

        let encoded = try codec.mediaFrame(
            payload: annexB,
            timestamp: 42,
            isKeyframe: true
        )
        let packet = try ProtocolV1MediaPacketCodec.decode(try XCTUnwrap(encoded.records.first))

        XCTAssertEqual(packet.payload, annexB)
        XCTAssertEqual(packet.header.streamID, 7)
        XCTAssertEqual(packet.header.sessionEpoch, 3)
        XCTAssertEqual(packet.header.configEpoch, 9)
        XCTAssertEqual(packet.header.frameID, 1)
        XCTAssertEqual(packet.header.fragmentIndex, 0)
        XCTAssertEqual(packet.header.fragmentCount, 1)
        XCTAssertEqual(packet.header.captureTimestampNs, 42)
        XCTAssertTrue(packet.header.keyframe)
        XCTAssertEqual(packet.header.codec, .hevc)
    }

    func testInternetProductVideoConfigurationRejectsAV1UntilEncoderExists() {
        let configuration = InternetProductVideoConfiguration(
            codec: .av1,
            width: 1920,
            height: 1080,
            framesPerSecond: 60,
            bitrateKbps: 20_000,
            streamID: 7,
            configEpoch: 9
        )

        XCTAssertThrowsError(try configuration.validate()) { error in
            XCTAssertEqual(error as? InternetProductProtocolError, .unsupportedCodec)
        }
    }

    func testHandshakeNegotiatesFragmentationCapabilityAndEncryptedRecordLimit() throws {
        var codec = try makeCodec(negotiate: false)
        let negotiatedMaximum = InternetMediaRecordContract.minimumNegotiatedEncryptedRecordBytes
        let hello = clientHello(maximumEncryptedMediaRecordBytes: negotiatedMaximum)

        try codec.validate(hello)
        let hostEnvelope = try VSEnvelope(serializedBytes: codec.hostHello())
        let acceptedEnvelope = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsStylus: true
        ))

        XCTAssertEqual(codec.negotiatedMaximumEncryptedMediaRecordBytes, negotiatedMaximum)
        XCTAssertEqual(hostEnvelope.hostHello.resourceLimits.maximumEncryptedMediaRecordBytes, UInt32(
            InternetMediaRecordContract.maximumEncryptedRecordBytes
        ))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.mediaRecordFragmentation))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.audioDataChannel))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.bulkDataChannel))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.stylus))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.managedConfiguration))
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.fileTransfer))
        XCTAssertFalse(hostEnvelope.hostHello.capabilities.contains(.audio))
        XCTAssertFalse(hostEnvelope.hostHello.capabilities.contains(.clipboard))
        XCTAssertEqual(
            acceptedEnvelope.sessionAccepted.negotiatedResourceLimits.maximumEncryptedMediaRecordBytes,
            UInt32(negotiatedMaximum)
        )
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.mediaRecordFragmentation))
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.audioDataChannel))
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.bulkDataChannel))
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.stylus))
        XCTAssertFalse(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.audio))
        XCTAssertFalse(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.clipboard))
        XCTAssertFalse(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.fileTransfer))
        XCTAssertFalse(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.managedConfiguration))

        let encoded = try codec.mediaFrame(
            payload: Data(repeating: 0x41, count: 256 * 1_024),
            timestamp: 7,
            isKeyframe: true
        )
        XCTAssertGreaterThan(encoded.records.count, 1)
        XCTAssertTrue(encoded.records.allSatisfy {
            $0.count + InternetMediaRecordContract.applicationAEADRecordOverheadBytes <= negotiatedMaximum
        })
    }

    func testHandshakeAdvertisesAndNegotiatesInternetFileTransferResourceLimits() throws {
        let policy = ProtocolV1FileTransferPolicy(
            maximumFileBytes: 512,
            maximumChunkBytes: 64
        )
        var codec = try makeCodec(
            negotiate: false,
            fileTransferPolicy: policy
        )
        var hello = clientHello(
            supportsFileTransfer: true,
            supportsManagedConfiguration: true
        )
        hello.resourceLimits.maximumFileBytes = 128
        hello.resourceLimits.maximumFileChunkBytes = 16

        try codec.validate(hello)
        let host = try VSEnvelope(serializedBytes: codec.hostHello()).hostHello
        let accepted = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsFileTransfer: true,
            peerSupportsManagedConfiguration: true
        )).sessionAccepted

        XCTAssertTrue(host.capabilities.contains(.fileTransfer))
        XCTAssertTrue(host.capabilities.contains(.managedConfiguration))
        XCTAssertEqual(host.resourceLimits.maximumFileBytes, 512)
        XCTAssertEqual(host.resourceLimits.maximumFileChunkBytes, 64)
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.fileTransfer))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.managedConfiguration))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileBytes, 128)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileChunkBytes, 16)
    }

    func testFileTransferCapabilityIsOptionalForLegacyInternetPeers() throws {
        var codec = try makeCodec(negotiate: false)

        try codec.validate(clientHello(supportsFileTransfer: false))
        let accepted = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsFileTransfer: false,
            peerSupportsManagedConfiguration: false
        )).sessionAccepted

        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.fileTransfer))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.managedConfiguration))
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileBytes, 0)
        XCTAssertEqual(accepted.negotiatedResourceLimits.maximumFileChunkBytes, 0)
    }

    func testDisabledInputIsNeitherAdvertisedNorNegotiated() throws {
        var codec = try makeCodec(negotiate: false, inputEnabled: false)
        try codec.validate(clientHello())

        let host = try VSEnvelope(serializedBytes: codec.hostHello()).hostHello
        let accepted = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsStylus: true
        )).sessionAccepted

        XCTAssertFalse(host.capabilities.contains(.touch))
        XCTAssertFalse(host.capabilities.contains(.stylus))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.touch))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.stylus))
    }

    func testLegacyTouchOnlyPeerDoesNotNegotiateStylus() throws {
        var codec = try makeCodec(negotiate: false, inputEnabled: true)
        try codec.validate(clientHello())

        let accepted = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsStylus: false
        )).sessionAccepted

        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.touch))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.stylus))
    }

    func testControllerCapabilityIsIndependentOfTouchInputToggle() throws {
        var codec = try makeCodec(
            negotiate: false,
            inputEnabled: false,
            controllerAvailable: true
        )
        try codec.validate(clientHello(supportsController: true))

        let host = try VSEnvelope(serializedBytes: codec.hostHello()).hostHello
        let accepted = try VSEnvelope(serializedBytes: codec.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: false,
            peerSupportsController: true
        )).sessionAccepted

        XCTAssertFalse(host.capabilities.contains(.touch))
        XCTAssertTrue(host.capabilities.contains(.controller))
        XCTAssertFalse(accepted.negotiatedCapabilities.contains(.touch))
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.controller))
    }

    func testRequiredControllerCapabilityIsRejectedWhenHostCannotCreateControllers() throws {
        var codec = try makeCodec(negotiate: false, controllerAvailable: false)
        var hello = clientHello(supportsController: true)
        hello.requiredCapabilities.append(.controller)

        XCTAssertThrowsError(try codec.validate(hello)) { error in
            XCTAssertEqual(
                error as? InternetProductProtocolError,
                .missingCapability(.controller)
            )
        }
    }

    func testControllerFifthSoftRejectConsumesInputIDAndPreservesSlots() throws {
        var codec = try makeCodec(controllerAvailable: true)

        for index in 0..<4 {
            let admission = try codec.authorizeController(controllerEvent(
                inputID: UInt64(index + 1),
                controllerID: "pad-\(index + 1)",
                kind: .connected
            ))
            guard case .accepted = admission else {
                return XCTFail("Controller \(index + 1) should be admitted")
            }
        }

        let fifth = try codec.authorizeController(controllerEvent(
            inputID: 5,
            controllerID: "pad-5",
            kind: .connected
        ))
        guard case .rejected(let inputID, let reason) = fifth else {
            return XCTFail("The fifth controller should be soft-rejected")
        }
        XCTAssertEqual(inputID, 5)
        XCTAssertEqual(reason, "maximum_active_controllers_exceeded")
        XCTAssertEqual(codec.controllerStateMachine.attachments.count, 4)

        XCTAssertThrowsError(try codec.authorizeController(controllerEvent(
            inputID: 5,
            controllerID: "pad-1",
            kind: .state,
            buttonMask: 1
        ))) { error in
            XCTAssertEqual(error as? InternetProductProtocolError, .invalidController)
        }

        guard case .accepted = try codec.authorizeController(controllerEvent(
            inputID: 6,
            controllerID: "pad-1",
            kind: .state,
            buttonMask: 1
        )) else {
            return XCTFail("An admitted controller should remain active")
        }
        guard case .accepted = try codec.authorizeController(controllerEvent(
            inputID: 7,
            controllerID: "pad-2",
            kind: .disconnected
        )) else {
            return XCTFail("Disconnect should release a controller slot")
        }
        guard case .accepted(let replacement) = try codec.authorizeController(controllerEvent(
            inputID: 8,
            controllerID: "pad-5",
            controllerEpoch: 2,
            kind: .connected
        )) else {
            return XCTFail("A higher-epoch controller should enter the released slot")
        }
        XCTAssertEqual(replacement.controllerID, "pad-5")
        XCTAssertEqual(codec.controllerStateMachine.attachments.count, 4)
    }

    func testControllerAuthorizationPreservesCodecValueSemantics() throws {
        let original = try makeCodec(controllerAvailable: true)
        var copy = original

        guard case .accepted = try copy.authorizeController(controllerEvent(
            inputID: 1,
            controllerID: "pad-1",
            kind: .connected
        )) else {
            return XCTFail("Copied codec should accept the controller")
        }

        XCTAssertTrue(original.controllerStateMachine.attachments.isEmpty)
        XCTAssertEqual(copy.controllerStateMachine.attachments["pad-1"], 1)
    }

    func testHandshakeRejectsLegacyOrInvalidMediaRecordOffer() throws {
        for maximum in [0, InternetMediaRecordContract.minimumNegotiatedEncryptedRecordBytes - 1] {
            var codec = try makeCodec(negotiate: false)
            var hello = clientHello(maximumEncryptedMediaRecordBytes: maximum)
            if maximum == 0 {
                hello.capabilities.removeAll { $0 == .mediaRecordFragmentation }
            }
            XCTAssertThrowsError(try codec.validate(hello))
            XCTAssertThrowsError(try codec.sessionAccepted(
                heartbeatIntervalMilliseconds: 1_000,
                peerSupportsTouch: true
            ))
        }
    }

    func testMediaFrameFragmentsFourAndSixteenMiBBoundariesWithinAndroidRecordLimit() throws {
        XCTAssertEqual(
            InternetMediaRecordContract.maximumEncryptedRecordBytes,
            InternetMediaRecordContract.maximumPlaintextRecordBytes
                + InternetMediaRecordContract.applicationAEADRecordOverheadBytes
        )
        for payloadBytes in [4 * 1_024 * 1_024, 16 * 1_024 * 1_024] {
            var codec = try makeCodec()
            let payload = Data(repeating: 0x41, count: payloadBytes)

            let encoded = try codec.mediaFrame(
                payload: payload,
                timestamp: 99,
                isKeyframe: true
            )

            XCTAssertEqual(encoded.mediaPayloadBytes, payloadBytes)
            XCTAssertGreaterThan(encoded.records.count, 1)
            XCTAssertLessThanOrEqual(
                encoded.records.count,
                InternetMediaRecordContract.maximumFragmentsPerFrame
            )
            var reassembled = Data()
            for (index, record) in encoded.records.enumerated() {
                XCTAssertLessThanOrEqual(
                    record.count,
                    InternetMediaRecordContract.maximumPlaintextRecordBytes
                )
                XCTAssertLessThanOrEqual(
                    record.count + InternetMediaRecordContract.applicationAEADRecordOverheadBytes,
                    InternetMediaRecordContract.maximumEncryptedRecordBytes
                )
                let packet = try ProtocolV1MediaPacketCodec.decode(record)
                XCTAssertEqual(packet.header.frameID, 1)
                XCTAssertEqual(packet.header.fragmentIndex, UInt32(index))
                XCTAssertEqual(packet.header.fragmentCount, UInt32(encoded.records.count))
                reassembled.append(packet.payload)
            }
            XCTAssertEqual(reassembled, payload)
        }
    }

    func testMediaFrameRejectsPayloadAboveSixteenMiB() throws {
        var codec = try makeCodec()
        let payloadBytes = 16 * 1_024 * 1_024 + 1

        XCTAssertThrowsError(try codec.mediaFrame(
            payload: Data(repeating: 0x41, count: payloadBytes),
            timestamp: 1,
            isKeyframe: true
        )) { error in
            XCTAssertEqual(
                error as? InternetProductProtocolError,
                .mediaPayloadTooLarge(actual: payloadBytes, maximum: 16 * 1_024 * 1_024)
            )
        }
    }

    func testEncodedFrameRejectsMalformedOversizedAndInconsistentBatches() throws {
        let first = try mediaRecord(
            payload: Data([1]),
            frameID: 1,
            fragmentIndex: 0,
            fragmentCount: 2
        )
        let second = try mediaRecord(
            payload: Data([2]),
            frameID: 1,
            fragmentIndex: 1,
            fragmentCount: 2
        )
        XCTAssertNoThrow(try EncodedInternetFrame(
            records: [first, second],
            mediaPayloadBytes: 2,
            captureTimestamp: 42,
            isKeyframe: true
        ))
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: [],
            mediaPayloadBytes: 0,
            captureTimestamp: 42,
            isKeyframe: true
        ))
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: [first, second],
            mediaPayloadBytes: 3,
            captureTimestamp: 42,
            isKeyframe: true
        ))
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: Array(repeating: first, count: InternetMediaRecordContract.maximumFragmentsPerFrame + 1),
            mediaPayloadBytes: 1,
            captureTimestamp: 42,
            isKeyframe: true
        ))
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: [Data(
                repeating: 0x41,
                count: InternetMediaRecordContract.maximumPlaintextRecordBytes + 1
            )],
            mediaPayloadBytes: 1,
            captureTimestamp: 42,
            isKeyframe: true
        ))
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: [first],
            mediaPayloadBytes: InternetMediaRecordContract.maximumFrameBytes + 1,
            captureTimestamp: 42,
            isKeyframe: true
        ))

        let wrongScope = try mediaRecord(
            payload: Data([2]),
            frameID: 2,
            fragmentIndex: 1,
            fragmentCount: 2
        )
        XCTAssertThrowsError(try EncodedInternetFrame(
            records: [first, wrongScope],
            mediaPayloadBytes: 2,
            captureTimestamp: 42,
            isKeyframe: true
        ))
    }

    func testControlDecoderRejectsOversizeBeforeParsing() throws {
        var codec = try makeCodec(controlLimit: 8)

        XCTAssertThrowsError(try codec.decodeControl(Data(repeating: 1, count: 9))) { error in
            XCTAssertEqual(
                error as? InternetProductProtocolError,
                .controlPayloadTooLarge(actual: 9, maximum: 8)
            )
        }
    }

    func testControlDecoderRejectsStaleEpochAndNonMonotonicMessageID() throws {
        var codec = try makeCodec()
        let stale = try envelope(messageID: 1, epoch: 2).serializedData()
        XCTAssertThrowsError(try codec.decodeControl(stale)) { error in
            XCTAssertEqual(
                error as? InternetProductProtocolError,
                .staleSessionEpoch(received: 2, expected: 3)
            )
        }

        let accepted = try envelope(messageID: 2, epoch: 3).serializedData()
        _ = try codec.decodeControl(accepted)
        XCTAssertThrowsError(try codec.decodeControl(accepted)) { error in
            XCTAssertEqual(error as? InternetProductProtocolError, .invalidMessageID)
        }
    }

    func testInitialAndRuntimeRotationUseVersionedVideoAndDisplayChangedControls() throws {
        var codec = try makeCodec(rotationDegrees: 90)
        let initial = try VSEnvelope(serializedBytes: codec.videoConfiguration())
        guard case .videoConfig(let initialVideo) = initial.payload else {
            return XCTFail("Expected initial video configuration")
        }
        XCTAssertEqual(initialVideo.configEpoch, 9)
        XCTAssertEqual(initialVideo.colorDescription, HostVideoColorNegotiator.legacySDRColor)
        XCTAssertEqual(initialVideo.rotationDegrees, 90)

        let updates = try codec.updateRotation(270)
        XCTAssertEqual(updates.count, 2)
        let displayEnvelope = try VSEnvelope(serializedBytes: updates[0])
        let videoEnvelope = try VSEnvelope(serializedBytes: updates[1])
        guard case .displayChanged(let display) = displayEnvelope.payload,
              case .videoConfig(let video) = videoEnvelope.payload else {
            return XCTFail("Expected DisplayChanged followed by VideoConfig")
        }
        XCTAssertEqual(display.rotationDegrees, 270)
        XCTAssertEqual(video.colorDescription, HostVideoColorNegotiator.legacySDRColor)
        XCTAssertEqual(video.rotationDegrees, 270)
        XCTAssertEqual(video.configEpoch, 10)
        XCTAssertEqual(codec.video.rotationDegrees, 270)
    }

    func testAdaptivePlanNeverUpsamplesAndEnforcesEvenMinimumDimensions() {
        let baseline = InternetProductVideoConfiguration(
            codec: .hevc, width: 1920, height: 1080,
            framesPerSecond: 60, bitrateKbps: 20_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        )

        // resolutionScale above 1 must not grow the frame beyond the baseline.
        let upscale = InternetAdaptiveVideoPlan(
            baseline: baseline,
            profile: AdaptiveMediaProfile(
                targetBitrateBps: 20_000_000, resolutionScale: 1.5, framesPerSecond: 60
            )
        )
        XCTAssertEqual(upscale?.width, 1920)
        XCTAssertEqual(upscale?.height, 1080)

        // Odd baselines scale down to even dimensions (low bit cleared).
        let oddBaseline = InternetProductVideoConfiguration(
            codec: .hevc, width: 1921, height: 1081,
            framesPerSecond: 60, bitrateKbps: 20_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        )
        let halfScale = InternetAdaptiveVideoPlan(
            baseline: oddBaseline,
            profile: AdaptiveMediaProfile(
                targetBitrateBps: 20_000_000, resolutionScale: 0.5, framesPerSecond: 30
            )
        )
        XCTAssertEqual(halfScale?.width, 960)
        XCTAssertEqual(halfScale?.height, 540)
        XCTAssertEqual(halfScale?.width.isMultiple(of: 2), true)
        XCTAssertEqual(halfScale?.height.isMultiple(of: 2), true)

        // Dimensions floor out at 2 so the encoder always receives a valid frame.
        let tinyBaseline = InternetProductVideoConfiguration(
            codec: .hevc, width: 3, height: 3,
            framesPerSecond: 60, bitrateKbps: 20_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        )
        let tiny = InternetAdaptiveVideoPlan(
            baseline: tinyBaseline,
            profile: AdaptiveMediaProfile(
                targetBitrateBps: 20_000_000, resolutionScale: 0.1, framesPerSecond: 30
            )
        )
        XCTAssertEqual(tiny?.width, 2)
        XCTAssertEqual(tiny?.height, 2)
    }

    func testAdaptivePlanCapsFpsAndBitrateAtUserBaseline() {
        let baseline = InternetProductVideoConfiguration(
            codec: .hevc, width: 1920, height: 1080,
            framesPerSecond: 30, bitrateKbps: 5_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        )
        let greedy = AdaptiveMediaProfile(
            targetBitrateBps: 20_000_000, resolutionScale: 1, framesPerSecond: 120
        )

        let plan = InternetAdaptiveVideoPlan(baseline: baseline, profile: greedy)

        XCTAssertEqual(plan?.framesPerSecond, 30)
        XCTAssertEqual(plan?.bitrateMbps, 5)
    }

    func testAdaptivePlanQuantizesBitrateToWholeMbpsRoundingHalfUp() {
        let baseline = InternetProductVideoConfiguration(
            codec: .hevc, width: 1920, height: 1080,
            framesPerSecond: 60, bitrateKbps: 100_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        )

        func mbps(_ bps: UInt64) -> Int? {
            InternetAdaptiveVideoPlan(
                baseline: baseline,
                profile: AdaptiveMediaProfile(
                    targetBitrateBps: bps, resolutionScale: 1, framesPerSecond: 30
                )
            )?.bitrateMbps
        }

        XCTAssertEqual(mbps(2_000_000), 2)
        XCTAssertEqual(mbps(2_499_999), 2)
        XCTAssertEqual(mbps(2_500_000), 3)
        XCTAssertEqual(mbps(2_999_999), 3)
    }

    func testConfigEpochExhaustionRejectsVideoConfigurationUpdate() throws {
        let exhausted = InternetProductVideoConfiguration(
            codec: .hevc, width: 1920, height: 1080,
            framesPerSecond: 60, bitrateKbps: 20_000,
            streamID: 7, configEpoch: UInt64.max, rotationDegrees: 0
        )
        var codec = try InternetProductProtocolCodec(
            sessionIdentifier: "product-session",
            sessionEpoch: 3,
            hostID: "host-1",
            hostName: "Mac",
            peerDeviceID: "device-1",
            video: exhausted,
            inputEnabled: true,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: 64 * 1_024,
                maximumBufferedControlBytes: 2 * 1_024 * 1_024,
                maximumMediaFrameBytes: 16 * 1_024 * 1_024,
                maximumRelayBytesPerSession: 1_024 * 1_024
            )
        )
        try codec.validate(clientHello())

        XCTAssertThrowsError(try codec.updateVideoConfiguration(bitrateKbps: 30_000)) { error in
            XCTAssertEqual(
                error as? InternetProductProtocolError,
                .rejectedVideoConfiguration("Video configuration epoch is exhausted.")
            )
        }
    }

    func testRestoreDoesNotReusePreviouslyIssuedConfigEpoch() throws {
        var codec = try makeCodec() // configEpoch 9, nextConfigEpoch 10

        let first = try codec.updateVideoConfiguration(bitrateKbps: 30_000)
        let firstEnvelope = try VSEnvelope(serializedBytes: first[0])
        guard case .videoConfig(let firstVideo) = firstEnvelope.payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(firstVideo.configEpoch, 10)

        // Roll back to the original configuration. The issued epoch 10 must not
        // be handed out again even though the restored video carries epoch 9.
        codec.restoreVideoConfiguration(InternetProductVideoConfiguration(
            codec: .hevc, width: 1920, height: 1080,
            framesPerSecond: 60, bitrateKbps: 20_000,
            streamID: 7, configEpoch: 9, rotationDegrees: 0
        ))
        XCTAssertEqual(codec.video.configEpoch, 9)

        let second = try codec.updateVideoConfiguration(bitrateKbps: 40_000)
        let secondEnvelope = try VSEnvelope(serializedBytes: second[0])
        guard case .videoConfig(let secondVideo) = secondEnvelope.payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(secondVideo.configEpoch, 11)
    }

    func testInvalidUpdateDoesNotConsumeConfigEpoch() throws {
        var codec = try makeCodec() // configEpoch 9, nextConfigEpoch 10

        XCTAssertThrowsError(try codec.updateVideoConfiguration(rotationDegrees: 45))
        XCTAssertEqual(codec.video.configEpoch, 9)
        XCTAssertEqual(codec.video.rotationDegrees, 0)

        let controls = try codec.updateVideoConfiguration(rotationDegrees: 90)
        let envelope = try VSEnvelope(serializedBytes: try XCTUnwrap(controls.last))
        guard case .videoConfig(let video) = envelope.payload else {
            return XCTFail("Expected VideoConfig")
        }
        XCTAssertEqual(video.configEpoch, 10)
        XCTAssertEqual(video.rotationDegrees, 90)
    }

    func testBitrateOrFpsChangeEmitsOnlyVideoConfig() throws {
        var codec = try makeCodec()

        let bitrate = try codec.updateVideoConfiguration(bitrateKbps: 30_000)
        XCTAssertEqual(bitrate.count, 1)
        let bitrateEnvelope = try VSEnvelope(serializedBytes: bitrate[0])
        guard case .videoConfig = bitrateEnvelope.payload else {
            return XCTFail("Expected only VideoConfig for bitrate change")
        }

        let fps = try codec.updateVideoConfiguration(framesPerSecond: 30)
        XCTAssertEqual(fps.count, 1)
        let fpsEnvelope = try VSEnvelope(serializedBytes: fps[0])
        guard case .videoConfig = fpsEnvelope.payload else {
            return XCTFail("Expected only VideoConfig for fps change")
        }
    }

    func testGeometryOrRotationChangeEmitsDisplayChangedThenVideoConfig() throws {
        var codec = try makeCodec()

        let resize = try codec.updateVideoConfiguration(width: 1280, height: 720)
        XCTAssertEqual(resize.count, 2)
        let resizeDisplay = try VSEnvelope(serializedBytes: resize[0])
        let resizeVideo = try VSEnvelope(serializedBytes: resize[1])
        guard case .displayChanged = resizeDisplay.payload,
              case .videoConfig = resizeVideo.payload else {
            return XCTFail("Expected DisplayChanged then VideoConfig for resize")
        }

        let rotate = try codec.updateVideoConfiguration(rotationDegrees: 90)
        XCTAssertEqual(rotate.count, 2)
        let rotateDisplay = try VSEnvelope(serializedBytes: rotate[0])
        let rotateVideo = try VSEnvelope(serializedBytes: rotate[1])
        guard case .displayChanged = rotateDisplay.payload,
              case .videoConfig = rotateVideo.payload else {
            return XCTFail("Expected DisplayChanged then VideoConfig for rotation")
        }
    }

    func testAdaptiveRequestSequenceExhaustsAfterUInt64Max() {
        var sequence = InternetAdaptiveRequestSequence(nextRequestID: UInt64.max)

        XCTAssertEqual(sequence.take(), UInt64.max)
        XCTAssertNil(sequence.take())
    }

    private func makeCodec(
        controlLimit: Int = 64 * 1_024,
        rotationDegrees: Int = 0,
        negotiate: Bool = true,
        inputEnabled: Bool = true,
        controllerAvailable: Bool = false,
        fileTransferPolicy: ProtocolV1FileTransferPolicy = .default
    ) throws -> InternetProductProtocolCodec {
        var codec = try InternetProductProtocolCodec(
            sessionIdentifier: "product-session",
            sessionEpoch: 3,
            hostID: "host-1",
            hostName: "Mac",
            peerDeviceID: "device-1",
            video: InternetProductVideoConfiguration(
                codec: .hevc,
                width: 1920,
                height: 1080,
                framesPerSecond: 60,
                bitrateKbps: 20_000,
                streamID: 7,
                configEpoch: 9,
                rotationDegrees: rotationDegrees
            ),
            inputEnabled: inputEnabled,
            controllerAvailable: controllerAvailable,
            fileTransferPolicy: fileTransferPolicy,
            limits: InternetTransportLimits(
                maximumControlMessageBytes: controlLimit,
                maximumBufferedControlBytes: 2 * 1_024 * 1_024,
                maximumMediaFrameBytes: 16 * 1_024 * 1_024,
                maximumRelayBytesPerSession: 1_024 * 1_024
            )
        )
        if negotiate {
            try codec.validate(clientHello())
        }
        return codec
    }

    private func clientHello(
        maximumEncryptedMediaRecordBytes: Int = InternetMediaRecordContract.maximumEncryptedRecordBytes,
        supportsController: Bool = false,
        supportsFileTransfer: Bool = false,
        supportsManagedConfiguration: Bool = false
    ) -> VSClientHello {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(maximumEncryptedMediaRecordBytes)
        if supportsFileTransfer {
            limits.maximumFileBytes = ProtocolV1FileTransferPolicy.defaultMaximumFileBytes
            limits.maximumFileChunkBytes = UInt32(clamping: ProtocolV1FileTransferPolicy.default.maximumChunkBytes)
        }
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device-1"
        hello.deviceName = "Android"
        hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities) + [.touch]
        if supportsController { hello.capabilities.append(.controller) }
        if supportsFileTransfer { hello.capabilities.append(.fileTransfer) }
        if supportsManagedConfiguration { hello.capabilities.append(.managedConfiguration) }
        hello.requiredCapabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        hello.resourceLimits = limits
        return hello
    }

    private func controllerEvent(
        inputID: UInt64,
        controllerID: String,
        controllerEpoch: UInt64 = 1,
        kind: VSControllerEventKind,
        buttonMask: UInt32 = 0
    ) -> VSControllerEvent {
        var event = VSControllerEvent()
        event.inputID = inputID
        event.controllerID = controllerID
        event.controllerEpoch = controllerEpoch
        event.kind = kind
        event.buttonMask = buttonMask
        return event
    }

    private func envelope(messageID: UInt64, epoch: UInt64) -> VSEnvelope {
        var envelope = VSEnvelope()
        envelope.protocolVersion = 1
        envelope.messageID = messageID
        envelope.sessionID = Data("product-session".utf8)
        envelope.sessionEpoch = epoch
        var ping = VSPing()
        ping.sequence = messageID
        envelope.ping = ping
        return envelope
    }

    private func mediaRecord(
        payload: Data,
        frameID: UInt64,
        fragmentIndex: UInt32,
        fragmentCount: UInt32
    ) throws -> Data {
        var header = VSMediaPacketHeader()
        header.streamID = 7
        header.sessionEpoch = 3
        header.configEpoch = 9
        header.frameID = frameID
        header.fragmentIndex = fragmentIndex
        header.fragmentCount = fragmentCount
        header.captureTimestampNs = 42
        header.keyframe = true
        header.codec = .hevc
        return try ProtocolV1MediaPacketCodec.encode(header: header, payload: payload)
    }
}
