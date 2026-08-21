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
        guard let audioFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: Double(streamFormat.sampleRate),
            channels: AVAudioChannelCount(streamFormat.channelCount),
            interleaved: true
        ) else {
            throw AudioPlaybackError.unavailableFormat
        }
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
        let audioBuffer = buffer.mutableAudioBufferList.pointee.mBuffers
        guard let destination = audioBuffer.mData,
              Int(audioBuffer.mDataByteSize) >= packet.payload.count else {
            throw AudioPlaybackError.bufferAllocationFailed
        }
        queueState.recordScheduledBuffer()
        let scheduledGeneration = configureGeneration
        packet.payload.copyBytes(to: destination.assumingMemoryBound(to: UInt8.self), count: packet.payload.count)
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
}

@MainActor
enum AudioPlaybackSelfTest {
    static func run() async throws -> AudioPlaybackQueueSnapshot {
        var config = VSAudioConfig()
        config.streamID = 7
        config.configEpoch = 2
        config.codec = .pcmS16Le
        config.sampleRateHz = 48_000
        config.channelCount = 2
        config.framesPerPacket = PCMStreamFormat.maximumFramesPerPacket

        let controller = AudioPlaybackController()
        do {
            let format = try controller.configure(config)

            let first = try packet(sequence: 0, config: config, format: format)
            guard try controller.schedule(first) else { throw AudioPlaybackSelfTestError.initialScheduleDropped }

            var filled = 1
            for sequence in UInt64(1)...UInt64(AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers + 2) {
                let accepted = try controller.schedule(packet(sequence: sequence, config: config, format: format))
                if accepted { filled += 1 }
            }
            guard filled == AudioPlaybackQueuePolicy.defaultMaximumScheduledBuffers else {
                throw AudioPlaybackSelfTestError.queueLimitNotEnforced(filled)
            }
            guard controller.snapshot.overrunDropCount > 0 else {
                throw AudioPlaybackSelfTestError.missingOverrunObservation
            }

            try await Task.sleep(for: .milliseconds(50))
            _ = controller.stop()

            let nextConfigEpoch: UInt64 = config.configEpoch + 1
            config.configEpoch = nextConfigEpoch
            let restartedFormat = try controller.configure(config)
            guard try controller.schedule(packet(sequence: 0, config: config, format: restartedFormat)) else {
                throw AudioPlaybackSelfTestError.restartScheduleDropped
            }
            try await Task.sleep(for: .milliseconds(20))
            _ = controller.stop()
            return controller.snapshot
        } catch {
            _ = controller.stop()
            throw error
        }
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
    case initialScheduleDropped
    case queueLimitNotEnforced(Int)
    case missingOverrunObservation
    case restartScheduleDropped

    var errorDescription: String? {
        switch self {
        case .initialScheduleDropped:
            "首个 PCM 缓冲未能进入 AVAudioPlayerNode 队列"
        case let .queueLimitNotEnforced(count):
            "音频播放队列上限未按预期生效：accepted=\(count)"
        case .missingOverrunObservation:
            "音频播放队列满载时未记录 overrun/drop"
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
