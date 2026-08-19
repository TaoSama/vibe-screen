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
    private var scheduledBuffers = 0
    private var audioSessionActive = false
    private let maximumScheduledBuffers = 8

    init() {
        engine.attach(player)
    }

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
        guard scheduledBuffers < maximumScheduledBuffers else { return false }
        guard packet.payload.count == streamFormat.bytesPerPacket else {
            throw AudioPlaybackError.invalidPCMByteCount
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
        packet.payload.copyBytes(to: destination.assumingMemoryBound(to: UInt8.self), count: packet.payload.count)
        scheduledBuffers += 1
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in self?.scheduledBuffers = max(0, (self?.scheduledBuffers ?? 1) - 1) }
        }
        return true
    }

    @discardableResult
    func stop() -> Error? {
        player.stop()
        engine.stop()
        engine.disconnectNodeOutput(player)
        streamFormat = nil
        audioFormat = nil
        scheduledBuffers = 0
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
