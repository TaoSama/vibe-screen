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

    func testInvalidationRejectsNewFramesUntilOutstandingAdmissionsComplete() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let videoToolbox = FakeVideoToolbox()
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))
        XCTAssertEqual(admission.submit(videoToolbox.submit), .submitted(noErr))

        admission.invalidate()

        XCTAssertEqual(admission.snapshot, .init(inFlight: 2, capacity: 2))
        XCTAssertEqual(admission.submit(videoToolbox.submit), .invalidated)
        XCTAssertEqual(videoToolbox.submissionCount, 2)

        videoToolbox.completeFirstFrame()
        XCTAssertEqual(admission.snapshot, .init(inFlight: 1, capacity: 2))
        videoToolbox.completeFirstFrame()
        XCTAssertEqual(admission.inFlightCount, 0)
    }

    func testSnapshotReportsCapacityAndNeverExceedsItDuringConcurrentSubmissionPressure() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let lock = NSLock()
        var acceptedLeases: [VideoEncoderInFlightAdmission.Lease] = []
        var acceptedCount = 0
        var rejectedAtCapacityCount = 0
        var unexpectedInvalidatedCount = 0
        var maximumObservedInFlight = 0
        let start = DispatchSemaphore(value: 0)
        let group = DispatchGroup()

        for _ in 0..<32 {
            group.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                start.wait()
                for _ in 0..<200 {
                    switch admission.submit({ lease in
                        lock.lock()
                        acceptedLeases.append(lease)
                        acceptedCount += 1
                        let snapshot = admission.snapshot
                        maximumObservedInFlight = max(maximumObservedInFlight, snapshot.inFlight)
                        lock.unlock()
                        return noErr
                    }) {
                    case .submitted:
                        break
                    case .atCapacity:
                        lock.lock()
                        rejectedAtCapacityCount += 1
                        let snapshot = admission.snapshot
                        maximumObservedInFlight = max(maximumObservedInFlight, snapshot.inFlight)
                        lock.unlock()
                    case .invalidated:
                        lock.lock()
                        unexpectedInvalidatedCount += 1
                        lock.unlock()
                    }
                }
                group.leave()
            }
        }

        for _ in 0..<32 { start.signal() }

        guard group.wait(timeout: .now() + 5) == .success else {
            XCTFail("Timed out waiting for concurrent submissions")
            return
        }
        XCTAssertEqual(acceptedCount, 2)
        XCTAssertGreaterThan(rejectedAtCapacityCount, 0)
        XCTAssertEqual(unexpectedInvalidatedCount, 0)
        XCTAssertLessThanOrEqual(maximumObservedInFlight, 2)
        XCTAssertEqual(admission.snapshot, .init(inFlight: 2, capacity: 2))

        acceptedLeases.forEach { $0.release() }
        XCTAssertEqual(admission.snapshot, .init(inFlight: 0, capacity: 2))
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
            let observationLock = NSLock()
            var callbackSnapshots: [VideoEncoderInFlightAdmission.Snapshot] = []
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
                    VideoEncoderCallbackLifecycle.process(claimedFrame) { _ in
                        observationLock.lock()
                        callbackSnapshots.append(admission.snapshot)
                        observationLock.unlock()
                    }
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
            guard group.wait(timeout: .now() + 1) == .success else {
                XCTFail("Timed out waiting for callback and teardown race")
                return
            }
            observationLock.lock()
            let observedCallbackSnapshots = callbackSnapshots
            observationLock.unlock()
            XCTAssertTrue(
                observedCallbackSnapshots.allSatisfy { $0 == .init(inFlight: 1, capacity: 1) }
            )
            XCTAssertEqual(registry.count, 0)
            XCTAssertEqual(admission.inFlightCount, 0)
        }
    }

    func testCallbackLifecycleHoldsAdmissionUntilCallbackBodyReturns() throws {
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

        let claimedFrame = try XCTUnwrap(registry.claim(sourceFrameRefcon))
        var snapshotsDuringCallback: [VideoEncoderInFlightAdmission.Snapshot] = []
        VideoEncoderCallbackLifecycle.process(claimedFrame) { _ in
            snapshotsDuringCallback.append(admission.snapshot)
            XCTAssertEqual(admission.submit { _ in noErr }, .atCapacity)
        }

        XCTAssertEqual(snapshotsDuringCallback, [.init(inFlight: 1, capacity: 1)])
        XCTAssertEqual(admission.snapshot, .init(inFlight: 0, capacity: 1))
    }

    func testCallbackLifecycleReleasesAdmissionWhenCallbackBodyReturnsEarly() throws {
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

        let claimedFrame = try XCTUnwrap(registry.claim(sourceFrameRefcon))
        VideoEncoderCallbackLifecycle.process(claimedFrame) { _ in
            XCTAssertEqual(admission.snapshot, .init(inFlight: 1, capacity: 1))
            return
        }

        XCTAssertEqual(admission.snapshot, .init(inFlight: 0, capacity: 1))
    }

    func testAnnexBConverterAppendsValidLengthPrefixedNALUnits() {
        let input: [UInt8] = [
            0, 0, 0, 2, 0xAA, 0xBB,
            0, 0, 0, 1, 0xCC,
        ]
        var output = Data()

        let converted = input.withUnsafeBytes { bytes in
            VideoEncoderAnnexBConverter.appendLengthPrefixedNALUnits(
                from: bytes.baseAddress!,
                lengthAtOffset: input.count,
                totalLength: input.count,
                to: &output
            )
        }

        XCTAssertTrue(converted)
        XCTAssertEqual(
            Array(output),
            [0, 0, 0, 1, 0xAA, 0xBB, 0, 0, 0, 1, 0xCC]
        )
    }

    func testAnnexBConverterRejectsNonContiguousBlockBufferPointer() {
        let input: [UInt8] = [0, 0, 0, 1, 0xAA]
        var output = Data([0xEE])

        let converted = input.withUnsafeBytes { bytes in
            VideoEncoderAnnexBConverter.appendLengthPrefixedNALUnits(
                from: bytes.baseAddress!,
                lengthAtOffset: input.count - 1,
                totalLength: input.count,
                to: &output
            )
        }

        XCTAssertFalse(converted)
        XCTAssertEqual(Array(output), [0xEE])
    }

    func testAnnexBConverterRejectsTruncatedLengthPrefix() {
        let input: [UInt8] = [0, 0, 0]
        var output = Data()

        let converted = input.withUnsafeBytes { bytes in
            VideoEncoderAnnexBConverter.appendLengthPrefixedNALUnits(
                from: bytes.baseAddress!,
                lengthAtOffset: input.count,
                totalLength: input.count,
                to: &output
            )
        }

        XCTAssertFalse(converted)
        XCTAssertTrue(output.isEmpty)
    }

    func testAnnexBConverterRejectsTruncatedNALPayload() {
        let input: [UInt8] = [0, 0, 0, 4, 0xAA, 0xBB]
        var output = Data()

        let converted = input.withUnsafeBytes { bytes in
            VideoEncoderAnnexBConverter.appendLengthPrefixedNALUnits(
                from: bytes.baseAddress!,
                lengthAtOffset: input.count,
                totalLength: input.count,
                to: &output
            )
        }

        XCTAssertFalse(converted)
        XCTAssertTrue(output.isEmpty)
    }

    func testAnnexBConverterRejectsTruncatedNALPayloadAfterValidUnit() {
        let input: [UInt8] = [
            0, 0, 0, 1, 0xAA,
            0, 0, 0, 4, 0xBB,
        ]
        var output = Data()

        let converted = input.withUnsafeBytes { bytes in
            VideoEncoderAnnexBConverter.appendLengthPrefixedNALUnits(
                from: bytes.baseAddress!,
                lengthAtOffset: input.count,
                totalLength: input.count,
                to: &output
            )
        }

        XCTAssertFalse(converted)
        XCTAssertEqual(Array(output), [0, 0, 0, 1, 0xAA])
    }

    func testDrainAfterInvalidationReleasesOnlyRegisteredFrames() {
        let admission = VideoEncoderInFlightAdmission(capacity: 2)
        let registry = VideoEncoderFrameRegistry()
        let owner = VideoEncoderCallbackOwner()

        for timestamp in 1...2 {
            XCTAssertEqual(admission.submit { lease in
                _ = registry.register(
                    VideoEncoder.FrameContext(
                        timestamp: UInt64(timestamp),
                        sessionEpoch: 1,
                        admissionLease: lease
                    ),
                    owner: owner
                )
                return noErr
            }, .submitted(noErr))
        }
        XCTAssertEqual(admission.snapshot, .init(inFlight: 2, capacity: 2))

        admission.invalidate()
        XCTAssertEqual(admission.submit { _ in noErr }, .invalidated)
        XCTAssertEqual(admission.snapshot, .init(inFlight: 2, capacity: 2))

        owner.deactivate()
        XCTAssertEqual(registry.drain(owner: owner), 2)
        XCTAssertEqual(registry.drain(owner: owner), 0)
        XCTAssertEqual(admission.snapshot, .init(inFlight: 0, capacity: 2))
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
