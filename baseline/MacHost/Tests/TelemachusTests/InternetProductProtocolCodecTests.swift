import Foundation
import VibeScreenProtocol
import XCTest
@testable import Telemachus

final class InternetProductProtocolCodecTests: XCTestCase {
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
        XCTAssertTrue(hostEnvelope.hostHello.capabilities.contains(.stylus))
        XCTAssertEqual(
            acceptedEnvelope.sessionAccepted.negotiatedResourceLimits.maximumEncryptedMediaRecordBytes,
            UInt32(negotiatedMaximum)
        )
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.mediaRecordFragmentation))
        XCTAssertTrue(acceptedEnvelope.sessionAccepted.negotiatedCapabilities.contains(.stylus))

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

    func testControllerAdvertisingRequiresRuntimeAvailabilityAndPeerOffer() throws {
        var unavailable = try makeCodec(negotiate: false, controllerAvailable: false)
        var offer = clientHello(supportsController: true)
        try unavailable.validate(offer)
        XCTAssertFalse(try VSEnvelope(serializedBytes: unavailable.hostHello())
            .hostHello.capabilities.contains(.controller))

        var available = try makeCodec(negotiate: false, controllerAvailable: true)
        try available.validate(offer)
        XCTAssertTrue(try VSEnvelope(serializedBytes: available.hostHello())
            .hostHello.capabilities.contains(.controller))
        let accepted = try VSEnvelope(serializedBytes: available.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsController: true
        )).sessionAccepted
        XCTAssertTrue(accepted.negotiatedCapabilities.contains(.controller))

        offer.capabilities.removeAll { $0 == .controller }
        var noOffer = try makeCodec(negotiate: false, controllerAvailable: true)
        try noOffer.validate(offer)
        let notNegotiated = try VSEnvelope(serializedBytes: noOffer.sessionAccepted(
            heartbeatIntervalMilliseconds: 1_000,
            peerSupportsTouch: true,
            peerSupportsController: false
        )).sessionAccepted
        XCTAssertFalse(notNegotiated.negotiatedCapabilities.contains(.controller))
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
        XCTAssertEqual(video.rotationDegrees, 270)
        XCTAssertEqual(video.configEpoch, 10)
        XCTAssertEqual(codec.video.rotationDegrees, 270)
    }

    private func makeCodec(
        controlLimit: Int = 64 * 1_024,
        rotationDegrees: Int = 0,
        negotiate: Bool = true,
        inputEnabled: Bool = true,
        controllerAvailable: Bool = false
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
        supportsController: Bool = false
    ) -> VSClientHello {
        var range = VSProtocolRange()
        range.minimum = 1
        range.maximum = 1
        var limits = VSResourceLimits()
        limits.maximumEncryptedMediaRecordBytes = UInt32(maximumEncryptedMediaRecordBytes)
        var hello = VSClientHello()
        hello.supportedProtocols = range
        hello.deviceID = "device-1"
        hello.deviceName = "Android"
        hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities) + [.touch]
        if supportsController { hello.capabilities.append(.controller) }
        hello.requiredCapabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
        hello.codecs = [.hevc]
        hello.transports = [.internet]
        hello.resourceLimits = limits
        return hello
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
