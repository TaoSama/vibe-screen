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
    private let maximumScheduledBuffers = 8

    init() {
        engine.attach(player)
    }

    func configure(_ config: VSAudioConfig) throws -> PCMStreamFormat {
        let streamFormat = try PCMStreamFormat(config: config)
        guard let audioFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: Double(streamFormat.sampleRate),
            channels: AVAudioChannelCount(streamFormat.channelCount),
            interleaved: true
        ) else {
            throw AudioPlaybackError.unavailableFormat
        }
        stop()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .moviePlayback, options: [.mixWithOthers])
        try session.setActive(true)
        engine.connect(player, to: engine.mainMixerNode, format: audioFormat)
        try engine.start()
        player.play()
        self.streamFormat = streamFormat
        self.audioFormat = audioFormat
        return streamFormat
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

    func stop() {
        player.stop()
        engine.stop()
        engine.disconnectNodeOutput(player)
        streamFormat = nil
        audioFormat = nil
        scheduledBuffers = 0
    }
}

enum AudioPlaybackError: Error {
    case unavailableFormat
    case notConfigured
    case invalidPCMByteCount
    case bufferAllocationFailed
}
