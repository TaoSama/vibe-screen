import CoreMedia
import CoreVideo
import Foundation

enum VideoEncoderSelfTest {
    private static let width = 640
    private static let height = 480
    private static let frameCount = 120
    private static let settingsUpdateCount = 24

    private final class ResultState: @unchecked Sendable {
        private let lock = NSLock()
        private var settingsSucceeded = true
        private var encodedFrameCount = 0

        func recordSettingsResult(_ succeeded: Bool) {
            guard !succeeded else { return }
            lock.lock()
            settingsSucceeded = false
            lock.unlock()
        }

        func recordEncodedFrame() {
            lock.lock()
            encodedFrameCount += 1
            lock.unlock()
        }

        func snapshot() -> (settingsSucceeded: Bool, encodedFrameCount: Int) {
            lock.lock()
            defer { lock.unlock() }
            return (settingsSucceeded, encodedFrameCount)
        }
    }

    static func run() -> Bool {
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

        group.enter()
        encodeQueue.async {
            for index in 0..<frameCount {
                encoder.encode(
                    pixelBuffer: pixelBuffer,
                    presentationTimeStamp: CMTime(value: CMTimeValue(index), timescale: 60),
                    sessionEpoch: 1
                )
            }
            group.leave()
        }

        group.enter()
        settingsQueue.async {
            for index in 0..<settingsUpdateCount {
                let sharp = index.isMultiple(of: 2)
                let succeeded = encoder.updateSettings(
                    bitrateMbps: sharp ? 35 : 12,
                    quality: sharp ? "high" : "low",
                    gamingBoost: false,
                    frameRate: sharp ? 60 : 30
                )
                result.recordSettingsResult(succeeded)
            }
            group.leave()
        }

        guard group.wait(timeout: .now() + 15) == .success else {
            FileHandle.standardError.write(Data("video encoder self-test: concurrent work timed out\n".utf8))
            return false
        }

        let callbackDeadline = Date().addingTimeInterval(5)
        while result.snapshot().encodedFrameCount == 0, Date() < callbackDeadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        let snapshot = result.snapshot()
        let passed = snapshot.settingsSucceeded && snapshot.encodedFrameCount > 0
        if passed {
            print("video encoder self-test passed (encoded callbacks: \(snapshot.encodedFrameCount))")
        } else {
            let failure = snapshot.settingsSucceeded ? "no encoded callbacks" : "VideoToolbox property update rejected"
            FileHandle.standardError.write(Data(
                "video encoder self-test failed: \(failure) "
                    .appending("(callbacks=\(snapshot.encodedFrameCount))\n")
                    .utf8
            ))
        }
        return passed
    }

    private static func runKeyframeRecoveryStateChecks() -> Bool {
        let keyframeState = VideoEncoderKeyframeRequestState()
        keyframeState.requestKeyframe()
        guard keyframeState.consumePendingRequest() else {
            FileHandle.standardError.write(Data("video encoder self-test: keyframe request was not consumed\n".utf8))
            return false
        }
        guard !keyframeState.hasPendingRequest else {
            FileHandle.standardError.write(Data("video encoder self-test: consumed keyframe request stayed pending\n".utf8))
            return false
        }
        keyframeState.restoreConsumedRequest(true)
        guard keyframeState.hasPendingRequest else {
            FileHandle.standardError.write(Data("video encoder self-test: consumed keyframe request was not restored\n".utf8))
            return false
        }
        guard keyframeState.consumePendingRequest() else {
            FileHandle.standardError.write(Data("video encoder self-test: restored keyframe request was not consumable\n".utf8))
            return false
        }
        keyframeState.restoreConsumedRequest(false)
        guard !keyframeState.hasPendingRequest else {
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
