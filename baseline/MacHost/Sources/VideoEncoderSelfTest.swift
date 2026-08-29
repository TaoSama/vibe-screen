import CoreMedia
import CoreVideo
import Foundation
import VideoToolbox

enum VideoEncoderSelfTest {
    private static let width = 640
    private static let height = 480
    private static let warmupFrameCount = 4
    private static let frameCount = 120
    private static let settingsUpdateCount = 24
    private static let warmupTimeout: TimeInterval = 8
    private static let warmupPollInterval: TimeInterval = 0.05
    private static let warmupDrainDelay: TimeInterval = 0.5

    private final class ResultState: @unchecked Sendable {
        private let lock = NSLock()
        private var settingsFailure: String?
        private var encodedFrameCount = 0

        func recordSettingsFailure(_ failure: String) {
            lock.lock()
            if settingsFailure == nil {
                settingsFailure = failure
            }
            lock.unlock()
        }

        func recordEncodedFrame() {
            lock.lock()
            encodedFrameCount += 1
            lock.unlock()
        }

        func snapshot() -> (settingsFailure: String?, encodedFrameCount: Int) {
            lock.lock()
            defer { lock.unlock() }
            return (settingsFailure, encodedFrameCount)
        }
    }

    static func run() -> Bool {
        guard sdrColorMetadataIsPinned() else {
            FileHandle.standardError.write(Data("video encoder self-test: SDR color metadata drifted\n".utf8))
            return false
        }

        guard runKeyframeRecoveryStateChecks() else { return false }

        guard let pixelBuffer = makePixelBuffer() else {
            FileHandle.standardError.write(Data("video encoder self-test: pixel buffer creation failed\n".utf8))
            return false
        }

        let encoder = VideoEncoder(
            width: width,
            height: height,
            codec: .h264,
            bitrateMbps: 20,
            quality: "medium",
            frameRate: 60
        )
        guard encoder.hasActiveCompressionSession else {
            FileHandle.standardError.write(Data("video encoder self-test: H.264 compression session unavailable\n".utf8))
            return false
        }
        let group = DispatchGroup()
        let encodeQueue = DispatchQueue(label: "dev.vibescreen.encoder-self-test.frames")
        let settingsQueue = DispatchQueue(label: "dev.vibescreen.encoder-self-test.settings")
        let result = ResultState()
        encoder.onEncodedFrame = { _, _, _, _ in result.recordEncodedFrame() }
        encoder.requestKeyframe()

        let warmup = WarmupPump(
            frameCount: warmupFrameCount,
            timeout: warmupTimeout,
            pollInterval: warmupPollInterval,
            drainDelay: warmupDrainDelay
        )
        let warmupResult = warmup.run(
            availableCapacity: {
                let snapshot = encoder.inFlightSnapshot
                return max(0, snapshot.capacity - snapshot.inFlight)
            },
            callbackCount: { result.snapshot().encodedFrameCount },
            submitFrame: { index in
                encoder.encode(
                    pixelBuffer: pixelBuffer,
                    presentationTimeStamp: CMTime(value: CMTimeValue(index), timescale: 60),
                    sessionEpoch: 1
                )
            },
            completeFrames: { encoder.completeFrames() },
            drainFrames: { encoder.drainPendingFramesForSelfTest() },
            sleep: Thread.sleep(forTimeInterval:)
        )

        guard warmupResult.completionStatus == noErr else {
            FileHandle.standardError.write(Data(
                "video encoder self-test failed: warmup frame completion failed "
                    .appending("(status=\(warmupResult.completionStatus), ")
                    .appending("submitted=\(warmupResult.submittedFrames), ")
                    .appending("drained=\(warmupResult.drainedFrames), ")
                    .appending("callbacks=\(warmupResult.callbacks))\n")
                    .utf8
            ))
            return false
        }

        guard warmupResult.observedEncodedFrame else {
            let snapshot = result.snapshot()
            FileHandle.standardError.write(Data(
                "video encoder self-test failed: warmup produced no encoded callbacks "
                    .appending("(submitted=\(warmupResult.submittedFrames), ")
                    .appending("drained=\(warmupResult.drainedFrames), ")
                    .appending("callbacks=\(snapshot.encodedFrameCount))\n")
                    .utf8
            ))
            return false
        }
        let warmupSnapshot = result.snapshot()

        group.enter()
        encodeQueue.async {
            defer { group.leave() }
            let firstStreamFrameIndex = warmupResult.submittedFrames
            for index in firstStreamFrameIndex..<(firstStreamFrameIndex + frameCount) {
                encoder.encode(
                    pixelBuffer: pixelBuffer,
                    presentationTimeStamp: CMTime(value: CMTimeValue(index), timescale: 60),
                    sessionEpoch: 1
                )
                Thread.sleep(forTimeInterval: 1.0 / 120.0)
            }
        }

        group.enter()
        settingsQueue.async {
            defer { group.leave() }
            for index in 0..<settingsUpdateCount {
                let sharp = index.isMultiple(of: 2)
                let bitrateMbps = sharp ? 35 : 12
                let quality = sharp ? "high" : "low"
                let frameRate = sharp ? 60 : 30
                let succeeded = encoder.updateSettings(
                    bitrateMbps: bitrateMbps,
                    quality: quality,
                    gamingBoost: false,
                    frameRate: frameRate
                )
                if !succeeded {
                    let detail = encoder.settingsUpdateFailureDescription
                        .map { " (\($0))" } ?? ""
                    result.recordSettingsFailure(
                        "update #\(index + 1) rejected "
                            + "(bitrate=\(bitrateMbps)Mbps, quality=\(quality), fps=\(frameRate))"
                            + detail
                    )
                    return
                }
            }
        }

        guard group.wait(timeout: .now() + 15) == .success else {
            FileHandle.standardError.write(Data("video encoder self-test: concurrent work timed out\n".utf8))
            return false
        }

        let completionStatus = encoder.completeFrames()
        guard completionStatus == noErr else {
            FileHandle.standardError.write(Data(
                "video encoder self-test failed: frame completion failed "
                    .appending("(status=\(completionStatus), callbacks=\(result.snapshot().encodedFrameCount))\n")
                    .utf8
            ))
            return false
        }
        _ = waitForEncodedFrameCount(warmupSnapshot.encodedFrameCount + 1, in: result, timeout: 5)
        let snapshot = result.snapshot()
        let passed = snapshot.settingsFailure == nil
            && snapshot.encodedFrameCount > warmupSnapshot.encodedFrameCount
        if passed {
            print(
                "video encoder self-test passed "
                    + "(warmup callbacks: \(warmupSnapshot.encodedFrameCount), "
                    + "encoded callbacks: \(snapshot.encodedFrameCount), "
                    + "settings updates: \(settingsUpdateCount))"
            )
        } else {
            let failure = snapshot.settingsFailure.map {
                "VideoToolbox property update rejected after warmup: \($0)"
            } ?? "no encoded callbacks after settings updates"
            FileHandle.standardError.write(Data(
                "video encoder self-test failed: \(failure) "
                    .appending("(callbacks=\(snapshot.encodedFrameCount))\n")
                    .utf8
            ))
        }
        return passed
    }

    private static func waitForEncodedFrameCount(
        _ expectedCount: Int,
        in result: ResultState,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while result.snapshot().encodedFrameCount < expectedCount, Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        return result.snapshot().encodedFrameCount >= expectedCount
    }

    struct WarmupPump {
        struct Result: Equatable {
            let submittedFrames: Int
            let drainedFrames: Int
            let callbacks: Int
            let completionStatus: OSStatus

            var observedEncodedFrame: Bool { callbacks > 0 }
        }

        let frameCount: Int
        let timeout: TimeInterval
        let pollInterval: TimeInterval
        let drainDelay: TimeInterval

        func run(
            availableCapacity: () -> Int,
            callbackCount: () -> Int,
            submitFrame: (Int) -> Void,
            completeFrames: () -> OSStatus,
            drainFrames: () -> Int,
            sleep: (TimeInterval) -> Void,
            now: () -> Date = Date.init
        ) -> Result {
            precondition(drainDelay >= 0)
            let deadline = now().addingTimeInterval(timeout)
            var submittedFrames = 0
            var drainedFrames = 0
            var completionStatus: OSStatus = noErr
            var capacityFullSince: Date?

            while now() < deadline, callbackCount() == 0 {
                var submittedThisPass = false
                while submittedFrames < frameCount, availableCapacity() > 0 {
                    submitFrame(submittedFrames)
                    submittedFrames += 1
                    submittedThisPass = true
                    capacityFullSince = nil
                }

                if submittedThisPass {
                    sleep(pollInterval)
                    if callbackCount() > 0 {
                        break
                    }
                }

                completionStatus = completeFrames()
                if completionStatus != noErr {
                    break
                }
                if callbackCount() > 0 {
                    break
                }
                if availableCapacity() == 0 {
                    let currentTime = now()
                    if capacityFullSince == nil {
                        capacityFullSince = currentTime
                    }
                    if let fullSince = capacityFullSince,
                       currentTime.timeIntervalSince(fullSince) >= drainDelay {
                        drainedFrames += drainFrames()
                        capacityFullSince = nil
                    }
                } else {
                    capacityFullSince = nil
                }
                sleep(pollInterval)
            }

            return Result(
                submittedFrames: submittedFrames,
                drainedFrames: drainedFrames,
                callbacks: callbackCount(),
                completionStatus: completionStatus
            )
        }
    }

    private static func sdrColorMetadataIsPinned() -> Bool {
        let properties = Dictionary(
            uniqueKeysWithValues: VideoEncoderSDRColorMetadata.compressionProperties.map { property in
                (property.key as String, property.value as Any)
            }
        )
        return properties[kVTCompressionPropertyKey_ColorPrimaries as String] as? String
            == kCMFormatDescriptionColorPrimaries_ITU_R_709_2 as String
            && properties[kVTCompressionPropertyKey_TransferFunction as String] as? String
                == kCMFormatDescriptionTransferFunction_ITU_R_709_2 as String
            && properties[kVTCompressionPropertyKey_YCbCrMatrix as String] as? String
                == kCMFormatDescriptionYCbCrMatrix_ITU_R_709_2 as String
            && (properties[kVTCompressionPropertyKey_OutputBitDepth as String] as? NSNumber)?.intValue == 8
            && properties[kVTCompressionPropertyKey_HDRMetadataInsertionMode as String] as? String
                == kVTHDRMetadataInsertionMode_None as String
    }

    private static func runKeyframeRecoveryStateChecks() -> Bool {
        let keyframeRequests = VideoEncoderKeyframeRequests()
        keyframeRequests.request()
        guard keyframeRequests.consumePendingRequest() else {
            FileHandle.standardError.write(Data("video encoder self-test: keyframe request was not consumed\n".utf8))
            return false
        }
        guard !keyframeRequests.isPending else {
            FileHandle.standardError.write(Data("video encoder self-test: consumed keyframe request stayed pending\n".utf8))
            return false
        }
        keyframeRequests.restoreAfterSynchronousFailure(consumedRequest: true)
        guard keyframeRequests.isPending else {
            FileHandle.standardError.write(Data("video encoder self-test: consumed keyframe request was not restored\n".utf8))
            return false
        }
        guard keyframeRequests.consumePendingRequest() else {
            FileHandle.standardError.write(Data("video encoder self-test: restored keyframe request was not consumable\n".utf8))
            return false
        }
        keyframeRequests.restoreAfterSynchronousFailure(consumedRequest: false)
        guard !keyframeRequests.isPending else {
            FileHandle.standardError.write(Data("video encoder self-test: unconsumed keyframe request was restored\n".utf8))
            return false
        }
        return true
    }

    private static func makePixelBuffer() -> CVPixelBuffer? {
        var pixelBuffer: CVPixelBuffer?
        let attributes: [CFString: Any] = [
            kCVPixelBufferIOSurfacePropertiesKey: [:],
            kCVPixelBufferMetalCompatibilityKey: true
        ]
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            attributes as CFDictionary,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let pixelBuffer else { return nil }

        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        for plane in 0..<CVPixelBufferGetPlaneCount(pixelBuffer) {
            guard let baseAddress = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, plane) else {
                return nil
            }
            let byteCount = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, plane)
                * CVPixelBufferGetHeightOfPlane(pixelBuffer, plane)
            memset(baseAddress, plane == 0 ? 16 : 128, byteCount)
        }
        return pixelBuffer
    }
}
