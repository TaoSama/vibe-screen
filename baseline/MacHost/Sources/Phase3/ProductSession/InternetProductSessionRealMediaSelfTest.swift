import CoreMedia
import CoreVideo
import Foundation
import VibeScreenProtocol

/// Offline gate that feeds real VideoToolbox HEVC output through the Protocol v1
/// media record layer and verifies that reassembled records match the original
/// encoded keyframe. This does not claim device decoder continuity.
enum InternetProductSessionRealMediaSelfTest {
    static func run() -> Bool {
        do {
            let encoder = VideoEncoder(
                width: 640,
                height: 480,
                codec: .hevc,
                bitrateMbps: 20,
                quality: "medium",
                frameRate: 60
            )
            guard encoder.hasActiveCompressionSession else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: VideoToolbox HEVC session unavailable\n".utf8
                ))
                return false
            }
            guard let pixelBuffer = makePixelBuffer(width: 640, height: 480) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: pixel buffer creation failed\n".utf8
                ))
                return false
            }

            let frameReceived = DispatchSemaphore(value: 0)
            let lock = NSLock()
            var encodedPayload: Data?
            encoder.onEncodedFrame = { data, _, isKeyframe, _ in
                guard isKeyframe else { return }
                lock.lock()
                encodedPayload = data
                lock.unlock()
                frameReceived.signal()
            }
            encoder.requestKeyframe()
            encoder.encode(
                pixelBuffer: pixelBuffer,
                presentationTimeStamp: CMTime(value: 1, timescale: 60),
                sessionEpoch: 1
            )

            guard frameReceived.wait(timeout: .now() + 10) == .success else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: no encoded HEVC keyframe within 10s\n".utf8
                ))
                return false
            }
            let payload: Data
            lock.lock()
            payload = encodedPayload ?? Data()
            lock.unlock()
            guard !payload.isEmpty else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: encoded payload was empty\n".utf8
                ))
                return false
            }
            guard payload.starts(with: [0x00, 0x00, 0x00, 0x01]) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: keyframe does not start with an Annex-B start code\n".utf8
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
            hello.capabilities = Array(InternetProductProtocolCodec.requiredCapabilities).sorted {
                $0.rawValue < $1.rawValue
            }
            hello.requiredCapabilities = hello.capabilities
            hello.codecs = [.hevc]
            var limits = VSResourceLimits()
            limits.maximumEncryptedMediaRecordBytes = UInt32(
                InternetMediaRecordContract.maximumEncryptedRecordBytes
            )
            hello.resourceLimits = limits
            try codec.validate(hello)

            let frame = try codec.mediaFrame(
                payload: payload,
                timestamp: 1_000,
                isKeyframe: true
            )

            guard !frame.records.isEmpty else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: media frame produced no records\n".utf8
                ))
                return false
            }

            var fragments: [VSMediaPacketHeader] = []
            var reassembled = Data()
            for record in frame.records {
                let decoded = try ProtocolV1MediaPacketCodec.decode(record)
                fragments.append(decoded.header)
                reassembled.append(decoded.payload)
            }

            guard fragments.allSatisfy({ $0.frameID == fragments[0].frameID }) else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: fragment frame IDs are inconsistent\n".utf8
                ))
                return false
            }
            guard fragments[0].sessionEpoch == 1 else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: fragment session epoch mismatch\n".utf8
                ))
                return false
            }
            guard fragments[0].keyframe else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: keyframe flag was not preserved\n".utf8
                ))
                return false
            }
            guard fragments[0].codec == .hevc else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: codec was not preserved as HEVC\n".utf8
                ))
                return false
            }
            guard reassembled == payload else {
                FileHandle.standardError.write(Data(
                    "phase3 real-media self-test: reassembled payload does not match the original HEVC keyframe\n".utf8
                ))
                return false
            }

            print(
                "phase3 real-media self-test: PASS "
                    + "(hevc=true, keyframe=true, payloadBytes=\(payload.count), "
                    + "fragments=\(frame.records.count), reassembled=true)"
            )
            return true
        } catch {
            FileHandle.standardError.write(Data(
                "phase3 real-media self-test: \(error.localizedDescription)\n".utf8
            ))
            return false
        }
    }

    private static func makePixelBuffer(width: Int, height: Int) -> CVPixelBuffer? {
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
            memset(baseAddress, plane == 0 ? 16 : 128, byteCount)
        }
        return pixelBuffer
    }
}
