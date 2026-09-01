import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class AudioUsbLanPcmFixtureTests: XCTestCase {
    func testFixturePinsUsbLanPcmS16LEProductFlow() throws {
        let fixture = try UsbLanPcmAudioFixture.load(file: #filePath)

        XCTAssertEqual(fixture.transportModes, ["usb", "lan"])
        XCTAssertEqual(fixture.capability, "CAPABILITY_AUDIO")
        XCTAssertEqual(fixture.protocolChannel.name, "AUDIO")
        XCTAssertEqual(fixture.protocolChannel.id, 3)
        XCTAssertEqual(fixture.cleanupExpectations.hostStopReason, MacHostAudioStopReason.reconfigure)

        let config = fixture.config.message
        let format = try MacHostAudioFormat(config: config)
        XCTAssertEqual(fixture.config.codec, "AUDIO_CODEC_PCM_S16LE")
        XCTAssertEqual(format.streamID, fixture.config.streamID)
        XCTAssertEqual(format.configEpoch, fixture.config.configEpoch)
        XCTAssertEqual(format.sampleRateHz, fixture.config.sampleRateHz)
        XCTAssertEqual(format.channelCount, fixture.config.channelCount)
        XCTAssertEqual(format.framesPerPacket, fixture.config.framesPerPacket)
        XCTAssertEqual(format.bytesPerPacket, fixture.config.bytesPerPacket)
        XCTAssertEqual(try config.serializedData(), Data(audioHex: fixture.config.serializedHex))
        XCTAssertEqual(
            try fixture.acceptedConfigResult.message.serializedData(),
            Data(audioHex: fixture.acceptedConfigResult.serializedHex)
        )

        var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: fixture.sessionEpoch)
        let packets = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data(audioHex: fixture.capture.pcmS16LEHex),
            frameCount: fixture.capture.frameCount,
            timestampMonotonicNs: fixture.capture.timestampMonotonicNs
        ))

        XCTAssertEqual(packets.count, fixture.packets.count)
        for (packet, expected) in zip(packets, fixture.packets) {
            XCTAssertEqual(packet.header.streamID, fixture.config.streamID)
            XCTAssertEqual(packet.header.sessionEpoch, fixture.sessionEpoch)
            XCTAssertEqual(packet.header.configEpoch, fixture.config.configEpoch)
            XCTAssertEqual(packet.header.sequence, expected.sequence)
            XCTAssertEqual(packet.header.frameCount, expected.frameCount)
            XCTAssertEqual(packet.header.payloadLength, UInt32(Data(audioHex: expected.payloadHex).count))
            XCTAssertEqual(packet.timestampMonotonicNs, expected.timestampMonotonicNs)
            XCTAssertEqual(try packet.header.serializedData(), Data(audioHex: expected.headerHex))
            XCTAssertEqual(packet.payload, Data(audioHex: expected.payloadHex))
            XCTAssertEqual(packet.serializedFrame, Data(audioHex: expected.serializedFrameHex))

            let decoded = try MacHostAudioPacketCodec.decode(Data(audioHex: expected.serializedFrameHex))
            XCTAssertEqual(decoded.header, packet.header)
            XCTAssertEqual(decoded.payload, packet.payload)
        }
    }
}

private struct UsbLanPcmAudioFixture: Decodable {
    struct ProtocolChannel: Decodable {
        let name: String
        let id: Int
    }

    struct Config: Decodable {
        let streamID: UInt64
        let configEpoch: UInt64
        let codec: String
        let sampleRateHz: UInt32
        let channelCount: UInt32
        let framesPerPacket: UInt32
        let bytesPerPacket: Int
        let serializedHex: String

        private enum CodingKeys: String, CodingKey {
            case streamID = "stream_id"
            case configEpoch = "config_epoch"
            case codec
            case sampleRateHz = "sample_rate_hz"
            case channelCount = "channel_count"
            case framesPerPacket = "frames_per_packet"
            case bytesPerPacket = "bytes_per_packet"
            case serializedHex = "serialized_hex"
        }

        var message: VSAudioConfig {
            var config = VSAudioConfig()
            config.streamID = streamID
            config.configEpoch = configEpoch
            config.codec = .pcmS16Le
            config.sampleRateHz = sampleRateHz
            config.channelCount = channelCount
            config.framesPerPacket = framesPerPacket
            return config
        }
    }

    struct ConfigResult: Decodable {
        let streamID: UInt64
        let configEpoch: UInt64
        let accepted: Bool
        let rejectionReason: String
        let serializedHex: String

        private enum CodingKeys: String, CodingKey {
            case streamID = "stream_id"
            case configEpoch = "config_epoch"
            case accepted
            case rejectionReason = "rejection_reason"
            case serializedHex = "serialized_hex"
        }

        var message: VSAudioConfigResult {
            var result = VSAudioConfigResult()
            result.streamID = streamID
            result.configEpoch = configEpoch
            result.accepted = accepted
            result.rejectionReason = rejectionReason
            return result
        }
    }

    struct Capture: Decodable {
        let frameCount: UInt32
        let timestampMonotonicNs: UInt64
        let pcmS16LEHex: String

        private enum CodingKeys: String, CodingKey {
            case frameCount = "frame_count"
            case timestampMonotonicNs = "timestamp_monotonic_ns"
            case pcmS16LEHex = "pcm_s16le_hex"
        }
    }

    struct Packet: Decodable {
        let sequence: UInt64
        let frameCount: UInt32
        let timestampMonotonicNs: UInt64
        let payloadHex: String
        let headerHex: String
        let serializedFrameHex: String

        private enum CodingKeys: String, CodingKey {
            case sequence
            case frameCount = "frame_count"
            case timestampMonotonicNs = "timestamp_monotonic_ns"
            case payloadHex = "payload_hex"
            case headerHex = "header_hex"
            case serializedFrameHex = "serialized_frame_hex"
        }
    }

    struct CleanupExpectations: Decodable {
        let hostStopReason: String

        private enum CodingKeys: String, CodingKey {
            case hostStopReason = "host_stop_reason"
        }
    }

    let transportModes: [String]
    let capability: String
    let protocolChannel: ProtocolChannel
    let sessionEpoch: UInt64
    let config: Config
    let acceptedConfigResult: ConfigResult
    let capture: Capture
    let packets: [Packet]
    let cleanupExpectations: CleanupExpectations

    private enum CodingKeys: String, CodingKey {
        case transportModes = "transport_modes"
        case capability
        case protocolChannel = "protocol_channel"
        case sessionEpoch = "session_epoch"
        case config
        case acceptedConfigResult = "accepted_config_result"
        case capture
        case packets
        case cleanupExpectations = "cleanup_expectations"
    }

    static func load(file: StaticString) throws -> UsbLanPcmAudioFixture {
        var root = URL(fileURLWithPath: "\(file)")
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let url = root.appendingPathComponent("contracts/fixtures/audio/v1/usb-lan-pcm-s16le-product-flow.json")
        return try JSONDecoder().decode(UsbLanPcmAudioFixture.self, from: Data(contentsOf: url))
    }
}

private extension Data {
    init(audioHex: String) {
        precondition(audioHex.count.isMultiple(of: 2))
        self.init(stride(from: 0, to: audioHex.count, by: 2).map { offset in
            let start = audioHex.index(audioHex.startIndex, offsetBy: offset)
            let end = audioHex.index(start, offsetBy: 2)
            return UInt8(audioHex[start..<end], radix: 16)!
        })
    }
}
