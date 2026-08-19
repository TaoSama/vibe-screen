import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ClipboardCoreTests: XCTestCase {
    private let localDeviceID = "host-device"
    private let remoteDeviceID = "peer-device"

    private func makeCore(maximumBytes: Int = ClipboardCore.localMaximumBytes) -> ClipboardCore {
        ClipboardCore(
            maximumBytes: maximumBytes,
            localDeviceID: localDeviceID,
            remoteDeviceID: remoteDeviceID
        )
    }

    private func changeID(_ bytes: [UInt8]) -> Data {
        Data(bytes)
    }

    private func sha256(_ data: Data) -> Data {
        Data(SHA256.hash(data: data))
    }

    // MARK: - Size limits

    func testMaximumBytesIsCappedAtOneMiB() {
        let core = makeCore(maximumBytes: 10 * 1024 * 1024)
        XCTAssertEqual(core.maximumBytes, ClipboardCore.localMaximumBytes)
    }

    func testMaximumBytesHonorsPeerLimitBelowHostCap() {
        let core = makeCore(maximumBytes: 256)
        XCTAssertEqual(core.maximumBytes, 256)
    }

    func testPrepareOfferRejectsEmptyText() {
        let core = makeCore()
        XCTAssertThrowsError(try core.prepareOffer(text: "")) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .emptyContent)
        }
    }

    func testPrepareOfferRejectsTextLargerThanMaximumBytes() {
        let core = makeCore(maximumBytes: 8)
        let text = String(repeating: "a", count: 9)
        XCTAssertThrowsError(try core.prepareOffer(text: text)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .contentTooLarge(9))
        }
    }

    func testHandleOfferRejectsByteLengthAboveMaximumBytes() {
        let core = makeCore(maximumBytes: 8)
        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 9
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)
        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .contentTooLarge(9))
        }
    }

    func testHandleOfferRejectsUInt64MaximumWithoutTrapping() {
        let core = makeCore()
        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64.max
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)
        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .contentTooLarge(Int.max))
        }
    }

    func testHandleContentRejectsContentLargerThanMaximumBytes() {
        let core = makeCore(maximumBytes: 8)
        let bytes = Data(repeating: 0x61, count: 9)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .contentTooLarge(9))
        }
    }

    // MARK: - Origin

    func testHandleOfferRejectsMismatchedOrigin() {
        let core = makeCore()
        var offer = VSClipboardOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        offer.originDeviceID = "not-the-peer"
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 4
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)
        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidOrigin)
        }
    }

    func testHandleContentRejectsMismatchedOrigin() {
        let core = makeCore()
        let bytes = Data("hi".utf8)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        content.originDeviceID = "not-the-peer"
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidOrigin)
        }
    }

    // MARK: - Digest

    func testHandleContentRejectsWrongDigest() {
        let core = makeCore()
        let bytes = Data("hello".utf8)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = Data(repeating: 0x00, count: ClipboardCore.sha256ByteCount)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidDigest)
        }
    }

    func testHandleContentRejectsWrongSizedDigest() {
        let core = makeCore()
        let bytes = Data("hello".utf8)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes).prefix(16)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidDigest)
        }
    }

    // MARK: - Strict UTF-8

    func testHandleContentRejectsInvalidUTF8() {
        let core = makeCore()
        // 0xFF is never valid in UTF-8.
        var bytes = Data("hello".utf8)
        bytes.append(0xFF)
        var content = VSClipboardContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidUTF8)
        }
    }

    // MARK: - Offer -> request -> content (solicited)

    func testSolicitedOfferRequestContentRoundTrip() throws {
        let core = makeCore()
        let text = "solicited clipboard text"
        let bytes = Data(text.utf8)
        let cid = Data(repeating: 0x0A, count: ClipboardCore.changeIDByteCount)

        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        let metadata = try core.handleOffer(offer)
        XCTAssertEqual(metadata.changeID, cid)
        XCTAssertEqual(metadata.byteLength, UInt64(bytes.count))

        let request = try core.requestContent(for: cid)
        XCTAssertEqual(request.changeID, cid)

        var content = VSClipboardContent()
        content.changeID = cid
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        let result = try core.handleContent(content)
        XCTAssertFalse(result.isDirect)
        XCTAssertEqual(result.validated.text, text)
        XCTAssertEqual(result.validated.originDeviceID, remoteDeviceID)
        XCTAssertEqual(result.validated.sha256, sha256(bytes))
    }

    // MARK: - Direct (unsolicited) content

    func testDirectContentIsFlaggedAndNotConsumedAsSolicited() throws {
        let core = makeCore()
        let text = "direct content"
        let bytes = Data(text.utf8)
        let cid = Data(repeating: 0x0B, count: ClipboardCore.changeIDByteCount)

        var content = VSClipboardContent()
        content.changeID = cid
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        let result = try core.handleContent(content)
        XCTAssertTrue(result.isDirect)
        XCTAssertEqual(result.validated.text, text)

        // The same change ID can still go through the offer/request flow
        // because direct content is not remembered for loop detection.
        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        XCTAssertNoThrow(try core.handleOffer(offer))
    }

    // MARK: - Duplicate / consumed requests

    func testMakeContentReturnsNilAfterFirstServe() throws {
        let core = makeCore()
        let offer = try core.prepareOffer(text: "once only")
        let first = core.makeContent(for: offer.changeID)
        XCTAssertNotNil(first)
        XCTAssertEqual(first?.changeID, offer.changeID)

        let second = core.makeContent(for: offer.changeID)
        XCTAssertNil(second, "A consumed snapshot must not be served twice")
    }

    func testMakeContentReturnsNilForUnknownChangeID() {
        let core = makeCore()
        XCTAssertNil(core.makeContent(for: Data(repeating: 0xCC, count: ClipboardCore.changeIDByteCount)))
    }

    func testRequestContentRejectsUnknownChangeID() {
        let core = makeCore()
        XCTAssertThrowsError(try core.requestContent(for: Data(repeating: 0xDD, count: ClipboardCore.changeIDByteCount))) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .unknownChangeID)
        }
    }

    func testDuplicateOfferWithMatchingMetadataIsIdempotent() throws {
        let core = makeCore()
        let cid = Data(repeating: 0x0E, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 5
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)

        let first = try core.handleOffer(offer)
        let second = try core.handleOffer(offer)
        XCTAssertEqual(first, second)
    }

    func testDuplicateOfferWithConflictingMetadataRejected() throws {
        let core = makeCore()
        let cid = Data(repeating: 0x0F, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = cid
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 5
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)
        _ = try core.handleOffer(offer)

        offer.byteLength = 6
        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .offerMetadataMismatch)
        }
    }

    // MARK: - Bounded pending state

    func testNewOfferEvictsPreviousOffer() throws {
        let core = makeCore()
        let firstID = Data(repeating: 0x10, count: ClipboardCore.changeIDByteCount)
        let secondID = Data(repeating: 0x20, count: ClipboardCore.changeIDByteCount)
        for changeID in [firstID, secondID] {
            var offer = VSClipboardOffer()
            offer.changeID = changeID
            offer.originDeviceID = remoteDeviceID
            offer.mimeType = ClipboardCore.supportedMIMEType
            offer.byteLength = 1
            offer.sha256 = Data(repeating: changeID.first!, count: ClipboardCore.sha256ByteCount)
            try core.handleOffer(offer)
        }

        XCTAssertThrowsError(try core.requestContent(for: firstID)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .unknownChangeID)
        }
        XCTAssertEqual(try core.requestContent(for: secondID).changeID, secondID)
    }

    func testNewRequestEvictsPreviousRequest() throws {
        let core = makeCore()
        let firstID = Data(repeating: 0x31, count: ClipboardCore.changeIDByteCount)
        let secondID = Data(repeating: 0x32, count: ClipboardCore.changeIDByteCount)
        for changeID in [firstID, secondID] {
            var offer = VSClipboardOffer()
            offer.changeID = changeID
            offer.originDeviceID = remoteDeviceID
            offer.mimeType = ClipboardCore.supportedMIMEType
            offer.byteLength = 1
            offer.sha256 = sha256(Data("x".utf8))
            try core.handleOffer(offer)
            _ = try core.requestContent(for: changeID)
        }

        var firstContent = VSClipboardContent()
        firstContent.changeID = firstID
        firstContent.originDeviceID = remoteDeviceID
        firstContent.mimeType = ClipboardCore.supportedMIMEType
        firstContent.content = Data("x".utf8)
        firstContent.sha256 = sha256(firstContent.content)
        XCTAssertTrue(try core.handleContent(firstContent).isDirect)

        var secondContent = firstContent
        secondContent.changeID = secondID
        XCTAssertFalse(try core.handleContent(secondContent).isDirect)
    }

    func testDuplicateRequestIsRejected() throws {
        let core = makeCore()
        let changeID = Data(repeating: 0x41, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 1
        offer.sha256 = sha256(Data("x".utf8))
        try core.handleOffer(offer)
        _ = try core.requestContent(for: changeID)

        XCTAssertThrowsError(try core.requestContent(for: changeID)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .duplicateRequest)
        }
    }

    func testExpiredRequestCanRetryAndLateContentBecomesDirect() throws {
        let core = makeCore()
        let changeID = Data(repeating: 0x42, count: ClipboardCore.changeIDByteCount)
        let bytes = Data("retry".utf8)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        try core.handleOffer(offer)
        _ = try core.requestContent(for: changeID)

        XCTAssertFalse(core.expireRequest(for: Data(repeating: 0x43, count: 16)))
        XCTAssertTrue(core.expireRequest(for: changeID))

        var lateContent = VSClipboardContent()
        lateContent.changeID = changeID
        lateContent.originDeviceID = remoteDeviceID
        lateContent.mimeType = ClipboardCore.supportedMIMEType
        lateContent.content = bytes
        lateContent.sha256 = sha256(bytes)
        XCTAssertTrue(try core.handleContent(lateContent).isDirect)
        XCTAssertEqual(try core.requestContent(for: changeID).changeID, changeID)
    }

    func testSolicitedContentRejectsOfferMetadataMismatch() throws {
        let core = makeCore()
        let changeID = Data(repeating: 0x51, count: ClipboardCore.changeIDByteCount)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = 1
        offer.sha256 = sha256(Data("x".utf8))
        try core.handleOffer(offer)
        _ = try core.requestContent(for: changeID)

        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = Data("y".utf8)
        content.sha256 = sha256(content.content)
        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .offerMetadataMismatch)
        }
    }

    func testOneMiBBoundaryIsAcceptedAndOneByteMoreIsRejected() throws {
        let core = makeCore()
        let exact = String(repeating: "a", count: ClipboardCore.localMaximumBytes)
        XCTAssertNoThrow(try core.prepareOffer(text: exact))

        let oversized = exact + "a"
        XCTAssertThrowsError(try core.prepareOffer(text: oversized)) { error in
            XCTAssertEqual(
                error as? ClipboardCoreError,
                .contentTooLarge(ClipboardCore.localMaximumBytes + 1)
            )
        }
    }

    // MARK: - Reset

    func testResetClearsSnapshotOffersRequestsAndHistory() throws {
        let core = makeCore()
        let offer = try core.prepareOffer(text: "before reset")
        XCTAssertNotNil(core.makeContent(for: offer.changeID))

        let remoteCID = Data(repeating: 0x09, count: ClipboardCore.changeIDByteCount)
        var remoteOffer = VSClipboardOffer()
        remoteOffer.changeID = remoteCID
        remoteOffer.originDeviceID = remoteDeviceID
        remoteOffer.mimeType = ClipboardCore.supportedMIMEType
        remoteOffer.byteLength = 1
        remoteOffer.sha256 = Data(repeating: 0x09, count: ClipboardCore.sha256ByteCount)
        try core.handleOffer(remoteOffer)

        core.reset()

        // Local snapshot is gone.
        XCTAssertNil(core.makeContent(for: offer.changeID))
        // Pending offer is gone, so requesting it fails as unknown.
        XCTAssertThrowsError(try core.requestContent(for: remoteCID)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .unknownChangeID)
        }
        // History is gone, so the previously seen local change ID can be
        // re-offered by the peer without triggering feedback-loop rejection.
        var echoed = VSClipboardOffer()
        echoed.changeID = offer.changeID
        echoed.originDeviceID = remoteDeviceID
        echoed.mimeType = ClipboardCore.supportedMIMEType
        echoed.byteLength = 1
        echoed.sha256 = Data(repeating: 0x01, count: ClipboardCore.sha256ByteCount)
        XCTAssertNoThrow(try core.handleOffer(echoed))
    }

    // MARK: - Feedback loop

    func testLocallyGeneratedChangeIDRejectedWhenEchoedBack() throws {
        let core = makeCore()
        let offer = try core.prepareOffer(text: "loop check")

        var echoed = VSClipboardOffer()
        echoed.changeID = offer.changeID
        echoed.originDeviceID = remoteDeviceID
        echoed.mimeType = ClipboardCore.supportedMIMEType
        echoed.byteLength = UInt64(Data("loop check".utf8).count)
        echoed.sha256 = sha256(Data("loop check".utf8))
        XCTAssertThrowsError(try core.handleOffer(echoed)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .feedbackLoop)
        }
    }
}
