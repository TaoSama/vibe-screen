import CoreMedia
import CoreVideo
import Foundation
import VibeScreenProtocol

struct InternetProductRealEncodedMediaFrames {
    let keyframe: Data
    let delta: Data
}

enum InternetProductRealEncodedMediaSource {
    enum Failure: Error, LocalizedError {
        case compressionSessionUnavailable
        case pixelBufferCreationFailed
        case timedOutWaitingForKeyframe
        case timedOutWaitingForDelta
        case malformedKeyframe

        var errorDescription: String? {
            switch self {
            case .compressionSessionUnavailable:
                return "VideoToolbox HEVC session unavailable"
            case .pixelBufferCreationFailed:
                return "pixel buffer creation failed"
            case .timedOutWaitingForKeyframe:
                return "no encoded HEVC keyframe within 10s"
            case .timedOutWaitingForDelta:
                return "no encoded HEVC delta frame within 10s"
            case .malformedKeyframe:
                return "keyframe does not start with an Annex-B start code"
            }
        }
    }

    static func makeHEVCFrames(width: Int = 640, height: Int = 480) throws -> InternetProductRealEncodedMediaFrames {
        let encoder = VideoEncoder(
            width: width,
            height: height,
            codec: .hevc,
            bitrateMbps: 20,
            quality: "medium",
            frameRate: 60
        )
        guard encoder.hasActiveCompressionSession else {
            throw Failure.compressionSessionUnavailable
        }

        let frameReceived = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var keyframe: Data?
        var delta: Data?
        encoder.onEncodedFrame = { data, _, isKeyframe, _ in
            lock.lock()
            if isKeyframe, keyframe == nil {
                keyframe = data
            } else if !isKeyframe, delta == nil {
                delta = data
            }
            lock.unlock()
            frameReceived.signal()
        }

        encoder.requestKeyframe()
        guard let firstBuffer = makePixelBuffer(width: width, height: height, luma: 16) else {
            throw Failure.pixelBufferCreationFailed
        }
        encoder.encode(
            pixelBuffer: firstBuffer,
            presentationTimeStamp: CMTime(value: 1, timescale: 60),
            sessionEpoch: 1
        )
        guard waitForFrame(frameReceived, lock: lock, isReady: { keyframe != nil }) else {
            throw Failure.timedOutWaitingForKeyframe
        }

        for frameIndex in 2...8 {
            guard let pixelBuffer = makePixelBuffer(
                width: width,
                height: height,
                luma: UInt8(16 + frameIndex)
            ) else {
                throw Failure.pixelBufferCreationFailed
            }
            encoder.encode(
                pixelBuffer: pixelBuffer,
                presentationTimeStamp: CMTime(value: CMTimeValue(frameIndex), timescale: 60),
                sessionEpoch: 1
            )
            if waitForFrame(frameReceived, lock: lock, isReady: { delta != nil }, timeout: 2) {
                break
            }
        }

        lock.lock()
        let encodedKeyframe = keyframe
        let encodedDelta = delta
        lock.unlock()
        guard let encodedKeyframe else { throw Failure.timedOutWaitingForKeyframe }
        guard let encodedDelta else { throw Failure.timedOutWaitingForDelta }
        guard encodedKeyframe.starts(with: Data([0x00, 0x00, 0x00, 0x01])) else {
            throw Failure.malformedKeyframe
        }
        return InternetProductRealEncodedMediaFrames(
            keyframe: encodedKeyframe,
            delta: encodedDelta
        )
    }

    private static func waitForFrame(
        _ semaphore: DispatchSemaphore,
        lock: NSLock,
        isReady: () -> Bool,
        timeout: TimeInterval = 10
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            lock.lock()
            let ready = isReady()
            lock.unlock()
            if ready { return true }
            let remaining = max(0.01, deadline.timeIntervalSinceNow)
            let waitMilliseconds = Int(min(remaining, 0.25) * 1_000)
            _ = semaphore.wait(timeout: .now() + .milliseconds(waitMilliseconds))
        }
        lock.lock()
        let ready = isReady()
        lock.unlock()
        return ready
    }

    private static func makePixelBuffer(width: Int, height: Int, luma: UInt8) -> CVPixelBuffer? {
        var pixelBuffer: CVPixelBuffer?
        let attributes: [CFString: Any] = [
            kCVPixelBufferIOSurfacePropertiesKey: [:],
            kCVPixelBufferMetalCompatibilityKey: true,
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
            memset(baseAddress, plane == 0 ? Int32(luma) : 128, byteCount)
        }
        return pixelBuffer
    }
}

/// Offline gate that feeds real VideoToolbox HEVC output through the Protocol v1
/// media record layer and verifies that reassembled records match the original
/// encoded keyframe and delta frame. This does not claim device decoder continuity.
enum InternetProductSessionRealMediaSelfTest {
    static func run() -> Bool {
        do {
            let frames = try InternetProductRealEncodedMediaSource.makeHEVCFrames()
            guard !frames.keyframe.isEmpty, !frames.delta.isEmpty else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: encoded payload was empty\n".utf8
                ))
                return false
            }
            guard frames.keyframe.starts(with: Data([0x00, 0x00, 0x00, 0x01])) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: keyframe does not start with an Annex-B start code\n".utf8
                ))
                return false
            }
            guard frames.delta.starts(with: Data([0x00, 0x00, 0x00, 0x01])) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: delta frame does not start with an Annex-B start code\n".utf8
                ))
                return false
            }

            var codec = try InternetProductProtocolCodec(
                sessionIdentifier: "real-media-self-test",
                sessionEpoch: 1,
                hostID: "host-1",
                hostName: "Real Media Host",
                peerDeviceID: "device-1",
                video: InternetProductVideoConfiguration(
                    codec: .hevc,
                    width: 640,
                    height: 480,
                    framesPerSecond: 60,
                    bitrateKbps: 20_000
                ),
                limits: .standard
            )

            var hello = VSClientHello()
            hello.deviceID = "device-1"
            var range = VSProtocolRange()
            range.minimum = 1
            range.maximum = 1
            hello.supportedProtocols = range
            hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
            hello.requiredCapabilities = Array(InternetProductProtocolCodec.requiredCapabilities)
            hello.codecs = [.hevc]
            var limits = VSResourceLimits()
            limits.maximumEncryptedMediaRecordBytes = UInt32(
                InternetMediaRecordContract.maximumEncryptedRecordBytes
            )
            hello.resourceLimits = limits
            try codec.validate(hello)

            let keyframe = try codec.mediaFrame(
                payload: frames.keyframe,
                timestamp: 1_000,
                isKeyframe: true
            )
            let delta = try codec.mediaFrame(
                payload: frames.delta,
                timestamp: 2_000,
                isKeyframe: false
            )

            guard !keyframe.records.isEmpty, !delta.records.isEmpty else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: media frame produced no records\n".utf8
                ))
                return false
            }

            let decodedKeyframe = try reassemble(records: keyframe.records)
            let decodedDelta = try reassemble(records: delta.records)

            guard decodedKeyframe.headers.allSatisfy({ $0.frameID == decodedKeyframe.headers[0].frameID }) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: keyframe fragment frame IDs are inconsistent\n".utf8
                ))
                return false
            }
            guard decodedDelta.headers.allSatisfy({ $0.frameID == decodedDelta.headers[0].frameID }) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: delta fragment frame IDs are inconsistent\n".utf8
                ))
                return false
            }
            guard decodedKeyframe.headers[0].sessionEpoch == 1, decodedDelta.headers[0].sessionEpoch == 1 else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: fragment session epoch mismatch\n".utf8
                ))
                return false
            }
            guard decodedKeyframe.headers[0].keyframe, !decodedDelta.headers[0].keyframe else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: keyframe flag was not preserved\n".utf8
                ))
                return false
            }
            guard decodedKeyframe.headers[0].codec == .hevc, decodedDelta.headers[0].codec == .hevc else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: codec was not preserved as HEVC\n".utf8
                ))
                return false
            }
            guard decodedKeyframe.payload == frames.keyframe else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: reassembled payload does not match the original HEVC keyframe\n".utf8
                ))
                return false
            }
            guard decodedDelta.payload == frames.delta else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: reassembled payload does not match the original HEVC delta frame\n".utf8
                ))
                return false
            }

            print(
                "phase3 real-media self-test: PASS "
                    + "(hevc=true, keyframe=true, delta=true, "
                    + "keyframePayloadBytes=\(frames.keyframe.count), "
                    + "deltaPayloadBytes=\(frames.delta.count), "
                    + "keyframeFragments=\(keyframe.records.count), "
                    + "deltaFragments=\(delta.records.count), reassembled=true)"
            )
            return true
        } catch {
            FileHandle.standardError.write(Data(
                "phase3 real-media self-test: \(error.localizedDescription)\n".utf8
            ))
            return false
        }
    }

    private static func reassemble(records: [Data]) throws -> (headers: [VSMediaPacketHeader], payload: Data) {
        var fragments: [VSMediaPacketHeader] = []
        var reassembled = Data()
        for record in records {
            let decoded = try ProtocolV1MediaPacketCodec.decode(record)
            fragments.append(decoded.header)
            reassembled.append(decoded.payload)
        }
        return (fragments, reassembled)
    }
}
