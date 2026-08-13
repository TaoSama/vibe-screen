import CoreMedia
import XCTest
@testable import Telemachus

final class VideoEncoderInFlightAdmissionTests: XCTestCase {
    private final class FakeVideoToolbox {
        var synchronousStatus: OSStatus = noErr
        private(set) var submissionCount = 0
        private var acceptedLeases: [VideoEncoderInFlightAdmission.Lease] = []

        var retainedFrameCount: Int {
            acceptedLeases.count
        }

        func submit(_ lease: VideoEncoderInFlightAdmission.Lease) -> OSStatus {
            submissionCount += 1
            if synchronousStatus == noErr {
                acceptedLeases.append(lease)
            }
            return synchronousStatus
        }

        func completeFirstFrame() {
            acceptedLeases.removeFirst().release()
        }
    }

    func testAcceptedFramesWithoutCallbacksStayAtCapacityAndCompletionRestoresAdmission() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let videoToolbox = FakeVideoToolbox()

        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(admission.submit(videoToolbox.submit), .atCapacity)
        XCTAssertEqual(videoToolbox.retainedFrameCount, 2)
        XCTAssertEqual(videoToolbox.submissionCount, 2)
        XCTAssertEqual(admission.inFlightCount, 2)

        videoToolbox.completeFirstFrame()

        XCTAssertEqual(admission.inFlightCount, 1)
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(videoToolbox.retainedFrameCount, 2)
        XCTAssertEqual(admission.inFlightCount, 2)
    }

    func testSynchronousSubmissionFailureReturnsAdmission() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let videoToolbox = FakeVideoToolbox()
        videoToolbox.synchronousStatus = -1

        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(-1))
        XCTAssertEqual(videoToolbox.retainedFrameCount, 0)
        XCTAssertEqual(admission.inFlightCount, 0)

        videoToolbox.synchronousStatus = noErr
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(admission.inFlightCount, 1)
    }

    func testInvalidationReturnsOutstandingAdmissionsAndRejectsNewFrames() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let videoToolbox = FakeVideoToolbox()
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))

        admission.invalidate()

        XCTAssertEqual(admission.inFlightCount, 0)
        XCTAssertEqual(admission.submit(videoToolbox.submit), .invalidated)
        XCTAssertEqual(videoToolbox.submissionCount, 2)

        videoToolbox.completeFirstFrame()
        videoToolbox.completeFirstFrame()
        XCTAssertEqual(admission.inFlightCount, 0)
    }

    func testAcceptedFrameWithoutCallbackIsDrainedAfterCompletionFailure() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let registry = VideoEncoderFrameRegistry()
        let owner = VideoEncoderCallbackOwner()
        var sourceFrameRefcon: UnsafeMutableRawPointer?

        XCTAssertEqual(admission.submit { lease in
            sourceFrameRefcon = registry.register(
                VideoEncoder.FrameContext(
                    timestamp: 1,
                    sessionEpoch: 2,
                    admissionLease: lease
                ),
                owner: owner
            )
            return noErr
        }, .submitted(noErr))
        XCTAssertEqual(registry.count, 1)
        XCTAssertEqual(admission.inFlightCount, 1)

        // Fake VTCompressionSessionCompleteFrames failure: teardown must own
        // cleanup because VideoToolbox never delivered the accepted callback.
        owner.deactivate()
        XCTAssertEqual(registry.drain(owner: owner), 1)

        XCTAssertEqual(registry.count, 0)
        XCTAssertEqual(admission.inFlightCount, 0)
        XCTAssertNil(registry.claim(sourceFrameRefcon))
    }

    func testSynchronousFailureClaimsRegisteredFrameExactlyOnce() {
        let admission = VideoEncoderInFlightAdmission(capacity: 1)
        let registry = VideoEncoderFrameRegistry()
        let owner = VideoEncoderCallbackOwner()
        var sourceFrameRefcon: UnsafeMutableRawPointer?

        let result = admission.submit { lease in
            sourceFrameRefcon = registry.register(
                VideoEncoder.FrameContext(
                    timestamp: 1,
                    sessionEpoch: 1,
                    admissionLease: lease
                ),
                owner: owner
            )
            return -1
        }
        if case .submitted(let status) = result, status != noErr,
           let claimedFrame = registry.claim(sourceFrameRefcon) {
            claimedFrame.context.completeSubmission()
        }

        XCTAssertEqual(result, .submitted(-1))
        XCTAssertEqual(registry.count, 0)
        XCTAssertEqual(admission.inFlightCount, 0)
        XCTAssertNil(registry.claim(sourceFrameRefcon))
    }

    func testCallbackAndTeardownRaceClaimsFrameExactlyOnce() {
        for iteration in 0..<100 {
            let admission = VideoEncoderInFlightAdmission(capacity: 1)
            let registry = VideoEncoderFrameRegistry()
            let owner = VideoEncoderCallbackOwner()
            var sourceFrameRefcon: UnsafeMutableRawPointer?
            XCTAssertEqual(admission.submit { lease in
                sourceFrameRefcon = registry.register(
                    VideoEncoder.FrameContext(
                        timestamp: UInt64(iteration),
                        sessionEpoch: 1,
                        admissionLease: lease
                    ),
                    owner: owner
                )
                return noErr
            }, .submitted(noErr))

            let start = DispatchSemaphore(value: 0)
            let group = DispatchGroup()
            group.enter()
            DispatchQueue.global().async {
                start.wait()
                if let claimedFrame = registry.claim(sourceFrameRefcon) {
                    claimedFrame.context.completeSubmission()
                }
                group.leave()
            }
            group.enter()
            DispatchQueue.global().async {
                start.wait()
                owner.deactivate()
                registry.drain(owner: owner)
                group.leave()
            }
            start.signal()
            start.signal()
            XCTAssertEqual(group.wait(timeout: .now() + 1), .success)
            XCTAssertEqual(registry.count, 0)
            XCTAssertEqual(admission.inFlightCount, 0)
        }
    }

    func testLateCallbackAfterTeardownIsNoOp() {
        let admission = VideoEncoderInFlightAdmission(capacity: 1)
        let registry = VideoEncoderFrameRegistry()
        let owner = VideoEncoderCallbackOwner()
        var sourceFrameRefcon: UnsafeMutableRawPointer?
        XCTAssertEqual(admission.submit { lease in
            sourceFrameRefcon = registry.register(
                VideoEncoder.FrameContext(
                    timestamp: 1,
                    sessionEpoch: 1,
                    admissionLease: lease
                ),
                owner: owner
            )
            return noErr
        }, .submitted(noErr))

        owner.deactivate()
        XCTAssertEqual(registry.drain(owner: owner), 1)

        XCTAssertNil(registry.claim(sourceFrameRefcon))
        XCTAssertNil(registry.claim(sourceFrameRefcon))
        XCTAssertEqual(registry.count, 0)
        XCTAssertEqual(admission.inFlightCount, 0)
    }
}
