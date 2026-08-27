import AVFoundation
import Foundation
import VibeScreenCore
import VibeScreenProtocol

@MainActor
final class AudioPlaybackController {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var streamFormat: PCMStreamFormat?
    private var audioFormat: AVAudioFormat?
    private var queueState = AudioPlaybackQueueState()
    private var audioSessionActive = false
    private var configureGeneration: UInt64 = 0

    init() {
        engine.attach(player)
    }

    var snapshot: AudioPlaybackQueueSnapshot { queueState.snapshot }

    func configure(_ config: VSAudioConfig) throws -> PCMStreamFormat {
        if let stopError = stop() {
            throw AudioPlaybackError.sessionDeactivationFailed(stopError.localizedDescription)
        }
        let streamFormat = try PCMStreamFormat(config: config)
        let audioFormat = AVAudioFormat(
            standardFormatWithSampleRate: Double(streamFormat.sampleRate),
            channels: AVAudioChannelCount(streamFormat.channelCount)
        )
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .moviePlayback, options: [.mixWithOthers])
            try session.setActive(true)
            audioSessionActive = true
            engine.connect(player, to: engine.mainMixerNode, format: audioFormat)
            try engine.start()
            player.play()
            self.streamFormat = streamFormat
            self.audioFormat = audioFormat
            queueState.configure(format: streamFormat)
            configureGeneration &+= 1
            return streamFormat
        } catch {
            let cleanupError = stop()
            throw AudioPlaybackError.activationFailed(
                error.localizedDescription,
                cleanupError?.localizedDescription
            )
        }
    }

    @discardableResult
    func schedule(_ packet: AudioPacket) throws -> Bool {
        guard let streamFormat, let audioFormat else { throw AudioPlaybackError.notConfigured }
        guard packet.payload.count == streamFormat.bytesPerPacket,
              packet.header.frameCount == streamFormat.framesPerPacket else {
            throw AudioPlaybackError.invalidPCMByteCount
        }
        guard queueState.hasScheduleCapacity else {
            queueState.recordOverrunDrop()
            return false
        }
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: audioFormat,
            frameCapacity: AVAudioFrameCount(streamFormat.framesPerPacket)
        ) else {
            throw AudioPlaybackError.bufferAllocationFailed
        }
        buffer.frameLength = AVAudioFrameCount(streamFormat.framesPerPacket)
        guard let channels = buffer.floatChannelData else {
            throw AudioPlaybackError.bufferAllocationFailed
        }
        queueState.recordScheduledBuffer()
        let scheduledGeneration = configureGeneration
        writeFloatSamples(from: packet.payload, to: channels, format: streamFormat)
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.configureGeneration == scheduledGeneration else { return }
                self.queueState.completeScheduledBuffer()
            }
        }
        return true
    }

    @discardableResult
    func stop() -> Error? {
        player.stop()
        engine.stop()
        engine.disconnectNodeOutput(player)
        configureGeneration &+= 1
        streamFormat = nil
        audioFormat = nil
        queueState.stop()
        guard audioSessionActive else { return nil }
        do {
            try AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
            audioSessionActive = false
            return nil
        } catch {
            return error
        }
    }

    private func writeFloatSamples(
        from payload: Data,
        to channels: UnsafePointer<UnsafeMutablePointer<Float>>,
        format: PCMStreamFormat
    ) {
        payload.withUnsafeBytes { bytes in
            let source = bytes.bindMemory(to: UInt8.self)
            let frameCount = Int(format.framesPerPacket)
            let channelCount = Int(format.channelCount)
            for frame in 0..<frameCount {
                for channel in 0..<channelCount {
                    let offset = ((frame * channelCount) + channel) * MemoryLayout<Int16>.size
                    let raw = UInt16(source[offset]) | (UInt16(source[offset + 1]) << 8)
                    let sample = Int16(bitPattern: raw)
                    channels[channel][frame] = Float(sample) / Float(Int16.max)
                }
            }
        }
    }
}

@MainActor
enum AudioPlaybackSelfTest {
    static func runQueueOnly() throws -> AudioPlaybackQueueSnapshot {
        var config = makeConfig()
        let format = try PCMStreamFormat(config: config)
        var queueState = AudioPlaybackQueueState()
        queueState.configure(format: format)

        var filled = 0
        for sequence in UInt64(0)..<UInt64(AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers + 3) {
            guard queueState.hasScheduleCapacity else {
                queueState.recordOverrunDrop()
                continue
            }
            let packet = try packet(sequence: sequence, config: config, format: format)
            guard packet.payload.count == format.bytesPerPacket,
                  packet.header.frameCount == format.framesPerPacket else {
                throw AudioPlaybackError.invalidPCMByteCount
            }
            queueState.recordScheduledBuffer()
            filled += 1
        }
        guard filled == AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers else {
            throw AudioPlaybackSelfTestError.queueLimitNotEnforced(filled)
        }
        guard queueState.overrunDropCount > 0 else {
            throw AudioPlaybackSelfTestError.missingOverrunObservation
        }
        while queueState.scheduledBufferCount > 0 {
            queueState.completeScheduledBuffer()
        }
        let firstPass = queueState.snapshot
        guard firstPass.queueEmptyCount > 0 else {
            throw AudioPlaybackSelfTestError.playbackCompletionTimedOut(firstPass)
        }

        queueState.stop()
        config.configEpoch += 1
        queueState.configure(format: try PCMStreamFormat(config: config))
        let restartedFormat = try PCMStreamFormat(config: config)
        let restartedPacket = try packet(sequence: 0, config: config, format: restartedFormat)
        guard restartedPacket.payload.count == restartedFormat.bytesPerPacket,
              restartedPacket.header.frameCount == restartedFormat.framesPerPacket else {
            throw AudioPlaybackError.invalidPCMByteCount
        }
        guard queueState.hasScheduleCapacity else {
            throw AudioPlaybackSelfTestError.restartScheduleDropped
        }
        queueState.recordScheduledBuffer()
        queueState.completeScheduledBuffer()
        queueState.stop()
        return queueState.snapshot
    }

    static func run() async throws -> AudioPlaybackQueueSnapshot {
        var config = makeConfig()

        let controller = AudioPlaybackController()
        do {
            let format = try controller.configure(config)

            var filled = 0
            for sequence in UInt64(0)..<UInt64(AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers + 3) {
                let accepted = try controller.schedule(packet(sequence: sequence, config: config, format: format))
                if accepted { filled += 1 }
            }
            guard filled == AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers else {
                throw AudioPlaybackSelfTestError.queueLimitNotEnforced(filled)
            }
            guard controller.snapshot.overrunDropCount > 0 else {
                throw AudioPlaybackSelfTestError.missingOverrunObservation
            }
            let firstPass = try await waitForPlaybackDrain(
                controller: controller,
                playedAfter: 0,
                queueEmptyAfter: 0,
                timeout: .seconds(3)
            )

            _ = controller.stop()

            let nextConfigEpoch: UInt64 = config.configEpoch + 1
            config.configEpoch = nextConfigEpoch
            let restartedFormat = try controller.configure(config)
            guard try controller.schedule(packet(sequence: 0, config: config, format: restartedFormat)) else {
                throw AudioPlaybackSelfTestError.restartScheduleDropped
            }
            _ = try await waitForPlaybackDrain(
                controller: controller,
                playedAfter: firstPass.playedBufferTotal,
                queueEmptyAfter: firstPass.queueEmptyCount,
                timeout: .seconds(3)
            )
            _ = controller.stop()
            return controller.snapshot
        } catch {
            _ = controller.stop()
            throw error
        }
    }

    private static func makeConfig() -> VSAudioConfig {
        var config = VSAudioConfig()
        config.streamID = 7
        config.configEpoch = 2
        config.codec = .pcmS16Le
        config.sampleRateHz = 48_000
        config.channelCount = 2
        config.framesPerPacket = 480
        return config
    }

    private static func packet(sequence: UInt64, config: VSAudioConfig, format: PCMStreamFormat) throws -> AudioPacket {
        var header = VSAudioPacketHeader()
        header.streamID = config.streamID
        header.sessionEpoch = 9
        header.configEpoch = config.configEpoch
        header.sequence = sequence
        header.frameCount = format.framesPerPacket
        let payload = sinePCM(format: format, sequence: sequence)
        header.payloadLength = UInt32(payload.count)
        let headerBytes = try header.serializedData()
        return try AudioPacket(serializedFrame: encodeVarint(headerBytes.count) + headerBytes + payload)
    }

    private static func waitForPlaybackDrain(
        controller: AudioPlaybackController,
        playedAfter playedBaseline: UInt64,
        queueEmptyAfter queueEmptyBaseline: UInt64,
        timeout: Duration
    ) async throws -> AudioPlaybackQueueSnapshot {
        let deadline = ContinuousClock.now.advanced(by: timeout)
        while ContinuousClock.now < deadline {
            let snapshot = controller.snapshot
            if snapshot.playedBufferTotal > playedBaseline,
               snapshot.queueEmptyCount > queueEmptyBaseline,
               snapshot.scheduledBufferCount == 0 {
                return snapshot
            }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw AudioPlaybackSelfTestError.playbackCompletionTimedOut(controller.snapshot)
    }

    private static func encodeVarint(_ value: Int) -> Data {
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

    private static func sinePCM(format: PCMStreamFormat, sequence: UInt64) -> Data {
        var data = Data(capacity: format.bytesPerPacket)
        let sampleRate = Double(format.sampleRate)
        let frequency = 440.0
        for frame in 0..<format.framesPerPacket {
            let t = Double(sequence * UInt64(format.framesPerPacket) + UInt64(frame)) / sampleRate
            let sample = Int16((sin(2.0 * .pi * frequency * t) * 0.25 * Double(Int16.max)).rounded())
            for _ in 0..<format.channelCount {
                data.append(UInt8(truncatingIfNeeded: sample))
                data.append(UInt8(truncatingIfNeeded: sample >> 8))
            }
        }
        return data
    }
}

enum AudioPlaybackSelfTestError: Error, LocalizedError {
    case queueLimitNotEnforced(Int)
    case missingOverrunObservation
    case playbackCompletionTimedOut(AudioPlaybackQueueSnapshot)
    case restartScheduleDropped

    var errorDescription: String? {
        switch self {
        case let .queueLimitNotEnforced(count):
            "音频播放队列上限未按预期生效：accepted=\(count)"
        case .missingOverrunObservation:
            "音频播放队列满载时未记录 overrun/drop"
        case let .playbackCompletionTimedOut(snapshot):
            "等待 PCM 缓冲播放完成超时：played=\(snapshot.playedBufferTotal) queued=\(snapshot.scheduledBufferCount) queue_empty=\(snapshot.queueEmptyCount)"
        case .restartScheduleDropped:
            "停止重启后 PCM 缓冲未能重新进入播放队列"
        }
    }
}

enum AudioPlaybackError: Error, LocalizedError {
    case unavailableFormat
    case notConfigured
    case invalidPCMByteCount
    case bufferAllocationFailed
    case sessionDeactivationFailed(String)
    case activationFailed(String, String?)

    var errorDescription: String? {
        switch self {
        case .unavailableFormat:
            "当前设备无法创建 PCM S16LE 播放格式"
        case .notConfigured:
            "音频播放尚未完成配置"
        case .invalidPCMByteCount:
            "音频帧字节数与协商格式不匹配"
        case .bufferAllocationFailed:
            "音频播放缓冲区分配失败"
        case let .sessionDeactivationFailed(message):
            "旧音频会话停止失败：\(message)"
        case let .activationFailed(message, cleanupMessage):
            if let cleanupMessage {
                "音频会话启动失败：\(message)；清理失败：\(cleanupMessage)"
            } else {
                "音频会话启动失败：\(message)"
            }
        }
    }
}
