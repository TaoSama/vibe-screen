import Foundation
import VideoToolbox
import CoreMedia
import os

final class VideoEncoderInFlightAdmission {
    enum SubmissionResult: Equatable {
        case submitted(OSStatus)
        case atCapacity
        case invalidated
    }

    final class Lease {
        private let lock = NSLock()
        private weak var admission: VideoEncoderInFlightAdmission?
        private var identifier: UInt64?

        fileprivate init(admission: VideoEncoderInFlightAdmission, identifier: UInt64) {
            self.admission = admission
            self.identifier = identifier
        }

        func release() {
            lock.lock()
            let identifier = self.identifier
            self.identifier = nil
            let admission = self.admission
            self.admission = nil
            lock.unlock()

            if let identifier {
                admission?.release(identifier)
            }
        }

        deinit {
            release()
        }
    }

    private struct State {
        var nextIdentifier: UInt64 = 0
        var activeIdentifiers: Set<UInt64> = []
        var invalidated = false
    }

    private let capacity: Int
    private let lock = NSLock()
    private var state = State()

    init(capacity: Int) {
        precondition(capacity > 0)
        self.capacity = capacity
    }

    func submit(_ submission: (Lease) -> OSStatus) -> SubmissionResult {
        let lease: Lease
        lock.lock()
        if state.invalidated {
            lock.unlock()
            return .invalidated
        }
        guard state.activeIdentifiers.count < capacity else {
            lock.unlock()
            return .atCapacity
        }
        state.nextIdentifier &+= 1
        let identifier = state.nextIdentifier
        state.activeIdentifiers.insert(identifier)
        lease = Lease(admission: self, identifier: identifier)
        lock.unlock()

        let status = submission(lease)
        if status != noErr {
            lease.release()
        }
        return .submitted(status)
    }

    func invalidate() {
        lock.lock()
        state.invalidated = true
        state.activeIdentifiers.removeAll(keepingCapacity: false)
        lock.unlock()
    }

    var inFlightCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return state.activeIdentifiers.count
    }

    private func release(_ identifier: UInt64) {
        lock.lock()
        state.activeIdentifiers.remove(identifier)
        lock.unlock()
    }
}

final class VideoEncoderCallbackOwner {
    private let lock = NSLock()
    private weak var encoder: VideoEncoder?
    private var active = false

    func activate(_ encoder: VideoEncoder) {
        lock.lock()
        self.encoder = encoder
        active = true
        lock.unlock()
    }

    func deactivate() {
        lock.lock()
        active = false
        encoder = nil
        lock.unlock()
    }

    func claimEncoder() -> VideoEncoder? {
        lock.lock()
        defer { lock.unlock() }
        return active ? encoder : nil
    }
}

final class VideoEncoderFrameRegistry {
    struct ClaimedFrame {
        let context: VideoEncoder.FrameContext
        let owner: VideoEncoderCallbackOwner
    }

    private struct Entry {
        let context: Unmanaged<VideoEncoder.FrameContext>
        let owner: VideoEncoderCallbackOwner
    }

    static let shared = VideoEncoderFrameRegistry()

    private let lock = NSLock()
    private var nextTicket: UInt = 0
    private var entries: [UInt: Entry] = [:]
    private var ticketsByOwner: [ObjectIdentifier: Set<UInt>] = [:]

    func register(
        _ context: VideoEncoder.FrameContext,
        owner: VideoEncoderCallbackOwner
    ) -> UnsafeMutableRawPointer {
        lock.lock()
        repeat {
            nextTicket &+= 1
        } while nextTicket == 0 || entries[nextTicket] != nil
        let ticket = nextTicket
        entries[ticket] = Entry(
            context: Unmanaged.passRetained(context),
            owner: owner
        )
        ticketsByOwner[ObjectIdentifier(owner), default: []].insert(ticket)
        lock.unlock()

        return UnsafeMutableRawPointer(bitPattern: ticket)!
    }

    func claim(_ sourceFrameRefcon: UnsafeMutableRawPointer?) -> ClaimedFrame? {
        guard let sourceFrameRefcon else { return nil }
        let ticket = UInt(bitPattern: sourceFrameRefcon)

        lock.lock()
        guard let entry = removeEntry(ticket: ticket) else {
            lock.unlock()
            return nil
        }
        lock.unlock()

        return ClaimedFrame(
            context: entry.context.takeRetainedValue(),
            owner: entry.owner
        )
    }

    @discardableResult
    func drain(owner: VideoEncoderCallbackOwner) -> Int {
        let ownerIdentifier = ObjectIdentifier(owner)
        lock.lock()
        let tickets = ticketsByOwner.removeValue(forKey: ownerIdentifier) ?? []
        let drainedEntries = tickets.compactMap { entries.removeValue(forKey: $0) }
        lock.unlock()

        for entry in drainedEntries {
            let context = entry.context.takeRetainedValue()
            context.completeSubmission()
        }
        return drainedEntries.count
    }

    var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return entries.count
    }

    private func removeEntry(ticket: UInt) -> Entry? {
        guard let entry = entries.removeValue(forKey: ticket) else { return nil }
        let ownerIdentifier = ObjectIdentifier(entry.owner)
        ticketsByOwner[ownerIdentifier]?.remove(ticket)
        if ticketsByOwner[ownerIdentifier]?.isEmpty == true {
            ticketsByOwner.removeValue(forKey: ownerIdentifier)
        }
        return entry
    }
}

class VideoEncoder {
    final class FrameContext {
        let timestamp: UInt64
        let sessionEpoch: UInt64
        private let admissionLease: VideoEncoderInFlightAdmission.Lease

        init(
            timestamp: UInt64,
            sessionEpoch: UInt64,
            admissionLease: VideoEncoderInFlightAdmission.Lease
        ) {
            self.timestamp = timestamp
            self.sessionEpoch = sessionEpoch
            self.admissionLease = admissionLease
        }

        func completeSubmission() {
            admissionLease.release()
        }
    }
    private struct EncoderState {
        var pendingForceKeyframe = false
    }

    private var compressionSession: VTCompressionSession?
    var onEncodedFrame: ((Data, UInt64, Bool, UInt64) -> Void)?
    private var width: Int
    private var height: Int
    let codec: StreamCodec
    private var bitrateMbps: Int = 20
    private var quality: String = "medium"
    private var gamingBoost: Bool = false
    private var frameRate: Int = 60
    private let sessionLock = NSLock()
    private let stateLock = OSAllocatedUnfairLock(initialState: EncoderState())
    private let inFlightAdmission = VideoEncoderInFlightAdmission(capacity: 2)
    private let callbackOwner = VideoEncoderCallbackOwner()

    var hasActiveCompressionSession: Bool {
        sessionLock.lock()
        defer { sessionLock.unlock() }
        return compressionSession != nil
    }

    init(width: Int, height: Int, codec: StreamCodec = .hevc, bitrateMbps: Int = 20, quality: String = "ultralow", gamingBoost: Bool = false, frameRate: Int = 60) {
        self.width = width
        self.height = height
        self.codec = codec
        self.bitrateMbps = gamingBoost ? 45 : bitrateMbps
        self.quality = gamingBoost ? "ultralow" : quality
        self.gamingBoost = gamingBoost
        self.frameRate = frameRate
        callbackOwner.activate(self)
        setupCompressionSession()
    }

    /// Applies live encoder preferences without invalidating the compression
    /// session. These VideoToolbox properties are explicitly read/write, so a
    /// decoder restart is unnecessary and would race the active frame submitter.
    @discardableResult
    func updateSettings(
        bitrateMbps: Int,
        quality: String,
        gamingBoost: Bool,
        frameRate: Int? = nil
    ) -> Bool {
        let updatedBitrate = gamingBoost ? 45 : bitrateMbps
        let updatedQuality = gamingBoost ? "ultralow" : quality

        sessionLock.lock()
        defer { sessionLock.unlock() }
        let updatedFrameRate = max(1, frameRate ?? self.frameRate)

        guard let session = compressionSession else {
            debugLog("VideoToolbox encoder settings rejected: no active compression session")
            return false
        }
        guard updatedBitrate != self.bitrateMbps
                || updatedQuality != self.quality
                || gamingBoost != self.gamingBoost
                || updatedFrameRate != self.frameRate else {
            return true
        }

        var appliedRollbacks: [(CFString, CFTypeRef)] = []
        func apply(_ key: CFString, value: CFTypeRef, rollbackValue: CFTypeRef) -> Bool {
            let status = VTSessionSetProperty(session, key: key, value: value)
            guard status == noErr else {
                for (rollbackKey, rollbackValue) in appliedRollbacks.reversed() {
                    let rollbackStatus = VTSessionSetProperty(
                        session,
                        key: rollbackKey,
                        value: rollbackValue
                    )
                    if rollbackStatus != noErr {
                        debugLog("VideoToolbox encoder settings rollback failed: \(rollbackStatus)")
                    }
                }
                debugLog("VideoToolbox encoder settings rejected for \(key): \(status)")
                return false
            }
            appliedRollbacks.append((key, rollbackValue))
            return true
        }

        if updatedBitrate != self.bitrateMbps {
            guard apply(
                kVTCompressionPropertyKey_AverageBitRate,
                value: (updatedBitrate * 1_000_000) as CFNumber,
                rollbackValue: (self.bitrateMbps * 1_000_000) as CFNumber
            ) else { return false }
        }
        if updatedQuality != self.quality || gamingBoost != self.gamingBoost {
            guard apply(
                kVTCompressionPropertyKey_Quality,
                value: Self.qualityValue(for: updatedQuality, gamingBoost: gamingBoost) as CFNumber,
                rollbackValue: Self.qualityValue(for: self.quality, gamingBoost: self.gamingBoost) as CFNumber
            ) else { return false }
        }
        if updatedFrameRate != self.frameRate {
            guard apply(
                kVTCompressionPropertyKey_ExpectedFrameRate,
                value: updatedFrameRate as CFNumber,
                rollbackValue: self.frameRate as CFNumber
            ), apply(
                kVTCompressionPropertyKey_MaxKeyFrameInterval,
                value: updatedFrameRate as CFNumber,
                rollbackValue: self.frameRate as CFNumber
            ) else { return false }
        }

        self.bitrateMbps = updatedBitrate
        self.quality = updatedQuality
        self.gamingBoost = gamingBoost
        self.frameRate = updatedFrameRate
        stateLock.withLock { $0.pendingForceKeyframe = true }

        let mode = gamingBoost ? "GAMING BOOST" : updatedQuality.uppercased()
        debugLog(
            "VideoToolbox encoder updated in place "
                + "(\(updatedBitrate)Mbps, \(updatedFrameRate)fps, \(mode))"
        )
        return true
    }

    private func setupCompressionSession() {
        var session: VTCompressionSession?

        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: Int32(width),
            height: Int32(height),
            codecType: codec == .hevc ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264,
            encoderSpecification: [kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder: true] as CFDictionary,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: encodingOutputCallback,
            refcon: Unmanaged.passUnretained(VideoEncoderFrameRegistry.shared).toOpaque(),
            compressionSessionOut: &session
        )

        guard status == noErr, let session = session else {
            debugLog("Failed to create compression session: \(status)")
            return
        }

        compressionSession = session

        // Ultra-low latency config for real-time streaming
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        // H.264 Main profile: decodable by every AVC hardware decoder
        // (Baseline/Main/High all accept Main-constrained streams' feature
        // set we use). High adds 8x8 transform that some low-end vendor OMX
        // decoders reject — not worth the marginal gain for screen content.
        let profile: CFString = codec == .hevc
            ? kVTProfileLevel_HEVC_Main_AutoLevel
            : kVTProfileLevel_H264_Main_AutoLevel
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ProfileLevel, value: profile)

        // The target SM-P610 has a USB-C connector but only a USB 2.0 data link.
        // Respect the configured bitrate instead of silently forcing 60 Mbps.
        // HEVC desktop content remains sharp at 25-50 Mbps and leaves ample room
        // for ADB framing bursts on a 480 Mbps signalling link.
        let effectiveBitrate = gamingBoost ? 45 : bitrateMbps
        let bitrateBps = effectiveBitrate * 1_000_000
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AverageBitRate, value: bitrateBps as CFNumber)
        // Removed DataRateLimits - was causing bursty traffic and buffer stalls

        // Frame rate settings
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: frameRate as CFNumber)

        // Short-GOP IPP: 1 keyframe per second, P-frames in between.
        // All-intra (every frame keyframe) was producing 3-5x more data than needed,
        // saturating tablet decode/compose pipeline at high panel resolutions and
        // starving Mac WindowServer with encoder load. Short-GOP IPP gives 99% of
        // the resilience (frame loss recovery within 1 second) at a fraction of
        // the per-frame cost. TCP over USB-C rarely drops, so 1s GOP is safe.
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: frameRate as CFNumber)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration, value: 1.0 as CFNumber)

        // Critical for low latency - NO frame reordering (no B-frames)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse)

        // ALWAYS zero frame delay for real-time streaming (not just gaming boost)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxFrameDelayCount, value: 0 as CFNumber)

        // Quality based on preset
        let qualityValue = Self.qualityValue(for: quality, gamingBoost: gamingBoost)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_Quality, value: qualityValue as CFNumber)

        // Use VBR (variable bitrate) instead of CBR for burst capacity during fast scene changes
        // CBR causes over-quantization (blocky artifacts) when scene complexity spikes
        // Removed: kVTCompressionPropertyKey_ConstantBitRate

        VTCompressionSessionPrepareToEncodeFrames(session)

        let mode = gamingBoost ? "🎮 GAMING BOOST" : quality.uppercased()
        debugLog("VideoToolbox encoder configured (\(codec == .hevc ? "H.265" : "H.264"), \(bitrateMbps)Mbps, \(frameRate)fps, \(mode))")
    }

    private static func qualityValue(for quality: String, gamingBoost: Bool) -> Float {
        if gamingBoost { return 0.3 }
        return switch quality {
        case "ultralow": 0.5
        case "low": 0.65
        case "medium": 0.8
        case "high": 0.9
        default: 0.5
        }
    }

    /// Force the next encoded frame to be an IDR (sync) frame.
    /// Used when a fresh client connects so its decoder can start immediately
    /// instead of waiting up to one full GOP for the next scheduled keyframe.
    func requestKeyframe() {
        stateLock.withLock { $0.pendingForceKeyframe = true }
    }

    func encode(
        pixelBuffer: CVPixelBuffer,
        presentationTimeStamp: CMTime,
        sessionEpoch: UInt64
    ) {
        sessionLock.lock()
        guard let session = compressionSession else {
            sessionLock.unlock()
            return
        }

        let duration = CMTime(value: 1, timescale: CMTimeScale(frameRate))

        // Use system uptime clock — MUST match DispatchTime.now().uptimeNanoseconds
        let captureNanos = DispatchTime.now().uptimeNanoseconds
        var sourceFrameRefcon: UnsafeMutableRawPointer?
        let submissionResult = inFlightAdmission.submit { admissionLease in
            let shouldForceKeyframe = stateLock.withLock { state -> Bool in
                guard state.pendingForceKeyframe else { return false }
                state.pendingForceKeyframe = false
                return true
            }
            let frameProperties: CFDictionary? = shouldForceKeyframe
                ? [kVTEncodeFrameOptionKey_ForceKeyFrame: true] as CFDictionary
                : nil
            let context = FrameContext(
                timestamp: captureNanos,
                sessionEpoch: sessionEpoch,
                admissionLease: admissionLease
            )
            let registeredRefcon = VideoEncoderFrameRegistry.shared.register(
                context,
                owner: callbackOwner
            )
            sourceFrameRefcon = registeredRefcon
            return VTCompressionSessionEncodeFrame(
                session,
                imageBuffer: pixelBuffer,
                presentationTimeStamp: presentationTimeStamp,
                duration: duration,
                frameProperties: frameProperties,
                sourceFrameRefcon: registeredRefcon,
                infoFlagsOut: nil
            )
        }
        sessionLock.unlock()
        if case .submitted(let encodeStatus) = submissionResult, encodeStatus != noErr {
            // VideoToolbox does not invoke the output callback when submission
            // itself fails, so ownership of the retained context remains here.
            if let claimedFrame = VideoEncoderFrameRegistry.shared.claim(sourceFrameRefcon) {
                claimedFrame.context.completeSubmission()
            }
            debugLog("VideoToolbox frame submission failed: \(encodeStatus)")
        }
    }

    deinit {
        invalidate()
    }

    func invalidate() {
        sessionLock.lock()
        callbackOwner.deactivate()
        if let session = compressionSession {
            let completeStatus = VTCompressionSessionCompleteFrames(
                session,
                untilPresentationTimeStamp: .invalid
            )
            if completeStatus != noErr {
                debugLog("VideoToolbox frame completion failed: \(completeStatus)")
            }
            VideoEncoderFrameRegistry.shared.drain(owner: callbackOwner)
            VTCompressionSessionInvalidate(session)
            compressionSession = nil
        } else {
            VideoEncoderFrameRegistry.shared.drain(owner: callbackOwner)
        }
        inFlightAdmission.invalidate()
        sessionLock.unlock()
    }
}

// Static start code to avoid repeated allocations
private let nalStartCode: [UInt8] = [0, 0, 0, 1]

private let encodingOutputCallback: VTCompressionOutputCallback = { (outputCallbackRefCon, sourceFrameRefCon, status, _, sampleBuffer) in
    guard let outputCallbackRefCon else { return }
    let registry = Unmanaged<VideoEncoderFrameRegistry>
        .fromOpaque(outputCallbackRefCon)
        .takeUnretainedValue()
    guard let claimedFrame = registry.claim(sourceFrameRefCon) else {
        return
    }
    claimedFrame.context.completeSubmission()

    guard status == noErr,
          let sampleBuffer = sampleBuffer else {
        if status != noErr {
            debugLog("VideoToolbox encode callback failed: \(status)")
        }
        return
    }

    guard let encoder = claimedFrame.owner.claimEncoder() else { return }
    let timestamp = claimedFrame.context.timestamp
    let sessionEpoch = claimedFrame.context.sessionEpoch

    // Extract encoded data
    guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

    var lengthAtOffset: Int = 0
    var totalLength: Int = 0
    var dataPointer: UnsafeMutablePointer<Int8>?

    let statusCode = CMBlockBufferGetDataPointer(
        dataBuffer,
        atOffset: 0,
        lengthAtOffsetOut: &lengthAtOffset,
        totalLengthOut: &totalLength,
        dataPointerOut: &dataPointer
    )

    guard statusCode == kCMBlockBufferNoErr,
          let dataPointer = dataPointer else {
        return
    }

    // Check if this is a keyframe
    let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[CFString: Any]]
    let isKeyframe = !(attachments?.first?[kCMSampleAttachmentKey_NotSync] as? Bool ?? false)

    // Pre-allocate estimated size to reduce reallocations
    let estimatedSize = totalLength + (isKeyframe ? 256 : 0) + 32
    var frameData = Data(capacity: estimatedSize)

    if isKeyframe {
        if let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer) {
            // Prepend parameter sets: VPS/SPS/PPS for HEVC, SPS/PPS for H.264.
            var parameterSetCount: Int = 0
            let countStatus: OSStatus
            if encoder.codec == .hevc {
                countStatus = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(formatDescription, parameterSetIndex: 0, parameterSetPointerOut: nil, parameterSetSizeOut: nil, parameterSetCountOut: &parameterSetCount, nalUnitHeaderLengthOut: nil)
            } else {
                countStatus = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(formatDescription, parameterSetIndex: 0, parameterSetPointerOut: nil, parameterSetSizeOut: nil, parameterSetCountOut: &parameterSetCount, nalUnitHeaderLengthOut: nil)
            }
            if countStatus != noErr {
                debugLog("Parameter set count query failed: \(countStatus) — keyframe sent without SPS/PPS")
                parameterSetCount = 0
            }

            for i in 0..<parameterSetCount {
                var parameterSetPointer: UnsafePointer<UInt8>?
                var parameterSetSize: Int = 0
                if encoder.codec == .hevc {
                    CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(formatDescription, parameterSetIndex: i, parameterSetPointerOut: &parameterSetPointer, parameterSetSizeOut: &parameterSetSize, parameterSetCountOut: nil, nalUnitHeaderLengthOut: nil)
                } else {
                    CMVideoFormatDescriptionGetH264ParameterSetAtIndex(formatDescription, parameterSetIndex: i, parameterSetPointerOut: &parameterSetPointer, parameterSetSizeOut: &parameterSetSize, parameterSetCountOut: nil, nalUnitHeaderLengthOut: nil)
                }

                if let pointer = parameterSetPointer {
                    frameData.append(contentsOf: nalStartCode)
                    frameData.append(pointer, count: parameterSetSize)
                }
            }
        }
    }

    // Convert length-prefixed NAL units to Annex-B format (start codes)
    var offset = 0
    while offset < totalLength {
        // Read 4-byte length
        var nalLength: UInt32 = 0
        memcpy(&nalLength, dataPointer.advanced(by: offset), 4)
        nalLength = UInt32(bigEndian: nalLength)
        offset += 4

        // Add start code and NAL unit data
        frameData.append(contentsOf: nalStartCode)
        let nalPointer = UnsafeRawPointer(dataPointer.advanced(by: offset))
        frameData.append(nalPointer.assumingMemoryBound(to: UInt8.self), count: Int(nalLength))
        offset += Int(nalLength)
    }

    encoder.onEncodedFrame?(frameData, timestamp, isKeyframe, sessionEpoch)
}
