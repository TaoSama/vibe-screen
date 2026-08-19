import Foundation
@preconcurrency import ScreenCaptureKit
import VideoToolbox
import CoreMedia
import CoreGraphics
@preconcurrency import CoreVideo
import IOSurface
import os

// MARK: - SCStreamDelegate

private class StreamDelegate: NSObject, SCStreamDelegate {
    var onStreamError: ((Error) -> Void)?

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        let nsError = error as NSError
        debugLog("SCStream stopped with error — domain: \(nsError.domain), code: \(nsError.code), description: \(nsError.localizedDescription)")
        onStreamError?(error)
    }
}

private final class WeakReference<Value: AnyObject>: @unchecked Sendable {
    weak var value: Value?

    init(_ value: Value) {
        self.value = value
    }
}

final class LatestRetainedSlot<Element>: @unchecked Sendable {
    final class Box: @unchecked Sendable {
        let value: Element

        fileprivate init(_ value: Element) {
            self.value = value
        }
    }

    private struct State {
        var latest: Box?
    }

    private let lock = OSAllocatedUnfairLock(initialState: State())

    func store(_ value: Element) {
        lock.withLock { state in
            state.latest = Box(value)
        }
    }

    func latest() -> Box? {
        lock.withLock { $0.latest }
    }

    func clear() {
        lock.withLock { state in
            state.latest = nil
        }
    }

    var retainedCount: Int {
        lock.withLock { $0.latest == nil ? 0 : 1 }
    }
}

enum CaptureReconfigurationAction: Equatable {
    case none
    case updateFrameRate
    case rebuild
}

enum CaptureReconfigurationPolicy {
    static func action(
        currentWidth: Int,
        currentHeight: Int,
        currentFrameRate: Int,
        targetWidth: Int,
        targetHeight: Int,
        targetFrameRate: Int
    ) -> CaptureReconfigurationAction {
        if currentWidth != targetWidth || currentHeight != targetHeight {
            return .rebuild
        }
        if currentFrameRate != targetFrameRate {
            return .updateFrameRate
        }
        return .none
    }
}

private final class CaptureConfigurationUpdateWaiter: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?
    private var completion: Result<Void, Error>?
    private var timeout: DispatchWorkItem?

    func install(_ continuation: CheckedContinuation<Void, Error>) {
        let completed: Result<Void, Error>?
        lock.lock()
        completed = completion
        if completed == nil {
            self.continuation = continuation
        }
        lock.unlock()
        if let completed {
            continuation.resume(with: completed)
        }
    }

    func installTimeout(_ timeout: DispatchWorkItem) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard completion == nil else { return false }
        self.timeout = timeout
        return true
    }

    func finish(_ result: Result<Void, Error>) {
        let continuation: CheckedContinuation<Void, Error>?
        let timeout: DispatchWorkItem?
        lock.lock()
        guard completion == nil else {
            lock.unlock()
            return
        }
        completion = result
        continuation = self.continuation
        self.continuation = nil
        timeout = self.timeout
        self.timeout = nil
        lock.unlock()
        timeout?.cancel()
        continuation?.resume(with: result)
    }
}

enum CaptureStreamConfigurationFactory {
    static func make(
        width: Int,
        height: Int,
        frameRate: Int,
        preservesAspectRatio: Bool
    ) -> SCStreamConfiguration {
        let configuration = SCStreamConfiguration()
        configuration.width = width
        configuration.height = height
        configuration.minimumFrameInterval = CMTime(
            value: 1,
            timescale: CMTimeScale(max(1, frameRate))
        )
        configuration.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
        configuration.showsCursor = true
        configuration.queueDepth = 2
        configuration.capturesAudio = false
        configuration.backgroundColor = .clear
        configuration.scalesToFit = true
        if preservesAspectRatio, #available(macOS 14.0, *) {
            configuration.preservesAspectRatio = true
        }
        return configuration
    }
}

// MARK: - ScreenCapture

class ScreenCapture {
    private static let liveConfigurationUpdateTimeoutSeconds: TimeInterval = 3
    private var stream: SCStream?
    private var streamOutput: StreamOutput?
    private var streamDelegate: StreamDelegate?
    private var encoder: VideoEncoder?
    private let encoderLock = NSLock()
    private var display: SCDisplay?
    private var virtualDisplayID: CGDirectDisplayID?
    private var followsMainDisplay = false
    private var refreshRate: Int = 60
    /// Optional encoded output size. This lets Telemachus capture an existing
    /// high-resolution Mac display at the tablet's native stream resolution
    /// instead of wasting latency and USB bandwidth on pixels the tablet cannot show.
    private var requestedOutputSize: (width: Int, height: Int)?

    // Thread-safe state for cross-thread access (frame output queue + main queue)
    private let stateLock = OSAllocatedUnfairLock(initialState: FrameMonitorState())

    private struct FrameMonitorState {
        var lastFrameTime: DispatchTime?
        var lastKeepaliveTime: DispatchTime?
        var hasReceivedFirstFrame = false
        var captureStatsStartTime: DispatchTime?
        var sourceFrameCount = 0
    }

    private let latestPixelBuffer = LatestRetainedSlot<CVPixelBuffer>()

    private struct KeyframeRequestState {
        var pendingEncoderCreationRequest = false
        var lastKeyframeOrReplayRequestNs: UInt64 = 0
    }
    private let keyframeRequestLock = OSAllocatedUnfairLock(initialState: KeyframeRequestState())
    private static let keyframeRequestThrottleNs: UInt64 = 500_000_000

    // Main-thread-only state
    private var frameMonitorTimer: DispatchSourceTimer?
    private var framePacingTimer: DispatchSourceTimer?
    private var restartAttempted = false
    private var isRestarting = false
    private var isHealthCheckRunning = false
    private var isStopping = false
    private var restartTask: Task<Void, Never>?
    private let streamStopBarrier = AsyncStopBarrier()
    private var streamStartTask: Task<Void, Error>?
    private var isSCStreamStarted = false

    // CGDisplayStream fallback
    private var cgDisplayStream: CGDisplayStream?
    private let fallbackLifecycle = FallbackCaptureLifecycle()

    // Streaming parameters (saved for restart)
    private weak var currentFrameSink: (any EncodedFrameSink)?
    private var currentBitrateMbps: Int = 20
    private var currentQuality: String = "medium"
    private var currentGamingBoost: Bool = false
    private var currentFrameRate: Int = 60

    // Encoding pipeline state (captured by frame handler closure)
    private var encodeQueue: DispatchQueue?

    var encoderInFlightStats: (inFlight: Int, capacity: Int) {
        guard let snapshot = currentEncoder()?.inFlightSnapshot else {
            return (inFlight: 0, capacity: 0)
        }
        return (inFlight: snapshot.inFlight, capacity: snapshot.capacity)
    }
    var encoderInFlightCount: Int { encoderInFlightStats.inFlight }
    var encoderInFlightCapacity: Int { encoderInFlightStats.capacity }

    /// Callback when capture method changes (e.g. SCStream → CGDisplayStream fallback)
    var onCaptureMethodChanged: ((String) -> Void)?
    /// Current-display mode follows a replacement Screen Sharing Virtual Display
    /// when macOS recreates it with a new CoreGraphics display ID.
    var onDisplayIDChanged: ((CGDirectDisplayID) -> Void)?
    /// Fired only after both ScreenCaptureKit restart and CGDisplayStream
    /// fallback are unavailable. Callers must stop the session or select a
    /// different online display instead of presenting a false running state.
    var onTerminalCaptureFailure: ((Error) -> Void)?

    /// Force the encoder to emit an IDR keyframe on the next frame.
    /// If the encoder hasn't been created yet (request arrived before
    /// startStreaming), the request is stored and applied at encoder init.
    func requestKeyframe() {
        if let encoder = currentEncoder() {
            encoder.requestKeyframe()
            return
        }
        keyframeRequestLock.withLock { $0.pendingEncoderCreationRequest = true }
    }

    /// Force a keyframe for the next captured frame, AND immediately re-encode
    /// the last cached frame as a forced keyframe if the display is currently
    /// idle. Without this, a client connecting during a static screen would
    /// wait up to one full GOP duration before its decoder could start.
    func requestKeyframeOrReplayCachedFrame(force: Bool = false) {
        let now = DispatchTime.now().uptimeNanoseconds
        let shouldRequest = keyframeRequestLock.withLock { state -> Bool in
            if !force,
               state.lastKeyframeOrReplayRequestNs > 0,
               now - state.lastKeyframeOrReplayRequestNs < Self.keyframeRequestThrottleNs {
                return false
            }
            state.lastKeyframeOrReplayRequestNs = now
            return true
        }
        guard shouldRequest else { return }

        requestKeyframe()

        guard let encoder = currentEncoder(), let cachedBox = latestPixelBuffer.latest() else { return }

        let pts = CMTime(
            value: CMTimeValue(DispatchTime.now().uptimeNanoseconds / 1000),
            timescale: 1_000_000
        )
        let sessionEpoch = currentFrameSink?.currentSessionEpoch ?? 0

        encodeQueue?.async {
            encoder.encode(
                pixelBuffer: cachedBox.value,
                presentationTimeStamp: pts,
                sessionEpoch: sessionEpoch
            )
        }
    }

    private func currentEncoder() -> VideoEncoder? {
        encoderLock.lock()
        defer { encoderLock.unlock() }
        return encoder
    }

    private func setCurrentEncoder(_ newEncoder: VideoEncoder?) {
        encoderLock.lock()
        encoder = newEncoder
        encoderLock.unlock()
    }

    var displayWidth: Int {
        guard let id = virtualDisplayID else { return display?.width ?? 0 }
        return ScreenCapture.physicalSize(for: id).width
    }
    var displayHeight: Int {
        guard let id = virtualDisplayID else { return display?.height ?? 0 }
        return ScreenCapture.physicalSize(for: id).height
    }

    /// Codec for the current encode session. Switching restarts the stream.
    private(set) var codec: StreamCodec = .hevc

    /// Encode dimensions for a codec: physical display pixels, clamped to the
    /// AVC decoder limit when streaming H.264. SCStream/CGDisplayStream scale
    /// the capture into this size, so no virtual-display change is needed.
    func encodeSize(for codec: StreamCodec) -> (width: Int, height: Int) {
        let phys = requestedOutputSize ?? (displayWidth, displayHeight)
        switch codec {
        case .hevc: return phys
        case .h264: return CodecLimits.clampForAvc(width: phys.0, height: phys.1)
        }
    }

    var activeCaptureFrameRate: Int { refreshRate }

    /// Returns physical pixel dimensions for a display ID.
    /// CGDisplayPixelsWide/High return logical pixels on HiDPI displays — use
    /// CGDisplayModeGetPixelWidth/Height to always get the true physical size.
    static func physicalSize(for displayID: CGDirectDisplayID) -> (width: Int, height: Int) {
        if let mode = CGDisplayCopyDisplayMode(displayID) {
            let w = mode.pixelWidth
            let h = mode.pixelHeight
            if w > 0 && h > 0 { return (w, h) }
        }
        // Mode lookup failed — falling back to logical pixels (may be stale on HiDPI display)
        debugLog("physicalSize fallback for display \(displayID) — CGDisplayCopyDisplayMode returned nil")
        return (Int(CGDisplayPixelsWide(displayID)), Int(CGDisplayPixelsHigh(displayID)))
    }

    init() async throws {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        debugLog("ScreenCapture init — macOS \(version.majorVersion).\(version.minorVersion).\(version.patchVersion)")
    }

    /// Setup screen capture for a specific virtual display
    func setupForVirtualDisplay(_ displayID: CGDirectDisplayID, refreshRate: Int = 60) async throws {
        try await setupForDisplay(displayID, refreshRate: refreshRate, followsMainDisplay: false)
    }

    /// Set up capture for any registered macOS display, including the
    /// Screen Sharing Virtual Display that macOS creates for headless sessions.
    func setupForDisplay(
        _ displayID: CGDirectDisplayID,
        refreshRate: Int = 60,
        outputSize: (width: Int, height: Int)? = nil,
        followsMainDisplay: Bool = false
    ) async throws {
        self.virtualDisplayID = displayID
        self.followsMainDisplay = followsMainDisplay
        self.refreshRate = refreshRate
        self.currentFrameRate = refreshRate
        self.requestedOutputSize = outputSize
        try await setupDisplay()
        try await setupStream()
    }

    /// Re-point an already-streaming capture at a different macOS display in
    /// place, without tearing down the streaming server or its Protocol v1
    /// session. This is the host side of a runtime display switch: the encoder
    /// is rebuilt at the new source's dimensions and the SCStream is rebuilt on
    /// the new display, but the same frame sink stays wired so media keeps
    /// flowing on one session. The caller drives the Protocol v1 epoch bump and
    /// media gating separately, so the newly captured frames are withheld until
    /// the client accepts the new VideoConfig.
    func switchCapturedDisplay(
        to displayID: CGDirectDisplayID,
        refreshRate: Int,
        outputSize: (width: Int, height: Int)?,
        followsMainDisplay: Bool,
        reportsTerminalFailure: Bool = true
    ) async throws {
        let targetFrameRate = max(1, refreshRate)
        guard currentFrameSink != nil else {
            // Not streaming yet: fall back to the plain setup path.
            try await setupForDisplay(
                displayID,
                refreshRate: targetFrameRate,
                outputSize: outputSize,
                followsMainDisplay: followsMainDisplay
            )
            return
        }

        // Internet adaptation rebuilds the stream geometry for the same live
        // display. Reuse the already validated SCDisplay in that case instead
        // of spending up to five 10-second discovery attempts inside the
        // product session's bounded host-apply window. A real display switch
        // still performs fresh discovery below.
        let reusableDisplay = virtualDisplayID == displayID ? display : nil

        isStopping = false
        // Let any in-flight restart settle before we re-point the source so the
        // two paths cannot fight over the SCStream lifecycle.
        restartTask?.cancel()
        await restartTask?.value
        restartTask = nil

        // Validate the replacement encoder before tearing down the active
        // capture surface. A rejected VideoToolbox session must leave the old
        // stream intact so Internet adaptation can soft-reject the proposal.
        let requestedSize = outputSize ?? ScreenCapture.physicalSize(for: displayID)
        let replacementSize: (width: Int, height: Int) = switch codec {
        case .hevc: requestedSize
        case .h264: CodecLimits.clampForAvc(
            width: requestedSize.width,
            height: requestedSize.height
        )
        }
        let frameSink = currentFrameSink
        let newEncoder = VideoEncoder(
            width: replacementSize.width,
            height: replacementSize.height,
            codec: codec,
            bitrateMbps: currentBitrateMbps,
            quality: currentQuality,
            gamingBoost: currentGamingBoost,
            frameRate: targetFrameRate
        )
        guard newEncoder.hasActiveCompressionSession else {
            throw NSError(
                domain: "ScreenCapture",
                code: 13,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "VideoToolbox could not create an encoder for the requested capture profile."
                ]
            )
        }
        newEncoder.onEncodedFrame = { [weak frameSink] data, timestamp, isKeyframe, sessionEpoch in
            frameSink?.sendFrame(
                data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch
            )
        }
        newEncoder.requestKeyframe()

        stopFrameMonitor()
        framePacingTimer?.cancel()
        framePacingTimer = nil
        latestPixelBuffer.clear()
        restartAttempted = false

        // Tear down the current capture surface (SCStream or CGDisplayStream)
        // before adopting the new display id.
        let previousStream = stream
        let previousStreamWasStarted = isSCStreamStarted
        isSCStreamStarted = false
        streamOutput?.onFrameReceived = nil
        setCurrentEncoder(nil)
        stream = nil
        streamOutput = nil
        streamDelegate = nil
        display = nil
        if previousStreamWasStarted {
            do {
                try await previousStream?.stopCapture()
            } catch {
                debugLog("Switch: failed to stop previous SCStream: \(error)")
            }
        }
        if fallbackLifecycle.isActive {
            invalidateFallbackCapture()
            cgDisplayStream?.stop()
            cgDisplayStream = nil
        }
        await streamStopBarrier.waitForAll()

        // Adopt the new source identity.
        self.virtualDisplayID = displayID
        self.followsMainDisplay = followsMainDisplay
        self.refreshRate = targetFrameRate
        self.currentFrameRate = targetFrameRate
        self.requestedOutputSize = outputSize
        display = reusableDisplay
        stateLock.withLock { state in
            state.lastFrameTime = nil
            state.lastKeepaliveTime = nil
            state.hasReceivedFirstFrame = false
            state.captureStatsStartTime = nil
            state.sourceFrameCount = 0
        }

        // Rebuild the encoder at the new source dimensions and rewire it to the
        // same frame sink so a single session keeps receiving media.
        setCurrentEncoder(newEncoder)

        if followsMainDisplay || CommandLine.arguments.contains("--prefer-cgdisplaystream") {
            if attemptFallbackCapture(stopSCStream: false) {
                startFrameMonitor()
                return
            }
        }

        // The old SCStream/CGDisplayStream were already stopped above. If the
        // new source fails to set up or start, mirror startStreaming's recovery
        // so the session does not end up reporting a running stream while no
        // frames are produced: try the CGDisplayStream fallback, and surface a
        // terminal failure (which drives session teardown/recovery) if that
        // also fails, instead of leaving the host silently frozen.
        do {
            if display == nil {
                try await setupDisplay()
            }
            try await setupStream()
            configureFrameHandler(label: "switch")
            currentEncoder()?.requestKeyframe()
            guard let stream else {
                throw NSError(
                    domain: "ScreenCapture",
                    code: 12,
                    userInfo: [NSLocalizedDescriptionKey: "Switched capture stream was not configured."]
                )
            }
            // Track the start so a concurrent stopStreaming() can await/cancel
            // it and we never mark the stream started or restart the frame
            // monitor after teardown has already detached the stream.
            let startTask = Task {
                try await stream.startCapture()
                self.isSCStreamStarted = true
            }
            streamStartTask = startTask
            try await startTask.value
            streamStartTask = nil
            guard !isStopping else { throw CancellationError() }
            startFrameMonitor()
        } catch is CancellationError where isStopping {
            streamStartTask = nil
            throw CancellationError()
        } catch {
            streamStartTask = nil
            debugLog("Switch: SCStream setup/start failed (\(error)) — attempting CGDisplayStream fallback")
            guard attemptFallbackCapture() else {
                if reportsTerminalFailure {
                    reportTerminalCaptureFailure(underlying: error)
                }
                throw error
            }
            startFrameMonitor()
        }
    }

    // MARK: - SCShareableContent with timeout

    private func getShareableContentWithTimeout(seconds: Int = 10) async throws -> SCShareableContent {
        try await withThrowingTaskGroup(of: SCShareableContent.self) { group in
            group.addTask {
                try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(seconds) * 1_000_000_000)
                throw NSError(domain: "ScreenCapture", code: 10,
                    userInfo: [NSLocalizedDescriptionKey: "SCShareableContent timed out after \(seconds)s (possible Apple bug FB12114396)"])
            }

            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }

    // MARK: - Display setup

    private func setupDisplay() async throws {
        guard let virtualDisplayID = virtualDisplayID else {
            throw NSError(domain: "ScreenCapture", code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Virtual display ID not set"])
        }

        for attempt in 1...5 {
            let content: SCShareableContent
            do {
                content = try await getShareableContentWithTimeout(seconds: 10)
            } catch {
                debugLog("SCShareableContent attempt \(attempt) failed: \(error.localizedDescription)")
                if attempt < 5 {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                    continue
                }
                throw error
            }

            debugLog("SCShareableContent returned \(content.displays.count) displays: \(content.displays.map { $0.displayID })")

            if let virtualDisplay = content.displays.first(where: { $0.displayID == virtualDisplayID }) {
                display = virtualDisplay
                debugLog("Capturing virtual display: \(virtualDisplay.width)x\(virtualDisplay.height) (ID: \(virtualDisplayID))")
                return
            }

            if attempt < 5 {
                debugLog("Virtual display \(virtualDisplayID) not found in attempt \(attempt), retrying...")
                try await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }

        throw NSError(domain: "ScreenCapture", code: 2,
            userInfo: [NSLocalizedDescriptionKey: "Virtual display with ID \(virtualDisplayID) not found after 5 attempts"])
    }

    // MARK: - Stream setup

    private func setupStream() async throws {
        guard let display = display, virtualDisplayID != nil else {
            throw NSError(domain: "ScreenCapture", code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Display not initialized"])
        }

        // Physical pixels for full Retina sharpness, clamped when H.264 (SCStream scales)
        let (width, height) = encodeSize(for: codec)
        let fps = refreshRate

        streamOutput = StreamOutput()

        let delegate = StreamDelegate()
        let captureReference = WeakReference(self)
        delegate.onStreamError = { streamError in
            DispatchQueue.main.async {
                guard let self = captureReference.value else { return }
                guard !self.isRestarting, !self.isStopping else { return }

                if self.followsMainDisplay {
                    let replacementID = CGMainDisplayID()
                    if replacementID != 0, replacementID != self.virtualDisplayID {
                        debugLog(
                            "Main display changed \(self.virtualDisplayID.map(String.init) ?? "none") " +
                            "→ \(replacementID); rebuilding capture"
                        )
                        self.virtualDisplayID = replacementID
                        self.onDisplayIDChanged?(replacementID)
                    } else {
                        debugLog("Current-display SCStream stopped — rebuilding capture")
                    }
                    self.restartStream()
                    return
                }

                debugLog("StreamDelegate error callback — attempting fallback")
                let alreadyActive = self.fallbackLifecycle.isActive
                if !alreadyActive {
                    if !self.attemptFallbackCapture() {
                        self.reportTerminalCaptureFailure(
                            underlying: streamError
                        )
                    }
                }
            }
        }
        streamDelegate = delegate

        let filter = SCContentFilter(display: display, excludingWindows: [])

        // Keep only the current and next frame. Deeper queues improve recording
        // resilience but directly become visible input latency for a remote display.
        // The factory is also used for live rate updates so both paths carry the
        // exact encoder/source dimensions and frame interval.
        let config = CaptureStreamConfigurationFactory.make(
            width: width,
            height: height,
            frameRate: fps,
            preservesAspectRatio: true
        )

        let scStream = SCStream(filter: filter, configuration: config, delegate: delegate)
        try scStream.addStreamOutput(streamOutput!, type: .screen, sampleHandlerQueue: .global(qos: .userInteractive))

        stream = scStream
        debugLog("Stream configured: \(width)x\(height) @ \(fps)fps (with delegate)")
    }

    // MARK: - Shared frame handler (used by both startStreaming and restartStream)

    @discardableResult
    private func recordSourceFrame(at now: DispatchTime, label: String) -> Bool {
        let (isFirst, captureStats) = stateLock.withLock { state -> (Bool, (frames: Int, elapsed: Double)?) in
            state.lastFrameTime = now
            state.sourceFrameCount += 1

            var report: (frames: Int, elapsed: Double)?
            if let start = state.captureStatsStartTime {
                let elapsed = Double(now.uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000_000
                if elapsed >= 1.0 {
                    report = (state.sourceFrameCount, elapsed)
                    state.captureStatsStartTime = now
                    state.sourceFrameCount = 0
                }
            } else {
                state.captureStatsStartTime = now
            }

            if !state.hasReceivedFirstFrame {
                state.hasReceivedFirstFrame = true
                return (true, report)
            }
            return (false, report)
        }

        if let stats = captureStats {
            let sourceFPS = Double(stats.frames) / stats.elapsed
            debugLog("Capture source (\(label)): \(String(format: "%.1f", sourceFPS))fps")
        }

        if isFirst {
            debugLog("First frame received from \(label)")
            onCaptureMethodChanged?(label)
            DispatchQueue.main.async {
                self.restartAttempted = false
            }
        }

        return isFirst
    }

    private func configureFrameHandler(label: String) {
        let queue = DispatchQueue(label: "encodeQueue.\(label)", qos: .userInteractive)
        configureFramePacer(on: queue)

        streamOutput?.onFrameReceived = { [weak self] sampleBuffer in
            guard let self = self else { return }
            autoreleasepool {
                let now = DispatchTime.now()

                self.recordSourceFrame(at: now, label: "SCStream")

                if let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) {
                    self.latestPixelBuffer.store(imageBuffer)
                }
            }
        }
    }

    /// Present the newest source buffer on a fixed output clock. Both capture
    /// APIs can occasionally omit a display tick; repeating only the latest
    /// buffer prevents that omission from becoming a 33 ms tablet presentation
    /// gap without ever building a stale-frame queue.
    private func configureFramePacer(on queue: DispatchQueue) {
        encodeQueue = queue
        framePacingTimer?.cancel()
        framePacingTimer = nil
        latestPixelBuffer.clear()
        stateLock.withLock { state in
            state.captureStatsStartTime = nil
            state.sourceFrameCount = 0
        }

        rescheduleFramePacerForCurrentRate(on: queue)
    }

    // MARK: - Start streaming

    func startStreaming(
        to frameSink: (any EncodedFrameSink)?,
        bitrateMbps: Int = 20,
        quality: String = "medium",
        gamingBoost: Bool = false,
        frameRate: Int = 60
    ) async throws {
        isStopping = false
        // Save parameters for potential restart
        currentFrameSink = frameSink
        currentBitrateMbps = bitrateMbps
        currentQuality = quality
        currentGamingBoost = gamingBoost
        currentFrameRate = frameRate

        let (width, height) = encodeSize(for: codec)

        let initialEncoder = VideoEncoder(width: width, height: height, codec: codec, bitrateMbps: bitrateMbps, quality: quality, gamingBoost: gamingBoost, frameRate: frameRate)
        initialEncoder.onEncodedFrame = { [weak frameSink] data, timestamp, isKeyframe, sessionEpoch in
            frameSink?.sendFrame(
                data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch
            )
        }
        setCurrentEncoder(initialEncoder)

        // Apply any keyframe request that arrived before the encoder existed
        let shouldForceInitialKeyframe = keyframeRequestLock.withLock { state -> Bool in
            guard state.pendingEncoderCreationRequest else { return false }
            state.pendingEncoderCreationRequest = false
            return true
        }
        if shouldForceInitialKeyframe {
            currentEncoder()?.requestKeyframe()
        }

        // Reset frame monitor state
        stateLock.withLock { state in
            state.lastFrameTime = DispatchTime.now()
            state.lastKeepaliveTime = nil
            state.hasReceivedFirstFrame = false
        }

        if followsMainDisplay || CommandLine.arguments.contains("--prefer-cgdisplaystream") {
            debugLog("Using CGDisplayStream with fixed-rate pacing for current-display capture")
            if attemptFallbackCapture(stopSCStream: false) {
                startFrameMonitor()
                return
            }
            debugLog("CGDisplayStream primary capture unavailable — using SCStream")
        }

        configureFrameHandler(label: "initial")

        do {
            guard let stream else {
                throw NSError(
                    domain: "ScreenCapture",
                    code: 11,
                    userInfo: [
                        NSLocalizedDescriptionKey: "Capture stream was not configured."
                    ]
                )
            }
            let startTask = Task {
                try await stream.startCapture()
                self.isSCStreamStarted = true
            }
            streamStartTask = startTask
            try await startTask.value
            streamStartTask = nil
            guard !isStopping else { throw CancellationError() }
            debugLog("SCStream capture started — starting frame flow monitor")
            startFrameMonitor()
        } catch is CancellationError where isStopping {
            throw CancellationError()
        } catch {
            streamStartTask = nil
            debugLog("Failed to start SCStream capture: \(error)")
            debugLog("Attempting CGDisplayStream fallback due to start failure")
            guard attemptFallbackCapture() else {
                throw error
            }
            startFrameMonitor()
        }
    }

    // MARK: - Continuous frame-flow monitor

    private func startFrameMonitor() {
        stopFrameMonitor()

        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.main)
        let monitorInterval = followsMainDisplay ? 1.0 : 3.0
        timer.schedule(deadline: .now() + monitorInterval, repeating: monitorInterval)
        timer.setEventHandler { [weak self] in
            guard let self = self else { return }

            // Screen Sharing and Computer Use can replace the virtual main
            // display without stopping the old SCStream. In that case the old
            // stream remains "healthy" and continues producing frames, but it
            // is no longer a mirror of the display the user is looking at.
            // Follow the replacement proactively instead of waiting for an
            // SCStream error that may never arrive.
            if self.followsMainDisplay {
                let currentMainDisplayID = CGMainDisplayID()
                if currentMainDisplayID != 0,
                   currentMainDisplayID != self.virtualDisplayID {
                    let wasUsingCGDisplayStream = self.fallbackLifecycle.isActive
                    debugLog(
                        "Main display changed \(self.virtualDisplayID.map(String.init) ?? "none") " +
                        "→ \(currentMainDisplayID); monitor rebuilding capture"
                    )
                    self.virtualDisplayID = currentMainDisplayID
                    self.onDisplayIDChanged?(currentMainDisplayID)
                    self.stopFrameMonitor()

                    if wasUsingCGDisplayStream {
                        self.invalidateFallbackCapture()
                        self.cgDisplayStream?.stop()
                        self.cgDisplayStream = nil
                        if self.attemptFallbackCapture(stopSCStream: false) {
                            self.currentEncoder()?.requestKeyframe()
                            self.startFrameMonitor()
                            return
                        }
                    }

                    self.restartStream()
                    return
                }
            }

            let isFallback = self.fallbackLifecycle.isActive
            guard !isFallback else {
                if !self.followsMainDisplay {
                    self.stopFrameMonitor()
                }
                return
            }

            let lastTime = self.stateLock.withLock { $0.lastFrameTime }
            let elapsed: Double
            if let last = lastTime {
                elapsed = Double(
                    DispatchTime.now().uptimeNanoseconds - last.uptimeNanoseconds
                ) / 1_000_000_000
            } else {
                elapsed = 0
            }

            let hasHadFrames = self.stateLock.withLock { $0.hasReceivedFirstFrame }

            if self.followsMainDisplay,
               hasHadFrames,
               elapsed > 1.5,
               let lastBuffer = self.latestPixelBuffer.latest() {
                // A current-display SCStream can silently stop reporting
                // changed frames while remaining attached and error-free.
                // Compare it with a one-shot capture so a genuinely idle
                // desktop stays idle, while a stale stream is rebuilt.
                self.checkCurrentDisplayCaptureHealth(against: lastBuffer)
                return
            }

            if elapsed > 5.0 {
                if hasHadFrames, let lastBuffer = self.latestPixelBuffer.latest() {
                    // Screen is idle — SCStream is healthy but not delivering frames (macOS optimization).
                    // Re-send the last captured frame as a keepalive so the tablet stays connected.
                    self.sendCachedFrameKeepaliveIfNeeded(lastBuffer)
                } else {
                    debugLog("No frames received within 5s — recovering SCStream")
                    self.stopFrameMonitor()
                    if !self.restartAttempted {
                        debugLog("Attempting SCStream restart...")
                        self.restartStream()
                    } else {
                        debugLog("Restart already attempted — falling back to CGDisplayStream")
                        if !self.attemptFallbackCapture() {
                            self.reportTerminalCaptureFailure()
                        }
                    }
                }
            }
        }
        timer.resume()
        frameMonitorTimer = timer
    }

    private func sendCachedFrameKeepaliveIfNeeded(_ pixelBuffer: LatestRetainedSlot<CVPixelBuffer>.Box) {
        let now = DispatchTime.now()
        let shouldSend = stateLock.withLock { state -> Bool in
            if let last = state.lastKeepaliveTime {
                let elapsed = Double(now.uptimeNanoseconds - last.uptimeNanoseconds) / 1_000_000_000
                if elapsed < 5.0 { return false }
            }
            state.lastKeepaliveTime = now
            return true
        }
        guard shouldSend else { return }

        debugLog("Screen idle — sending cached-frame keepalive")
        let pts = CMTime(
            value: CMTimeValue(now.uptimeNanoseconds / 1000),
            timescale: 1_000_000
        )
        encodeQueue?.async { [weak self] in
            self?.currentEncoder()?.encode(
                pixelBuffer: pixelBuffer.value,
                presentationTimeStamp: pts,
                sessionEpoch: self?.currentFrameSink?.currentSessionEpoch ?? 0
            )
        }
    }

    /// ScreenCaptureKit occasionally leaves a current-display SCStream alive
    /// but stale. A one-shot capture goes through an independent code path and
    /// lets us distinguish that failure from ScreenCaptureKit's normal
    /// "no frames for an unchanged desktop" optimization.
    private func checkCurrentDisplayCaptureHealth(against cachedBuffer: LatestRetainedSlot<CVPixelBuffer>.Box) {
        guard !isHealthCheckRunning, !isRestarting, let display else { return }

        guard #available(macOS 14.0, *) else {
            sendCachedFrameKeepaliveIfNeeded(cachedBuffer)
            return
        }

        isHealthCheckRunning = true
        let (width, height) = encodeSize(for: codec)
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.width = width
        config.height = height
        config.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
        config.showsCursor = true
        config.scalesToFit = true
        config.preservesAspectRatio = true

        SCScreenshotManager.captureSampleBuffer(
            contentFilter: filter,
            configuration: config
        ) { [weak self] sampleBuffer, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isHealthCheckRunning = false

                if let error {
                    debugLog("Current-display health snapshot failed: \(error.localizedDescription)")
                    self.sendCachedFrameKeepaliveIfNeeded(cachedBuffer)
                    return
                }

                guard let sampleBuffer,
                      let freshBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                    debugLog("Current-display health snapshot returned no pixel buffer")
                    self.sendCachedFrameKeepaliveIfNeeded(cachedBuffer)
                    return
                }

                let difference = Self.sampledLumaDifference(
                    cachedBuffer.value,
                    freshBuffer
                )
                guard difference > 0.5 else {
                    self.sendCachedFrameKeepaliveIfNeeded(cachedBuffer)
                    return
                }

                debugLog(
                    "Current-display capture is stale " +
                    "(snapshot difference \(String(format: "%.2f", difference))) — rebuilding"
                )
                self.stopFrameMonitor()
                self.restartStream()
            }
        }
    }

    /// Mean absolute luma difference over a fixed grid. Both buffers are
    /// requested in full-range NV12, so this is cheap and avoids converting a
    /// 2000×1124 frame merely to decide whether the stream is stale.
    private static func sampledLumaDifference(
        _ lhs: CVPixelBuffer,
        _ rhs: CVPixelBuffer
    ) -> Double {
        guard CVPixelBufferGetPlaneCount(lhs) > 0,
              CVPixelBufferGetPlaneCount(rhs) > 0 else {
            return .infinity
        }

        CVPixelBufferLockBaseAddress(lhs, .readOnly)
        CVPixelBufferLockBaseAddress(rhs, .readOnly)
        defer {
            CVPixelBufferUnlockBaseAddress(rhs, .readOnly)
            CVPixelBufferUnlockBaseAddress(lhs, .readOnly)
        }

        guard let lhsBase = CVPixelBufferGetBaseAddressOfPlane(lhs, 0),
              let rhsBase = CVPixelBufferGetBaseAddressOfPlane(rhs, 0) else {
            return .infinity
        }

        let lhsWidth = CVPixelBufferGetWidthOfPlane(lhs, 0)
        let lhsHeight = CVPixelBufferGetHeightOfPlane(lhs, 0)
        let rhsWidth = CVPixelBufferGetWidthOfPlane(rhs, 0)
        let rhsHeight = CVPixelBufferGetHeightOfPlane(rhs, 0)
        guard lhsWidth > 0, lhsHeight > 0, rhsWidth > 0, rhsHeight > 0 else {
            return .infinity
        }

        let lhsStride = CVPixelBufferGetBytesPerRowOfPlane(lhs, 0)
        let rhsStride = CVPixelBufferGetBytesPerRowOfPlane(rhs, 0)
        let lhsBytes = lhsBase.assumingMemoryBound(to: UInt8.self)
        let rhsBytes = rhsBase.assumingMemoryBound(to: UInt8.self)
        let columns = 96
        let rows = 54
        var totalDifference = 0

        for row in 0..<rows {
            let lhsY = min(lhsHeight - 1, row * lhsHeight / rows)
            let rhsY = min(rhsHeight - 1, row * rhsHeight / rows)
            for column in 0..<columns {
                let lhsX = min(lhsWidth - 1, column * lhsWidth / columns)
                let rhsX = min(rhsWidth - 1, column * rhsWidth / columns)
                totalDifference += abs(
                    Int(lhsBytes[lhsY * lhsStride + lhsX]) -
                    Int(rhsBytes[rhsY * rhsStride + rhsX])
                )
            }
        }

        return Double(totalDifference) / Double(columns * rows)
    }

    private func stopFrameMonitor() {
        frameMonitorTimer?.cancel()
        frameMonitorTimer = nil
    }

    // MARK: - Stream restart

    private func restartStream() {
        guard !isRestarting else { return }
        isRestarting = true
        restartAttempted = true
        stateLock.withLock { $0.hasReceivedFirstFrame = false }

        restartTask = Task { [weak self] in
            guard let self else { return }
            defer {
                self.isRestarting = false
                self.restartTask = nil
            }
            do {
                // Stop existing stream
                let previousStream = self.stream
                let previousStreamWasStarted = self.isSCStreamStarted
                self.isSCStreamStarted = false
                self.stream = nil
                self.streamOutput = nil
                self.streamDelegate = nil
                self.display = nil
                if previousStreamWasStarted {
                    try await previousStream?.stopCapture()
                }
                await self.streamStopBarrier.waitForAll()
                try Task.checkCancellation()
                guard !self.isStopping else { return }

                // Re-setup
                try await self.setupDisplay()
                try Task.checkCancellation()
                guard !self.isStopping else { return }
                try await self.setupStream()
                try Task.checkCancellation()
                guard !self.isStopping else { return }

                // Re-attach encoding pipeline using shared handler
                self.configureFrameHandler(label: "restart")
                self.currentEncoder()?.requestKeyframe()

                try await self.stream?.startCapture()
                self.isSCStreamStarted = true
                try Task.checkCancellation()
                guard !self.isStopping else { return }
                debugLog("SCStream restarted — starting frame flow monitor")
                self.startFrameMonitor()
            } catch is CancellationError {
                if !self.isStopping {
                    debugLog("SCStream restart superseded")
                }
            } catch {
                guard !self.isStopping else { return }
                debugLog("SCStream restart failed: \(error) — falling back to CGDisplayStream")
                if !self.attemptFallbackCapture() {
                    self.reportTerminalCaptureFailure(underlying: error)
                } else {
                    self.startFrameMonitor()
                }
            }
        }
    }

    private func reportTerminalCaptureFailure(underlying: Error? = nil) {
        guard !isStopping else { return }
        let error = underlying ?? NSError(
            domain: "ScreenCapture",
            code: 20,
            userInfo: [
                NSLocalizedDescriptionKey:
                    "The selected display is unavailable and both capture paths failed."
            ]
        )
        DispatchQueue.main.async { [weak self] in
            self?.onTerminalCaptureFailure?(error)
        }
    }

    // MARK: - CGDisplayStream fallback

    @discardableResult
    private func attemptFallbackCapture(stopSCStream: Bool = true) -> Bool {
        guard let displayID = virtualDisplayID else {
            debugLog("Fallback skipped — no displayID")
            return false
        }

        let fallbackGeneration: UInt64
        switch fallbackLifecycle.begin() {
        case .alreadyActive:
            debugLog("Fallback skipped — already active")
            return true
        case .started(let generation):
            fallbackGeneration = generation
        }

        if stopSCStream {
            // Detach output immediately, then retain the stop task so a host
            // teardown can await ScreenCaptureKit before creating a new stream.
            let streamToStop = stream
            let streamWasStarted = isSCStreamStarted
            isSCStreamStarted = false
            streamOutput?.onFrameReceived = nil
            stream = nil
            streamOutput = nil
            streamDelegate = nil
            if streamWasStarted {
                streamStopBarrier.enqueue {
                    do {
                        try await streamToStop?.stopCapture()
                    } catch {
                        debugLog("Failed to stop SCStream before fallback: \(error)")
                    }
                }
            }
        }

        // CGDisplayStream scales natively via outputWidth/Height, so the
        // AVC clamp applies here exactly as in the SCStream path.
        let (width, height) = encodeSize(for: codec)

        debugLog("CGDisplayStream fallback — display \(displayID) (\(width)x\(height))")

        let pixelFormat = Int32(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
        let captureQueue = DispatchQueue(
            label: "com.telemachus.cgdisplaystream.capture",
            qos: .userInteractive
        )
        let pacingQueue = DispatchQueue(
            label: "com.telemachus.cgdisplaystream.pacing",
            qos: .userInteractive
        )
        configureFramePacer(on: pacingQueue)

        guard let displayStream = CGDisplayStream(
            dispatchQueueDisplay: displayID,
            outputWidth: width,
            outputHeight: height,
            pixelFormat: pixelFormat,
            properties: nil,
            queue: captureQueue,
            handler: { [weak self] status, _, frameSurface, _ in
                guard let self else { return }
                let disposition = self.fallbackLifecycle.disposition(
                    status: status,
                    generation: fallbackGeneration,
                    hasSurface: frameSurface != nil
                )
                switch disposition {
                case .terminalFailure:
                    DispatchQueue.main.async { [weak self] in
                        guard let self, !self.isStopping,
                              self.fallbackLifecycle.claimTerminal(
                                generation: fallbackGeneration
                              ) else { return }
                        self.framePacingTimer?.cancel()
                        self.framePacingTimer = nil
                        self.latestPixelBuffer.clear()
                        self.cgDisplayStream = nil
                        self.stopFrameMonitor()
                        switch FallbackStoppedPolicy.action(
                            followsMainDisplay: self.followsMainDisplay,
                            capturedDisplayID: self.virtualDisplayID,
                            currentMainDisplayID: CGMainDisplayID()
                        ) {
                        case .rebuild(let replacementID):
                            debugLog(
                                "Fallback display stopped; following replacement " +
                                "main display \(replacementID)"
                            )
                            self.virtualDisplayID = replacementID
                            self.onDisplayIDChanged?(replacementID)
                            if self.attemptFallbackCapture(stopSCStream: false) {
                                self.currentEncoder()?.requestKeyframe()
                                self.startFrameMonitor()
                            } else {
                                self.restartStream()
                            }
                        case .terminalFailure:
                            self.reportTerminalCaptureFailure()
                        }
                    }
                    return
                case .clearFrame:
                    self.latestPixelBuffer.clear()
                    return
                case .ignore:
                    return
                case .consume:
                    break
                }
                guard let surface = frameSurface else { return }
                self.recordSourceFrame(at: DispatchTime.now(), label: "CGDisplayStream")

                var unmanagedPB: Unmanaged<CVPixelBuffer>?
                let attrs: [String: Any] = [
                    kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]
                ]
                let cvReturn = CVPixelBufferCreateWithIOSurface(
                    kCFAllocatorDefault,
                    surface,
                    attrs as CFDictionary,
                    &unmanagedPB
                )

                guard cvReturn == kCVReturnSuccess, let pb = unmanagedPB?.takeRetainedValue() else { return }
                self.latestPixelBuffer.store(pb)
            }
        ) else {
            debugLog("Failed to create CGDisplayStream — fallback unavailable")
            invalidateFallbackCapture()
            framePacingTimer?.cancel()
            framePacingTimer = nil
            return false
        }

        let startResult = displayStream.start()
        if startResult == .success {
            cgDisplayStream = displayStream
            debugLog("CGDisplayStream fallback started successfully")
            onCaptureMethodChanged?("CGDisplayStream (fallback)")
            return true
        } else {
            debugLog("CGDisplayStream.start() failed: \(startResult)")
            invalidateFallbackCapture()
            framePacingTimer?.cancel()
            framePacingTimer = nil
            return false
        }
    }

    // MARK: - Settings update

    @discardableResult
    func updateEncoderSettings(
        bitrateMbps: Int,
        quality: String,
        gamingBoost: Bool,
        frameRate: Int? = nil,
        reconfigureCaptureSource: Bool = true
    ) -> Bool {
        guard let encoder = currentEncoder() else { return false }
        guard encoder.updateSettings(
            bitrateMbps: bitrateMbps,
            quality: quality,
            gamingBoost: gamingBoost,
            frameRate: frameRate
        ) else { return false }

        currentBitrateMbps = gamingBoost ? 45 : bitrateMbps
        currentQuality = gamingBoost ? "ultralow" : quality
        currentGamingBoost = gamingBoost
        if let frameRate {
            updateActiveFrameRate(
                frameRate,
                reconfigureCaptureSource: reconfigureCaptureSource
            )
        }
        return true
    }

    /// Change the live capture frame rate in place, without rebuilding the
    /// encoder or the capture surface. The frame pacer that drives encoded FPS
    /// is rescheduled to the new rate, and an active SCStream's source interval
    /// is updated so it can deliver the new rate. A no-op when the rate is
    /// unchanged; when nothing is streaming it records the rate for the next
    /// capture without disturbing the live stream. Must be called on the main
    /// thread, including through updateEncoderSettings(frameRate:), matching the
    /// other framePacingTimer mutators.
    func updateActiveFrameRate(
        _ frameRate: Int,
        reconfigureCaptureSource: Bool = true
    ) {
        let newRate = max(1, frameRate)
        guard newRate != currentFrameRate
                || (reconfigureCaptureSource && newRate != refreshRate) else { return }
        currentFrameRate = newRate
        if reconfigureCaptureSource {
            refreshRate = newRate
        }

        // Rebuild the pacer on the main thread so framePacingTimer stays
        // main-thread-owned (like every other mutator), avoiding a race with
        // stopStreaming/setCodec. The timer still fires its event handler on the
        // encode queue via the `on: queue` argument, so pacing stays off-main.
        // The latest source buffer is preserved so the rate change does not
        // blank the stream.
        if reconfigureCaptureSource, let queue = encodeQueue {
            rescheduleFramePacerForCurrentRate(on: queue)
        }

        // Widen or narrow the SCStream source interval so the capture can
        // actually feed the new rate. CGDisplayStream fallback is driven purely
        // by the pacer, so no source update is required there.
        if reconfigureCaptureSource, let stream, isSCStreamStarted {
            let (width, height) = encodeSize(for: codec)
            let updatedConfig = CaptureStreamConfigurationFactory.make(
                width: width,
                height: height,
                frameRate: newRate,
                preservesAspectRatio: true
            )
            stream.updateConfiguration(updatedConfig) { error in
                if let error {
                    debugLog("Live frame-rate SCStream reconfiguration failed: \(error)")
                }
            }
        }
    }

    /// Applies an Internet adaptive source-rate change and waits until
    /// ScreenCaptureKit reports completion. The product session must not
    /// advertise the new FPS or start its peer-ACK deadline before this method
    /// succeeds. A short local timeout leaves enough of the session's host
    /// apply budget to restore the acknowledged rate before failing closed.
    @MainActor
    func updateInternetAdaptiveFrameRate(_ frameRate: Int) async throws {
        let newRate = max(1, frameRate)
        guard currentFrameSink != nil else {
            throw NSError(
                domain: "ScreenCapture",
                code: 14,
                userInfo: [NSLocalizedDescriptionKey: "No active capture stream is available for an adaptive frame-rate update."]
            )
        }

        if newRate == refreshRate {
            currentFrameRate = newRate
            if let queue = encodeQueue {
                rescheduleFramePacerForCurrentRate(on: queue)
            }
            return
        }

        if fallbackLifecycle.isActive {
            currentFrameRate = newRate
            refreshRate = newRate
            if let queue = encodeQueue {
                rescheduleFramePacerForCurrentRate(on: queue)
            }
            return
        }

        guard let stream, isSCStreamStarted else {
            throw NSError(
                domain: "ScreenCapture",
                code: 15,
                userInfo: [NSLocalizedDescriptionKey: "The active ScreenCaptureKit stream is not running."]
            )
        }

        let (width, height) = encodeSize(for: codec)
        let updatedConfig = CaptureStreamConfigurationFactory.make(
            width: width,
            height: height,
            frameRate: newRate,
            preservesAspectRatio: true
        )
        let waiter = CaptureConfigurationUpdateWaiter()
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                waiter.install(continuation)
                let timeout = DispatchWorkItem { [weak waiter] in
                    waiter?.finish(.failure(NSError(
                        domain: "ScreenCapture",
                        code: 16,
                        userInfo: [
                            NSLocalizedDescriptionKey:
                                "ScreenCaptureKit did not apply the adaptive frame rate within "
                                + "\(Self.liveConfigurationUpdateTimeoutSeconds) seconds."
                        ]
                    )))
                }
                if waiter.installTimeout(timeout) {
                    DispatchQueue.global(qos: .userInitiated).asyncAfter(
                        deadline: .now() + Self.liveConfigurationUpdateTimeoutSeconds,
                        execute: timeout
                    )
                    stream.updateConfiguration(updatedConfig) { [weak waiter] error in
                        if let error {
                            waiter?.finish(.failure(error))
                        } else {
                            waiter?.finish(.success(()))
                        }
                    }
                }
            }
            try Task.checkCancellation()
        }, onCancel: {
            waiter.finish(.failure(CancellationError()))
        })

        currentFrameRate = newRate
        refreshRate = newRate
        if let queue = encodeQueue {
            rescheduleFramePacerForCurrentRate(on: queue)
        }
    }

    /// Rebuild only the pacing timer at the current rate, keeping the retained
    /// latest source buffer so a rate change does not drop the visible frame.
    private func rescheduleFramePacerForCurrentRate(on queue: DispatchQueue) {
        framePacingTimer?.cancel()
        framePacingTimer = nil
        let frameIntervalNs = max(1, 1_000_000_000 / max(currentFrameRate, 1))
        let pacingTimer = DispatchSource.makeTimerSource(queue: queue)
        pacingTimer.schedule(
            deadline: .now(),
            repeating: .nanoseconds(frameIntervalNs),
            leeway: .microseconds(100)
        )
        pacingTimer.setEventHandler { [weak self] in
            guard let self,
                  let pixelBuffer = self.latestPixelBuffer.latest()?.value else {
                return
            }
            let pts = CMClockGetTime(CMClockGetHostTimeClock())
            self.currentEncoder()?.encode(
                pixelBuffer: pixelBuffer,
                presentationTimeStamp: pts,
                sessionEpoch: self.currentFrameSink?.currentSessionEpoch ?? 0
            )
        }
        pacingTimer.resume()
        framePacingTimer = pacingTimer
    }

    /// Switch the wire codec. The pacer is stopped before replacing the
    /// encoder, so a new-size encoder can never receive an old-size buffer.
    /// Whichever capture API is active is then rebuilt at the new dimensions.
    func setCodec(_ newCodec: StreamCodec) {
        guard newCodec != codec else { return }
        debugLog("Switching stream codec: \(codec) -> \(newCodec)")
        codec = newCodec

        guard currentEncoder() != nil else { return }  // not streaming yet; startStreaming will pick it up

        stopFrameMonitor()
        framePacingTimer?.cancel()
        framePacingTimer = nil
        latestPixelBuffer.clear()

        let (width, height) = encodeSize(for: newCodec)
        let frameSink = currentFrameSink
        let newEncoder = VideoEncoder(width: width, height: height, codec: newCodec, bitrateMbps: currentBitrateMbps, quality: currentQuality, gamingBoost: currentGamingBoost, frameRate: currentFrameRate)
        newEncoder.onEncodedFrame = { [weak frameSink] data, timestamp, isKeyframe, sessionEpoch in
            frameSink?.sendFrame(
                data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch
            )
        }
        newEncoder.requestKeyframe()
        setCurrentEncoder(newEncoder)

        let wasUsingCGDisplayStream = fallbackLifecycle.isActive
        if wasUsingCGDisplayStream {
            invalidateFallbackCapture()
            cgDisplayStream?.stop()
            cgDisplayStream = nil
            if attemptFallbackCapture(stopSCStream: false) {
                startFrameMonitor()
                return
            }
        }
        restartStream()
    }

    // MARK: - Stop streaming

    func stopStreaming() async {
        isStopping = true
        onTerminalCaptureFailure = nil
        // Cancel frame flow monitor
        stopFrameMonitor()
        framePacingTimer?.cancel()
        framePacingTimer = nil
        latestPixelBuffer.clear()

        restartTask?.cancel()
        await restartTask?.value
        restartTask = nil
        if let streamStartTask {
            do {
                try await streamStartTask.value
            } catch {
                if !Task.isCancelled {
                    debugLog("SCStream start ended during teardown: \(error)")
                }
            }
        }
        streamStartTask = nil
        await streamStopBarrier.waitForAll()

        // Detach references before suspension so no callback can reuse the
        // stream while ScreenCaptureKit completes teardown.
        let streamToStop = stream
        let streamWasStarted = isSCStreamStarted
        isSCStreamStarted = false
        streamOutput?.onFrameReceived = nil
        stream = nil
        streamOutput = nil
        streamDelegate = nil
        display = nil
        if streamWasStarted {
            do {
                try await streamToStop?.stopCapture()
            } catch {
                debugLog("Failed to stop SCStream capture: \(error)")
            }
        }

        // Stop CGDisplayStream fallback
        let wasFallback = fallbackLifecycle.isActive
        if wasFallback {
            invalidateFallbackCapture()
            cgDisplayStream?.stop()
            cgDisplayStream = nil
            debugLog("CGDisplayStream fallback stopped")
        }

        // Reset state
        stateLock.withLock { state in
            state.lastFrameTime = nil
            state.lastKeepaliveTime = nil
            state.hasReceivedFirstFrame = false
            state.captureStatsStartTime = nil
            state.sourceFrameCount = 0
        }
        restartAttempted = false
        isRestarting = false
        isHealthCheckRunning = false
        currentFrameSink = nil
    }

    private func invalidateFallbackCapture() {
        fallbackLifecycle.invalidate()
    }
}

// MARK: - StreamOutput

class StreamOutput: NSObject, SCStreamOutput {
    var onFrameReceived: ((CMSampleBuffer) -> Void)?

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { return }
        onFrameReceived?(sampleBuffer)
    }
}
