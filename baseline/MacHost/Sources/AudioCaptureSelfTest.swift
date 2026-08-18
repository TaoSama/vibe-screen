import Foundation
import VibeScreenProtocol

enum AudioCaptureSelfTest {
    static func run() -> Bool {
        var failures: [String] = []
        testConfigValidation(failures: &failures)
        testPacketizerWireFormat(failures: &failures)
        testPacketDecodeFailures(failures: &failures)
        testBoundedCaptureQueue(failures: &failures)
        testStopDuringPacketDelivery(failures: &failures)
        testReconfigureLifecycle(failures: &failures)
        testCaptureErrorForwarding(failures: &failures)

        if failures.isEmpty {
            print("Audio capture self-test: PASS (config, packetization, decode failures, bounded queue, stop delivery, lifecycle, error forwarding)")
            return true
        }
        print("Audio capture self-test: FAIL (\(failures.joined(separator: "; "))) ")
        return false
    }

    private static func testConfigValidation(failures: inout [String]) {
        do {
            let format = try MacHostAudioConfigValidator.validate(makeConfig())
            guard format.bytesPerPacket == 16 else {
                failures.append("PCM bytes-per-packet mismatch")
                return
            }
            var unsupported = makeConfig()
            unsupported.codec = .opus
            do {
                _ = try MacHostAudioConfigValidator.validate(unsupported)
                failures.append("unsupported audio codec accepted")
            } catch MacHostAudioError.unsupportedCodec(.opus) {
                // Expected.
            } catch {
                failures.append("unsupported codec returned wrong error: \(error)")
            }
        } catch {
            failures.append("valid audio config rejected: \(error)")
        }
    }

    private static func testPacketizerWireFormat(failures: inout [String]) {
        do {
            let format = try MacHostAudioFormat(config: makeConfig(streamID: 7, configEpoch: 3))
            var packetizer = MacHostAudioPacketizer(format: format, sessionEpoch: 9, firstSequence: 40)
            let packets = try packetizer.append(MacHostAudioCaptureBuffer(
                pcmS16LE: Data(0..<16),
                frameCount: 4,
                timestampMonotonicNs: 123
            ))
            guard let packet = packets.first, packets.count == 1 else {
                failures.append("packetizer did not emit exactly one packet")
                return
            }
            guard packet.header.streamID == 7,
                  packet.header.sessionEpoch == 9,
                  packet.header.configEpoch == 3,
                  packet.header.sequence == 40,
                  packet.header.frameCount == 4,
                  packet.header.payloadLength == 16,
                  packet.timestampMonotonicNs == 123 else {
                failures.append("packet header metadata mismatch")
                return
            }
            let decoded = try MacHostAudioPacketCodec.decode(packet.serializedFrame)
            guard decoded.header == packet.header, decoded.payload == Data(0..<16) else {
                failures.append("serialized audio frame did not round trip")
                return
            }
        } catch {
            failures.append("packetizer wire-format check failed: \(error)")
        }
    }

    private static func testPacketDecodeFailures(failures: inout [String]) {
        do {
            _ = try MacHostAudioPacketCodec.decode(Data([0x80, 0x80, 0x80, 0x80, 0x80, 0x01]))
            failures.append("invalid audio header length accepted")
        } catch MacHostAudioError.invalidHeaderLength {
            // Expected.
        } catch {
            failures.append("invalid audio header length returned wrong error: \(error)")
        }

        do {
            _ = try MacHostAudioPacketCodec.decode(encodeVarint(4) + Data([1, 2]))
            failures.append("truncated audio header accepted")
        } catch MacHostAudioError.truncatedHeader(declared: 4, available: 2) {
            // Expected.
        } catch {
            failures.append("truncated audio header returned wrong error: \(error)")
        }
    }

    private static func testBoundedCaptureQueue(failures: inout [String]) {
        let source = ManualAudioCaptureSource()
        let queue = DispatchQueue(label: "dev.vibescreen.audio.self-test.blocked")
        queue.suspend()
        let stream = MacHostAudioStream(
            captureSource: source,
            maximumQueuedPackets: 3,
            processingQueue: queue
        )
        let delivered = LockedAudioSelfTestPackets()
        do {
            try stream.start(config: makeConfig(framesPerPacket: 1), sessionEpoch: 5) { packet in
                delivered.append(packet.header.sequence, UInt64(packet.payload.first ?? 0))
            }
            for index in 0..<8 {
                source.emit(frameCount: 1, pcmS16LE: Data([UInt8(index), 0, 0, 0]), timestamp: UInt64(index))
            }
            queue.resume()
            guard delivered.waitForCount(6, timeoutSeconds: 2) else {
                failures.append("bounded capture queue did not drain latest packets")
                stream.stop()
                return
            }
            stream.stop()
            guard delivered.snapshot() == [0, 5, 1, 6, 2, 7] else {
                failures.append("bounded capture queue delivered unexpected sequence/payload list: \(delivered.snapshot())")
                return
            }
        } catch {
            queue.resume()
            stream.stop()
            failures.append("bounded capture queue setup failed: \(error)")
        }
    }

    private static func testStopDuringPacketDelivery(failures: inout [String]) {
        let source = ManualAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let delivered = LockedAudioSelfTestPackets()
        do {
            try stream.start(config: makeConfig(framesPerPacket: 1), sessionEpoch: 5) { packet in
                delivered.append(packet.header.sequence)
                if packet.header.sequence == 0 {
                    stream.stop()
                } else {
                    delivered.append(99)
                }
            }
            source.emit(frameCount: 2, pcmS16LE: Data([1, 0, 2, 0, 3, 0, 4, 0]), timestamp: 1)
            guard delivered.waitForCount(1, timeoutSeconds: 2) else {
                failures.append("stop-during-delivery did not deliver first packet")
                stream.stop()
                return
            }
            Thread.sleep(forTimeInterval: 0.05)
            guard delivered.snapshot() == [0], !stream.isRunning, source.stopCount == 1 else {
                failures.append(
                    "stop-during-delivery mismatch values=\(delivered.snapshot()) running=\(stream.isRunning) stop=\(source.stopCount)"
                )
                stream.stop()
                return
            }
        } catch {
            stream.stop()
            failures.append("stop-during-delivery failed: \(error)")
        }
    }

    private static func testReconfigureLifecycle(failures: inout [String]) {
        let source = ManualAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let delivered = LockedAudioSelfTestPackets()
        do {
            try stream.start(config: makeConfig(configEpoch: 1, framesPerPacket: 1), sessionEpoch: 5) { packet in
                delivered.append(packet.header.configEpoch, packet.header.sequence, UInt64(packet.payload.count))
            }
            source.emit(frameCount: 1, pcmS16LE: Data([1, 0, 2, 0]), timestamp: 1)
            guard delivered.waitForCount(3, timeoutSeconds: 2) else {
                failures.append("initial audio stream did not deliver before reconfigure")
                stream.stop()
                return
            }
            try stream.reconfigure(config: makeConfig(configEpoch: 2, channelCount: 1, framesPerPacket: 2), sessionEpoch: 6) { packet in
                delivered.append(packet.header.configEpoch, packet.header.sequence, UInt64(packet.payload.count))
            }
            source.emit(frameCount: 2, pcmS16LE: Data([3, 0, 4, 0]), timestamp: 2)
            guard delivered.waitForCount(6, timeoutSeconds: 2) else {
                failures.append("reconfigured audio stream did not deliver both packets")
                stream.stop()
                return
            }
            stream.stop()
            guard source.startCount == 2, source.stopCount == 2 else {
                failures.append("capture source lifecycle mismatch start=\(source.startCount) stop=\(source.stopCount)")
                return
            }
            guard delivered.snapshot() == [1, 0, 4, 2, 0, 4] else {
                failures.append("reconfigure metadata mismatch: \(delivered.snapshot())")
                return
            }
        } catch {
            stream.stop()
            failures.append("reconfigure lifecycle failed: \(error)")
        }
    }

    private static func testCaptureErrorForwarding(failures: inout [String]) {
        let source = ManualAudioCaptureSource()
        let stream = MacHostAudioStream(captureSource: source, maximumQueuedPackets: 4)
        let delivered = LockedAudioSelfTestPackets()
        do {
            try stream.start(
                config: makeConfig(framesPerPacket: 1),
                sessionEpoch: 5,
                onPacket: { _ in delivered.append(99) },
                onError: { error in
                    if case MacHostAudioError.invalidFrameCount(0) = error {
                        delivered.append(1)
                    }
                }
            )
            source.emit(error: MacHostAudioError.invalidFrameCount(0))
            guard delivered.waitForCount(1, timeoutSeconds: 2) else {
                failures.append("capture error did not reach handler")
                stream.stop()
                return
            }
            guard delivered.snapshot() == [1], !stream.isRunning, source.stopCount == 1 else {
                failures.append(
                    "capture error lifecycle mismatch values=\(delivered.snapshot()) running=\(stream.isRunning) stop=\(source.stopCount)"
                )
                stream.stop()
                return
            }
        } catch {
            stream.stop()
            failures.append("capture error forwarding failed: \(error)")
        }
    }

    private static func makeConfig(
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

    private static func encodeVarint(_ value: Int) -> Data {
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

private final class ManualAudioCaptureSource: MacHostAudioCaptureSource, @unchecked Sendable {
    private let lock = NSLock()
    private var onBuffer: (@Sendable (MacHostAudioCaptureBuffer) -> Void)?
    private var onError: (@Sendable (Error) -> Void)?
    private(set) var startCount = 0
    private(set) var stopCount = 0

    func start(
        format: MacHostAudioFormat,
        onBuffer: @escaping @Sendable (MacHostAudioCaptureBuffer) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws {
        lock.withAudioSelfTestLock {
            startCount += 1
            self.onBuffer = onBuffer
            self.onError = onError
        }
    }

    func stop() {
        lock.withAudioSelfTestLock {
            stopCount += 1
            onBuffer = nil
            onError = nil
        }
    }

    func emit(frameCount: UInt32, pcmS16LE: Data, timestamp: UInt64) {
        let callback = lock.withAudioSelfTestLock { onBuffer }
        callback?(MacHostAudioCaptureBuffer(
            pcmS16LE: pcmS16LE,
            frameCount: frameCount,
            timestampMonotonicNs: timestamp
        ))
    }

    func emit(error: Error) {
        let callback = lock.withAudioSelfTestLock { onError }
        callback?(error)
    }
}

private final class LockedAudioSelfTestPackets: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [UInt64] = []

    func append(_ value: UInt64) {
        lock.withAudioSelfTestLock { values.append(value) }
    }

    func append(_ values: UInt64...) {
        lock.withAudioSelfTestLock { self.values.append(contentsOf: values) }
    }

    func snapshot() -> [UInt64] {
        lock.withAudioSelfTestLock { values }
    }

    func waitForCount(_ count: Int, timeoutSeconds: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if lock.withAudioSelfTestLock(operation: { values.count >= count }) { return true }
            Thread.sleep(forTimeInterval: 0.01)
        }
        return lock.withAudioSelfTestLock { values.count >= count }
    }
}

private extension NSLock {
    func withAudioSelfTestLock<T>(operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
