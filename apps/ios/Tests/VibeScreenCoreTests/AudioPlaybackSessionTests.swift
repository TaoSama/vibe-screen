import XCTest
@testable import VibeScreenCore
import VibeScreenProtocol

final class AudioPlaybackSessionTests: XCTestCase {
    func testAcceptedConfigQueuesAudioUntilFailClosedClearsState() throws {
        let config = audioConfig(configEpoch: 2)
        let format = try PCMStreamFormat(config: config)
        let first = try packet(sequence: 0, sessionEpoch: 9, configEpoch: 2, format: format)
        let second = try packet(sequence: 1, sessionEpoch: 9, configEpoch: 2, format: format)
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        XCTAssertFalse(session.isConfigured)
        try session.accept(config: config, format: format)
        XCTAssertTrue(session.isConfigured)
        XCTAssertEqual(try session.enqueue(second, sessionEpoch: 9).map(\.header.sequence), [])
        XCTAssertEqual(session.queuedPacketCount, 1)

        XCTAssertEqual(try session.enqueue(first, sessionEpoch: 9).map(\.header.sequence), [0, 1])
        session.failClosed()

        XCTAssertFalse(session.isConfigured)
        XCTAssertEqual(session.queuedPacketCount, 0)
        XCTAssertEqual(try session.enqueue(first, sessionEpoch: 9).map(\.header.sequence), [])
    }

    func testNewConfigResetsOldEpochAndPacketWindow() throws {
        let oldConfig = audioConfig(configEpoch: 2)
        let oldFormat = try PCMStreamFormat(config: oldConfig)
        let oldPacket = try packet(sequence: 2, sessionEpoch: 9, configEpoch: 2, format: oldFormat)
        let newConfig = audioConfig(configEpoch: 3)
        let newFormat = try PCMStreamFormat(config: newConfig)
        let newPacket = try packet(sequence: 0, sessionEpoch: 9, configEpoch: 3, format: newFormat)
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        try session.accept(config: oldConfig, format: oldFormat)
        XCTAssertEqual(try session.enqueue(oldPacket, sessionEpoch: 9).map(\.header.sequence), [])
        XCTAssertEqual(session.queuedPacketCount, 1)

        try session.accept(config: newConfig, format: newFormat)

        XCTAssertEqual(session.queuedPacketCount, 0)
        XCTAssertEqual(try session.enqueue(newPacket, sessionEpoch: 9).map(\.header.sequence), [0])
        XCTAssertThrowsError(try session.enqueue(oldPacket, sessionEpoch: 9)) { error in
            XCTAssertEqual(error as? AudioStreamError, .staleConfigEpoch)
        }
    }

    func testInvalidConfigFailsBeforePlaybackSessionActivates() throws {
        var zeroStream = audioConfig(configEpoch: 2)
        zeroStream.streamID = 0
        XCTAssertThrowsError(try PCMStreamFormat(config: zeroStream)) { error in
            XCTAssertEqual(error as? AudioStreamError, .invalidStreamID(0))
        }

        var zeroEpoch = audioConfig(configEpoch: 0)
        XCTAssertThrowsError(try PCMStreamFormat(config: zeroEpoch)) { error in
            XCTAssertEqual(error as? AudioStreamError, .invalidConfigEpoch(0))
        }

        var emptyPacket = audioConfig(configEpoch: 2)
        emptyPacket.framesPerPacket = 0
        XCTAssertThrowsError(try PCMStreamFormat(config: emptyPacket)) { error in
            XCTAssertEqual(error as? AudioStreamError, .invalidFramesPerPacket(0))
        }

        var oversizedPacket = audioConfig(configEpoch: 2)
        oversizedPacket.framesPerPacket = PCMStreamFormat.maximumFramesPerPacket + 1
        XCTAssertThrowsError(try PCMStreamFormat(config: oversizedPacket)) { error in
            XCTAssertEqual(
                error as? AudioStreamError,
                .invalidFramesPerPacket(PCMStreamFormat.maximumFramesPerPacket + 1)
            )
        }
    }

    func testNonIncreasingConfigEpochFailsWithoutReplacingCurrentConfig() throws {
        let firstConfig = audioConfig(configEpoch: 2)
        let firstFormat = try PCMStreamFormat(config: firstConfig)
        var replayedConfig = firstConfig
        replayedConfig.configEpoch = 2
        var olderConfig = firstConfig
        olderConfig.configEpoch = 1
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        try session.accept(config: firstConfig, format: firstFormat)

        XCTAssertThrowsError(try session.accept(config: replayedConfig, format: firstFormat)) { error in
            XCTAssertEqual(error as? AudioStreamError, .nonIncreasingConfigEpoch(previous: 2, received: 2))
        }
        XCTAssertThrowsError(try session.accept(config: olderConfig, format: firstFormat)) { error in
            XCTAssertEqual(error as? AudioStreamError, .nonIncreasingConfigEpoch(previous: 2, received: 1))
        }
        XCTAssertEqual(session.config?.configEpoch, 2)
        XCTAssertTrue(session.isConfigured)
    }

    func testValidationDoesNotAdvanceEpochUntilAccepted() throws {
        let config = audioConfig(configEpoch: 2)
        let format = try PCMStreamFormat(config: config)
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        try session.validate(config: config)

        XCTAssertEqual(session.lastConfigEpoch, 0)
        XCTAssertFalse(session.isConfigured)
        try session.accept(config: config, format: format)
        XCTAssertEqual(session.lastConfigEpoch, 2)
    }

    func testFailClosedPreservesEpochWatermarkUntilSessionReset() throws {
        let config = audioConfig(configEpoch: 2)
        let format = try PCMStreamFormat(config: config)
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        try session.accept(config: config, format: format)
        session.failClosed()

        XCTAssertFalse(session.isConfigured)
        XCTAssertEqual(session.lastConfigEpoch, 2)
        XCTAssertThrowsError(try session.accept(config: config, format: format)) { error in
            XCTAssertEqual(error as? AudioStreamError, .nonIncreasingConfigEpoch(previous: 2, received: 2))
        }

        session.reset()
        XCTAssertEqual(session.lastConfigEpoch, 0)
        try session.accept(config: config, format: format)
        XCTAssertTrue(session.isConfigured)
    }

    func testPacketStreamIDMustMatchAcceptedConfig() throws {
        let config = audioConfig(configEpoch: 2)
        let format = try PCMStreamFormat(config: config)
        let wrongStreamPacket = try packet(
            streamID: 8,
            sequence: 0,
            sessionEpoch: 9,
            configEpoch: 2,
            format: format
        )
        var session = AudioPlaybackSession(maximumBufferedPackets: 3)

        try session.accept(config: config, format: format)

        XCTAssertThrowsError(try session.enqueue(wrongStreamPacket, sessionEpoch: 9)) { error in
            XCTAssertEqual(error as? AudioStreamError, .streamIDMismatch(expected: 7, received: 8))
        }
    }
}

private func audioConfig(configEpoch: UInt64) -> VSAudioConfig {
    var config = VSAudioConfig()
    config.streamID = 7
    config.configEpoch = configEpoch
    config.codec = .pcmS16Le
    config.sampleRateHz = 48_000
    config.channelCount = 2
    config.framesPerPacket = 4
    return config
}

private func packet(
    streamID: UInt64 = 7,
    sequence: UInt64,
    sessionEpoch: UInt64,
    configEpoch: UInt64,
    format: PCMStreamFormat
) throws -> AudioPacket {
    var header = VSAudioPacketHeader()
    header.streamID = streamID
    header.sessionEpoch = sessionEpoch
    header.configEpoch = configEpoch
    header.sequence = sequence
    header.frameCount = format.framesPerPacket
    let payload = Data(repeating: 0x01, count: format.bytesPerPacket)
    header.payloadLength = UInt32(payload.count)
    let headerBytes = try header.serializedData()
    return try AudioPacket(serializedFrame: encodeVarint(headerBytes.count) + headerBytes + payload)
}

private func encodeVarint(_ value: Int) -> Data {
    var remaining = value
    var data = Data()
    repeat {
        var byte = UInt8(remaining & 0x7f)
        remaining >>= 7
        if remaining > 0 { byte |= 0x80 }
        data.append(byte)
    } while remaining > 0
    return data
}
