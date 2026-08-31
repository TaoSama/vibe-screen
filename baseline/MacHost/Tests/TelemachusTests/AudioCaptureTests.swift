import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class AudioCaptureTests: XCTestCase {
    func testConfigValidatorAcceptsPCMS16LEAndBuildsResult() throws {
        let config = makeConfig(streamID: 7, configEpoch: 3, framesPerPacket: 480)

        let format = try MacHostAudioConfigValidator.validate(config)
        XCTAssertEqual(format.streamID, 7)
        XCTAssertEqual(format.configEpoch, 3)
        XCTAssertEqual(format.sampleRateHz, 48_000)
        XCTAssertEqual(format.channelCount, 2)
        XCTAssertEqual(format.framesPerPacket, 480)
        XCTAssertEqual(format.bytesPerPacket, 1_920)

        let result = MacHostAudioConfigValidator.result(for: config)
        XCTAssertTrue(result.accepted)
        XCTAssertEqual(result.streamID, 7)
        XCTAssertEqual(result.configEpoch, 3)
        XCTAssertTrue(result.rejectionReason.isEmpty)
    }

    func testConfigValidatorRejectsInvalidProtocolValues() {
        var zeroStream = makeConfig(streamID: 0)
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(zeroStream)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidStreamID)
        }

        zeroStream.streamID = 1
        zeroStream.configEpoch = 0
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(zeroStream)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidConfigEpoch)
        }

        var unsupportedCodec = makeConfig()
        unsupportedCodec.codec = .opus
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(unsupportedCodec)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .unsupportedCodec(.opus))
        }

        var lowSampleRate = makeConfig()
        lowSampleRate.sampleRateHz = 7_999
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(lowSampleRate)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidSampleRate(7_999))
        }

        var tooManyChannels = makeConfig()
        tooManyChannels.channelCount = 9
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(tooManyChannels)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidChannelCount(9))
        }

        var zeroFrames = makeConfig()
        zeroFrames.framesPerPacket = 0
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(zeroFrames)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidFramesPerPacket(0))
        }

        var oversized = makeConfig(sampleRateHz: 192_000, channelCount: 8)
        oversized.framesPerPacket = UInt32(ProtocolV1Framer.maximumPayloadBytes / 16 + 1)
        XCTAssertThrowsError(try MacHostAudioConfigValidator.validate(oversized)) { error in
            XCTAssertEqual(
                error as? MacHostAudioError,
                .payloadTooLarge(Int(oversized.framesPerPacket) * 16)
            )
        }
    }

    func testPacketizerSerializesDelimitedAudioPacketHeaderForIOSConsumer() throws {
        let format = try MacHostAudioFormat(config: makeConfig(streamID: 11, configEpoch: 4, framesPerPacket: 4))
        var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: 9)
        let payload = Data(0..<16)

        let packets = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: payload,
            frameCount: 4,
            timestampMonotonicNs: 123_456
        ))

        XCTAssertEqual(packets.count, 1)
        let packet = try XCTUnwrap(packets.first)
        XCTAssertEqual(packet.header.streamID, 11)
        XCTAssertEqual(packet.header.sessionEpoch, 9)
        XCTAssertEqual(packet.header.configEpoch, 4)
        XCTAssertEqual(packet.header.sequence, 0)
        XCTAssertEqual(packet.header.frameCount, 4)
        XCTAssertEqual(packet.header.payloadLength, 16)
        XCTAssertEqual(packet.timestampMonotonicNs, 123_456)
        XCTAssertEqual(packet.payload, payload)

        let decoded = try MacHostAudioPacketCodec.decode(packet.serializedFrame)
        XCTAssertEqual(decoded.header, packet.header)
        XCTAssertEqual(decoded.payload, payload)
    }

    func testPacketizerCoalescesPartialBuffersAndIncrementsSequence() throws {
        let format = try MacHostAudioFormat(config: makeConfig(framesPerPacket: 4))
        var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: 2, firstSequence: 41)

        let first = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data([0, 1, 2, 3]),
            frameCount: 1,
            timestampMonotonicNs: 10
        ))
        XCTAssertTrue(first.isEmpty)

        let second = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data([4, 5, 6, 7, 8, 9, 10, 11]),
            frameCount: 2,
            timestampMonotonicNs: 20
        ))
        XCTAssertTrue(second.isEmpty)

        let third = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data([12, 13, 14, 15, 16, 17, 18, 19]),
            frameCount: 2,
            timestampMonotonicNs: 30
        ))
        XCTAssertEqual(third.map(\.header.sequence), [41])
        XCTAssertEqual(third.first?.payload, Data(0..<16))
        XCTAssertEqual(third.first?.timestampMonotonicNs, 10)

        let fourth = try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data(20..<32),
            frameCount: 3,
            timestampMonotonicNs: 40
        ))
        XCTAssertEqual(fourth.map(\.header.sequence), [42])
        XCTAssertEqual(fourth.first?.payload, Data(16..<32))
        XCTAssertEqual(fourth.first?.timestampMonotonicNs, 30)
    }

    func testPacketizerRejectsSequenceOverflow() throws {
        let format = try MacHostAudioFormat(config: makeConfig(framesPerPacket: 1))
        var packetizer = MacHostAudioPacketizer(
            format: format,
            sessionEpoch: 2,
            firstSequence: UInt64.max
        )

        XCTAssertThrowsError(try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data([1, 0, 2, 0]),
            frameCount: 1,
            timestampMonotonicNs: 1
        ))) { error in
            XCTAssertEqual(error as? MacHostAudioError, .sequenceOverflow)
        }
    }

    func testPacketizerRejectsPCMByteCountMismatch() throws {
        let format = try MacHostAudioFormat(config: makeConfig(framesPerPacket: 4))
        var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: 2)

        XCTAssertThrowsError(try packetizer.append(MacHostAudioCaptureBuffer(
            pcmS16LE: Data([1, 2]),
            frameCount: 4,
            timestampMonotonicNs: 1
        ))) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidPCMByteCount(expected: 16, actual: 2))
        }
    }

    func testPacketCodecRejectsPayloadLengthMismatch() throws {
        var header = VSAudioPacketHeader()
        header.streamID = 1
        header.sessionEpoch = 2
        header.configEpoch = 3
        header.sequence = 4
        header.frameCount = 1
        header.payloadLength = 4

        XCTAssertThrowsError(try MacHostAudioPacketCodec.encode(header: header, payload: Data([1, 2]))) { error in
            XCTAssertEqual(
                error as? MacHostAudioError,
                .payloadLengthMismatch(declared: 4, actual: 2)
            )
        }

        let headerBytes = try header.serializedData()
        var serialized = encodeVarint(headerBytes.count)
        serialized.append(headerBytes)
        serialized.append(Data([1, 2]))
        XCTAssertThrowsError(try MacHostAudioPacketCodec.decode(serialized)) { error in
            XCTAssertEqual(
                error as? MacHostAudioError,
                .payloadLengthMismatch(declared: 4, actual: 2)
            )
        }
    }

    func testPacketCodecRejectsInvalidAndTruncatedHeaderLength() throws {
        XCTAssertThrowsError(try MacHostAudioPacketCodec.decode(Data([0x80, 0x80, 0x80, 0x80, 0x80, 0x01]))) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidHeaderLength)
        }

        let truncatedHeader = encodeVarint(4) + Data([1, 2])
        XCTAssertThrowsError(try MacHostAudioPacketCodec.decode(truncatedHeader)) { error in
            XCTAssertEqual(error as? MacHostAudioError, .truncatedHeader(declared: 4, available: 2))
        }
    }

    func testBacklogKeepsLatestBoundedPackets() throws {
        let format = try MacHostAudioFormat(config: makeConfig(framesPerPacket: 1))
        var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: 2)
        var backlog = MacHostAudioPacketBacklog(maximumPackets: 3)

        for sequence in 0..<5 {
            let packets = try packetizer.append(MacHostAudioCaptureBuffer(
                pcmS16LE: Data([UInt8(sequence), 0, 0, 0]),
                frameCount: 1,
                timestampMonotonicNs: UInt64(sequence)
            ))
            for packet in packets {
                let result = backlog.enqueue(packet)
                if sequence < 3 {
                    XCTAssertEqual(result, MacHostAudioBacklogResult(accepted: true, droppedPacketCount: 0))
                } else {
                    XCTAssertEqual(result, MacHostAudioBacklogResult(accepted: false, droppedPacketCount: 1))
                }
            }
        }

        XCTAssertEqual(backlog.queuedPacketCount, 3)
        XCTAssertEqual(backlog.drain().map(\.header.sequence), [2, 3, 4])
        XCTAssertEqual(backlog.queuedPacketCount, 0)
    }

    func testStreamStartStopAndStaleCallbackIsolation() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let firstPacket = expectation(description: "first packet delivered")
        let lateCallbackIgnored = expectation(description: "late callback ignored")
        lateCallbackIgnored.isInverted = true
        let lock = NSLock()
        var delivered: [UInt64] = []

        try stream.start(config: makeConfig(framesPerPacket: 1), sessionEpoch: 5) { packet in
            lock.withAudioTestLock {
                delivered.append(packet.header.sequence)
                if packet.header.configEpoch == 1 {
                    firstPacket.fulfill()
                } else {
                    lateCallbackIgnored.fulfill()
                }
            }
        }
        XCTAssertTrue(stream.isRunning)
        XCTAssertEqual(source.startCount, 1)

        source.emit(frameCount: 1, pcmS16LE: Data([1, 0, 2, 0]), timestamp: 10)
        wait(for: [firstPacket], timeout: 1)
        stream.stop()
        XCTAssertFalse(stream.isRunning)
        XCTAssertEqual(source.stopCount, 1)

        source.emit(frameCount: 1, pcmS16LE: Data([3, 0, 4, 0]), timestamp: 20)
        wait(for: [lateCallbackIgnored], timeout: 0.2)
        XCTAssertEqual(lock.withAudioTestLock { delivered }, [0])
    }

    func testStreamStartRejectsZeroSessionEpochWithoutStartingSource() {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)

        XCTAssertThrowsError(try stream.start(config: makeConfig(), sessionEpoch: 0, onPacket: { _ in })) { error in
            XCTAssertEqual(error as? MacHostAudioError, .invalidSessionEpoch)
        }

        XCTAssertFalse(stream.isRunning)
        XCTAssertNil(stream.currentFormat)
        XCTAssertEqual(source.startCount, 0)
        XCTAssertEqual(source.stopCount, 0)
    }

    func testStreamStopDuringPacketDeliverySuppressesRemainingPackets() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let firstPacket = expectation(description: "first packet delivered")
        let secondPacketIgnored = expectation(description: "second packet ignored after stop")
        secondPacketIgnored.isInverted = true
        let lock = NSLock()
        var delivered: [UInt64] = []

        try stream.start(config: makeConfig(framesPerPacket: 1), sessionEpoch: 5) { packet in
            lock.withAudioTestLock { delivered.append(packet.header.sequence) }
            if packet.header.sequence == 0 {
                firstPacket.fulfill()
                stream.stop()
            } else {
                secondPacketIgnored.fulfill()
            }
        }

        source.emit(frameCount: 2, pcmS16LE: Data([1, 0, 2, 0, 3, 0, 4, 0]), timestamp: 10)
        wait(for: [firstPacket], timeout: 1)
        wait(for: [secondPacketIgnored], timeout: 0.2)

        XCTAssertFalse(stream.isRunning)
        XCTAssertEqual(source.stopCount, 1)
        XCTAssertEqual(lock.withAudioTestLock { delivered }, [0])
    }

    func testStreamReconfigureRestartsSourceAndResetsSequence() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let initialPacketReady = expectation(description: "initial packet delivered before reconfigure")
        let reconfiguredPacketReady = expectation(description: "packet delivered after reconfigure")
        let lock = NSLock()
        var delivered: [(epoch: UInt64, sequence: UInt64, byteCount: Int)] = []

        try stream.start(config: makeConfig(configEpoch: 1, framesPerPacket: 1), sessionEpoch: 5) { packet in
            lock.withAudioTestLock {
                delivered.append((packet.header.configEpoch, packet.header.sequence, packet.payload.count))
                initialPacketReady.fulfill()
            }
        }
        source.emit(frameCount: 1, pcmS16LE: Data([1, 0, 2, 0]), timestamp: 10)
        wait(for: [initialPacketReady], timeout: 1)

        try stream.reconfigure(config: makeConfig(configEpoch: 2, channelCount: 1, framesPerPacket: 2), sessionEpoch: 6) { packet in
            lock.withAudioTestLock {
                delivered.append((packet.header.configEpoch, packet.header.sequence, packet.payload.count))
                reconfiguredPacketReady.fulfill()
            }
        }
        XCTAssertEqual(source.stopCount, 1)
        XCTAssertEqual(source.startCount, 2)
        source.emit(frameCount: 2, pcmS16LE: Data([3, 0, 4, 0]), timestamp: 20)

        wait(for: [reconfiguredPacketReady], timeout: 1)
        XCTAssertEqual(lock.withAudioTestLock { delivered.map(\.epoch) }, [1, 2])
        XCTAssertEqual(lock.withAudioTestLock { delivered.map(\.sequence) }, [0, 0])
        XCTAssertEqual(lock.withAudioTestLock { delivered.map(\.byteCount) }, [4, 4])
        XCTAssertEqual(stream.currentFormat?.channelCount, 1)
        stream.stop()
    }

    func testStreamForwardsCaptureErrorAndStops() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let errorDelivered = expectation(description: "capture error delivered")
        let lock = NSLock()
        var deliveredError: MacHostAudioError?

        try stream.start(
            config: makeConfig(framesPerPacket: 1),
            sessionEpoch: 5,
            onPacket: { _ in XCTFail("unexpected packet after capture error") },
            onError: { error in
                lock.withAudioTestLock { deliveredError = error as? MacHostAudioError }
                errorDelivered.fulfill()
            }
        )

        source.emit(error: MacHostAudioError.invalidFrameCount(0))
        wait(for: [errorDelivered], timeout: 1)

        XCTAssertEqual(lock.withAudioTestLock { deliveredError }, .invalidFrameCount(0))
        XCTAssertFalse(stream.isRunning)
        XCTAssertEqual(source.stopCount, 1)
    }

    func testStreamIgnoresZeroFrameCaptureWithoutFailing() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let packetIgnored = expectation(description: "zero-frame capture ignored")
        packetIgnored.isInverted = true
        let errorIgnored = expectation(description: "zero-frame capture does not fail")
        errorIgnored.isInverted = true

        try stream.start(
            config: makeConfig(framesPerPacket: 1),
            sessionEpoch: 5,
            onPacket: { _ in packetIgnored.fulfill() },
            onError: { _ in errorIgnored.fulfill() }
        )

        source.emit(frameCount: 0, pcmS16LE: Data(), timestamp: 10)
        wait(for: [packetIgnored, errorIgnored], timeout: 0.2)

        XCTAssertTrue(stream.isRunning)
        XCTAssertEqual(source.stopCount, 0)
        stream.stop()
    }

    func testStaleCaptureErrorDoesNotStopActiveGeneration() throws {
        let source = FakeAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let staleErrorIgnored = expectation(description: "stale error ignored")
        staleErrorIgnored.isInverted = true
        let activePacketDelivered = expectation(description: "active packet delivered")
        let lock = NSLock()
        var delivered: [UInt64] = []

        try stream.start(
            config: makeConfig(configEpoch: 1, framesPerPacket: 1),
            sessionEpoch: 5,
            onPacket: { _ in XCTFail("unexpected first-generation packet") },
            onError: { _ in staleErrorIgnored.fulfill() }
        )
        let staleErrorCallback = try XCTUnwrap(source.currentErrorCallback())

        try stream.reconfigure(config: makeConfig(configEpoch: 2, framesPerPacket: 1), sessionEpoch: 6) { packet in
            lock.withAudioTestLock { delivered.append(packet.header.configEpoch) }
            activePacketDelivered.fulfill()
        }
        XCTAssertEqual(source.stopCount, 1)

        staleErrorCallback(MacHostAudioError.invalidFrameCount(0))
        wait(for: [staleErrorIgnored], timeout: 0.2)

        XCTAssertTrue(stream.isRunning)
        XCTAssertEqual(source.stopCount, 1)
        source.emit(frameCount: 1, pcmS16LE: Data([1, 0, 2, 0]), timestamp: 20)
        wait(for: [activePacketDelivered], timeout: 1)
        XCTAssertEqual(lock.withAudioTestLock { delivered }, [2])
        stream.stop()
    }

    private func makeConfig(
        streamID: UInt64 = 1,
        configEpoch: UInt64 = 1,
        sampleRateHz: UInt32 = 48_000,
        channelCount: UInt32 = 2,
        framesPerPacket: UInt32 = 4
    ) -> VSAudioConfig {
        var config = VSAudioConfig()
        config.streamID = streamID
        config.configEpoch = configEpoch
        config.codec = .pcmS16Le
        config.sampleRateHz = sampleRateHz
        config.channelCount = channelCount
        config.framesPerPacket = framesPerPacket
        return config
    }

    private func encodeVarint(_ value: Int) -> Data {
        var remaining = UInt64(value)
        var data = Data()
        repeat {
            var byte = UInt8(remaining & 0x7f)
            remaining >>= 7
            if remaining > 0 { byte |= 0x80 }
            data.append(byte)
        } while remaining > 0
        return data
    }
}

private final class FakeAudioCaptureSource: MacHostAudioCaptureSource, @unchecked Sendable {
    private let lock = NSLock()
    private var onBuffer: (@Sendable (MacHostAudioCaptureBuffer) -> Void)?
    private var onError: (@Sendable (Error) -> Void)?
    private(set) var startCount = 0
    private(set) var stopCount = 0
    private(set) var latestFormat: MacHostAudioFormat?

    func start(
        format: MacHostAudioFormat,
        onBuffer: @escaping @Sendable (MacHostAudioCaptureBuffer) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws {
        lock.withAudioTestLock {
            startCount += 1
            latestFormat = format
            self.onBuffer = onBuffer
            self.onError = onError
        }
    }

    func stop() {
        lock.withAudioTestLock {
            stopCount += 1
            onBuffer = nil
            onError = nil
        }
    }

    func emit(frameCount: UInt32, pcmS16LE: Data, timestamp: UInt64) {
        let callback = lock.withAudioTestLock { onBuffer }
        callback?(MacHostAudioCaptureBuffer(
            pcmS16LE: pcmS16LE,
            frameCount: frameCount,
            timestampMonotonicNs: timestamp
        ))
    }

    func emit(error: Error) {
        let callback = lock.withAudioTestLock { onError }
        callback?(error)
    }

    func currentErrorCallback() -> (@Sendable (Error) -> Void)? {
        lock.withAudioTestLock { onError }
    }
}

private extension NSLock {
    func withAudioTestLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
