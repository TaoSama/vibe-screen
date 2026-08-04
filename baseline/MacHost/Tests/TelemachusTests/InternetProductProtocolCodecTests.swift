import Foundation
import VibeScreenCore
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
        let packet = try MediaPacket(serializedFrame: encoded.payload)

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

    private func makeCodec(controlLimit: Int = 64 * 1_024) throws -> InternetProductProtocolCodec {
        try InternetProductProtocolCodec(
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
                configEpoch: 9
            ),
            limits: InternetTransportLimits(
                maximumControlMessageBytes: controlLimit,
                maximumBufferedControlBytes: 2 * 1_024 * 1_024,
                maximumMediaFrameBytes: 16 * 1_024 * 1_024,
                maximumRelayBytesPerSession: 1_024 * 1_024
            )
        )
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
}
