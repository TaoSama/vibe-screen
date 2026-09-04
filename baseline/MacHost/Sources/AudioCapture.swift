@preconcurrency import AVFoundation
import CoreAudio
import Foundation
import VibeScreenProtocol

protocol MacHostAudioCaptureSource: AnyObject, Sendable {
    var canAdvertiseCapture: Bool { get }

    func start(
        format: MacHostAudioFormat,
        onBuffer: @escaping @Sendable (MacHostAudioCaptureBuffer) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws
    func stop()
}

extension MacHostAudioCaptureSource {
    var canAdvertiseCapture: Bool { true }
}

final class AVAudioEnginePCMSource: MacHostAudioCaptureSource, @unchecked Sendable {
    private let lock = NSLock()
    private var engine: AVAudioEngine?
    private var conversionState: AVAudioPCMConversionState?

    var canAdvertiseCapture: Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined, .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }

    func start(
        format: MacHostAudioFormat,
        onBuffer: @escaping @Sendable (MacHostAudioCaptureBuffer) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws {
        try Self.requireMicrophoneAuthorization()
        try lock.withAudioLock {
            guard engine == nil else { throw MacHostAudioError.alreadyRunning }
            let engine = AVAudioEngine()
            let inputNode = engine.inputNode
            let inputFormat = inputNode.inputFormat(forBus: 0)
            guard let outputFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: Double(format.sampleRateHz),
                channels: AVAudioChannelCount(format.channelCount),
                interleaved: true
            ) else {
                throw MacHostAudioError.captureStartFailed("PCM S16LE format is unavailable.")
            }
            guard let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
                throw MacHostAudioError.captureStartFailed("Audio converter is unavailable.")
            }
            let conversionState = AVAudioPCMConversionState(
                streamFormat: format,
                outputFormat: outputFormat,
                converter: converter
            )
            inputNode.installTap(
                onBus: 0,
                bufferSize: AVAudioFrameCount(format.framesPerPacket),
                format: inputFormat
            ) { buffer, time in
                do {
                    if let capture = try conversionState.captureBuffer(from: buffer, time: time) {
                        onBuffer(capture)
                    }
                } catch {
                    onError(error)
                }
            }
            do {
                try engine.start()
            } catch {
                conversionState.stop()
                inputNode.removeTap(onBus: 0)
                throw error
            }
            self.engine = engine
            self.conversionState = conversionState
        }
    }

    func stop() {
        let stopped = lock.withAudioLock { () -> (AVAudioEngine, AVAudioPCMConversionState)? in
            guard let engine, let conversionState else { return nil }
            self.engine = nil
            self.conversionState = nil
            return (engine, conversionState)
        }
        guard let (engine, conversionState) = stopped else { return }
        conversionState.stop()
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    private static func requireMicrophoneAuthorization() throws {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return
        case .notDetermined, .denied, .restricted:
            throw MacHostAudioError.captureStartFailed(
                "Microphone access is required for Mac audio capture. Enable it in System Settings > Privacy & Security > Microphone."
            )
        @unknown default:
            throw MacHostAudioError.captureStartFailed(
                "Microphone authorization status is unavailable."
            )
        }
    }
}

private final class AVAudioPCMConversionState: @unchecked Sendable {
    private let streamFormat: MacHostAudioFormat
    private let outputFormat: AVAudioFormat
    private let converter: AVAudioConverter
    private let lock = NSLock()
    private var active = true

    init(streamFormat: MacHostAudioFormat, outputFormat: AVAudioFormat, converter: AVAudioConverter) {
        self.streamFormat = streamFormat
        self.outputFormat = outputFormat
        self.converter = converter
    }

    func stop() {
        lock.withAudioLock { active = false }
    }

    func captureBuffer(
        from buffer: AVAudioPCMBuffer,
        time: AVAudioTime
    ) throws -> MacHostAudioCaptureBuffer? {
        try lock.withAudioLock {
            guard active else { throw MacHostAudioError.notRunning }
            let ratio = outputFormat.sampleRate / max(buffer.format.sampleRate, 1)
            let outputCapacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * ratio))
            guard let converted = AVAudioPCMBuffer(
                pcmFormat: outputFormat,
                frameCapacity: max(outputCapacity, 1)
            ) else {
                throw MacHostAudioError.captureStartFailed("PCM conversion buffer allocation failed.")
            }

            var didProvideInput = false
            var conversionError: NSError?
            converter.convert(to: converted, error: &conversionError) { _, status in
                guard !didProvideInput else {
                    status.pointee = .noDataNow
                    return nil
                }
                didProvideInput = true
                status.pointee = .haveData
                return buffer
            }
            if let conversionError { throw conversionError }

            let frameCount = UInt32(converted.frameLength)
            guard frameCount > 0 else { return nil }
            let expectedBytes = Int(frameCount) * streamFormat.bytesPerFrame
            let audioBuffer = converted.audioBufferList.pointee.mBuffers
            guard let source = audioBuffer.mData,
                  Int(audioBuffer.mDataByteSize) >= expectedBytes else {
                throw MacHostAudioError.invalidPCMByteCount(
                    expected: expectedBytes,
                    actual: Int(audioBuffer.mDataByteSize)
                )
            }
            let payload = Data(bytes: source, count: expectedBytes)
            let hostTime = time.hostTime == 0 ? mach_absolute_time() : time.hostTime
            return MacHostAudioCaptureBuffer(
                pcmS16LE: payload,
                frameCount: frameCount,
                timestampMonotonicNs: AudioConvertHostTimeToNanos(hostTime)
            )
        }
    }
}

final class MacHostAudioStream: @unchecked Sendable {
    typealias PacketHandler = @Sendable (MacHostAudioPacket) -> Void
    typealias ErrorHandler = @Sendable (Error) -> Void

    private struct RunningState {
        let generation: UInt64
        var packetizer: MacHostAudioPacketizer
        var backlog: MacHostAudioPacketBacklog
        var pendingCaptures: [MacHostAudioCaptureBuffer]
        var captureDrainScheduled: Bool
        let packetHandler: PacketHandler
        let errorHandler: ErrorHandler

        var format: MacHostAudioFormat { packetizer.format }
    }

    private let captureSource: MacHostAudioCaptureSource
    private let processingQueue: DispatchQueue
    private let maximumQueuedPackets: Int
    private let lock = NSLock()
    private var generation: UInt64 = 0
    private var runningState: RunningState?

    init(
        captureSource: MacHostAudioCaptureSource = AVAudioEnginePCMSource(),
        maximumQueuedPackets: Int = 8,
        processingQueue: DispatchQueue = DispatchQueue(label: "dev.vibescreen.audio.capture")
    ) {
        self.captureSource = captureSource
        self.maximumQueuedPackets = max(1, maximumQueuedPackets)
        self.processingQueue = processingQueue
    }

    var isRunning: Bool {
        lock.withAudioLock { runningState != nil }
    }

    var currentFormat: MacHostAudioFormat? {
        lock.withAudioLock { runningState?.format }
    }

    var canAdvertiseCapture: Bool {
        captureSource.canAdvertiseCapture
    }

    func start(
        config: VSAudioConfig,
        sessionEpoch: UInt64,
        onPacket: @escaping PacketHandler,
        onError: @escaping ErrorHandler = { _ in }
    ) throws {
        guard sessionEpoch != 0 else { throw MacHostAudioError.invalidSessionEpoch }
        let format = try MacHostAudioConfigValidator.validate(config)
        let startGeneration = try lock.withAudioLock { () throws -> UInt64 in
            guard runningState == nil else { throw MacHostAudioError.alreadyRunning }
            generation &+= 1
            let currentGeneration = generation
            runningState = RunningState(
                generation: currentGeneration,
                packetizer: MacHostAudioPacketizer(format: format, sessionEpoch: sessionEpoch),
                backlog: MacHostAudioPacketBacklog(maximumPackets: maximumQueuedPackets),
                pendingCaptures: [],
                captureDrainScheduled: false,
                packetHandler: onPacket,
                errorHandler: onError
            )
            return currentGeneration
        }

        do {
            try captureSource.start(
                format: format,
                onBuffer: { [weak self] capture in
                    self?.ingest(capture, generation: startGeneration)
                },
                onError: { [weak self] error in
                    self?.fail(error, generation: startGeneration)
                }
            )
        } catch {
            lock.withAudioLock {
                if runningState?.generation == startGeneration { runningState = nil }
            }
            throw error
        }
    }

    func stop() {
        lock.withAudioLock {
            generation &+= 1
            runningState = nil
        }
        captureSource.stop()
    }

    func reconfigure(
        config: VSAudioConfig,
        sessionEpoch: UInt64,
        onPacket: @escaping PacketHandler,
        onError: @escaping ErrorHandler = { _ in }
    ) throws {
        stop()
        try start(config: config, sessionEpoch: sessionEpoch, onPacket: onPacket, onError: onError)
    }

    private func ingest(_ capture: MacHostAudioCaptureBuffer, generation: UInt64) {
        guard capture.frameCount > 0 else { return }
        let shouldScheduleDrain = lock.withAudioLock { () -> Bool in
            guard var state = runningState, state.generation == generation else { return false }
            state.pendingCaptures.append(capture)
            while state.pendingCaptures.count > maximumQueuedPackets {
                state.pendingCaptures.removeFirst()
            }
            guard !state.captureDrainScheduled else {
                runningState = state
                return false
            }
            state.captureDrainScheduled = true
            runningState = state
            return true
        }
        guard shouldScheduleDrain else { return }
        processingQueue.async { [weak self] in
            self?.drainCaptures(generation: generation)
        }
    }

    private func drainCaptures(generation: UInt64) {
        let captures = lock.withAudioLock { () -> [MacHostAudioCaptureBuffer]? in
            guard var state = runningState, state.generation == generation else { return nil }
            let captures = state.pendingCaptures
            state.pendingCaptures.removeAll(keepingCapacity: true)
            state.captureDrainScheduled = false
            runningState = state
            return captures
        }
        guard let captures else { return }
        for capture in captures {
            process(capture, generation: generation)
        }
    }

    private func process(_ capture: MacHostAudioCaptureBuffer, generation: UInt64) {
        do {
            let delivery = try lock.withAudioLock { () throws -> [MacHostAudioPacket]? in
                guard var state = runningState, state.generation == generation else { return nil }
                let packets = try state.packetizer.append(capture)
                for packet in packets { _ = state.backlog.enqueue(packet) }
                let drained = state.backlog.drain()
                runningState = state
                return drained
            }
            guard let packets = delivery else { return }
            for packet in packets {
                let handler = lock.withAudioLock { () -> PacketHandler? in
                    guard let state = runningState, state.generation == generation else { return nil }
                    return state.packetHandler
                }
                guard let handler else { return }
                handler(packet)
            }
        } catch {
            fail(error, generation: generation)
        }
    }

    private func fail(_ error: Error, generation: UInt64) {
        let errorHandler = lock.withAudioLock { () -> ErrorHandler? in
            guard let state = runningState, state.generation == generation else { return nil }
            runningState = nil
            self.generation &+= 1
            return state.errorHandler
        }
        guard let errorHandler else { return }
        captureSource.stop()
        errorHandler(error)
    }
}

private extension NSLock {
    func withAudioLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
