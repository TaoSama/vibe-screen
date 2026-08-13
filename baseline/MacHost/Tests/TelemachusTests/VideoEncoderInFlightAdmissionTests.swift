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
}
