import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class ClipboardCoreFailClosedTests: XCTestCase {
    private let localDeviceID = "host-device"
    private let remoteDeviceID = "peer-device"

    func testHandleOfferRejectsInvalidChangeIDLength() {
        let core = makeCore()
        var offer = validOffer()
        offer.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount - 1)

        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidChangeID)
        }
    }

    func testHandleContentRejectsInvalidChangeIDLength() {
        let core = makeCore()
        var content = validContent()
        content.changeID = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount + 1)

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidChangeID)
        }
    }

    func testHandleOfferRejectsUnsupportedMIME() {
        let core = makeCore()
        var offer = validOffer()
        offer.mimeType = "text/html"

        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .unsupportedMIME("text/html"))
        }
    }

    func testHandleContentRejectsUnsupportedMIME() {
        let core = makeCore()
        var content = validContent()
        content.mimeType = "text/html"

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .unsupportedMIME("text/html"))
        }
    }

    func testHandleOfferRejectsWrongSizedDigest() {
        let core = makeCore()
        var offer = validOffer()
        offer.sha256 = Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount - 1)

        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidDigest)
        }
    }

    func testHandleContentRejectsEmptyContent() {
        let core = makeCore()
        var content = validContent(text: "")
        content.sha256 = sha256(Data())

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .emptyContent)
        }
    }

    func testHandleContentRejectsLocallyGeneratedChangeIDAsFeedbackLoop() throws {
        let core = makeCore()
        let localOffer = try core.prepareOffer(text: "local snapshot")
        var content = validContent(text: "loop")
        content.changeID = localOffer.changeID

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .feedbackLoop)
        }
    }

    func testHandleContentRejectsPreviouslyAcceptedChangeIDAsFeedbackLoop() throws {
        let core = makeCore()
        let changeID = Data(repeating: 0x44, count: ClipboardCore.changeIDByteCount)
        let content = validContent(changeID: changeID, text: "accepted once")
        try core.handleOffer(validOffer(changeID: changeID, text: "accepted once"))
        _ = try core.requestContent(for: changeID)
        XCTAssertFalse(try core.handleContent(content).isDirect)

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .feedbackLoop)
        }
    }

    func testHandleOfferRejectsEmptyOrigin() {
        let core = makeCore()
        var offer = validOffer()
        offer.originDeviceID = ""

        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidOrigin)
        }
    }

    func testHandleContentRejectsEmptyOrigin() {
        let core = makeCore()
        var content = validContent()
        content.originDeviceID = ""

        XCTAssertThrowsError(try core.handleContent(content)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .invalidOrigin)
        }
    }

    func testHandleOfferRejectsZeroByteLength() {
        let core = makeCore()
        var offer = validOffer()
        offer.byteLength = 0

        XCTAssertThrowsError(try core.handleOffer(offer)) { error in
            XCTAssertEqual(error as? ClipboardCoreError, .contentTooLarge(0))
        }
    }

    private func makeCore(maximumBytes: Int = ClipboardCore.localMaximumBytes) -> ClipboardCore {
        ClipboardCore(
            maximumBytes: maximumBytes,
            localDeviceID: localDeviceID,
            remoteDeviceID: remoteDeviceID
        )
    }

    private func validOffer(
        changeID: Data = Data(repeating: 0x10, count: ClipboardCore.changeIDByteCount),
        text: String = "clipboard text"
    ) -> VSClipboardOffer {
        let bytes = Data(text.utf8)
        var offer = VSClipboardOffer()
        offer.changeID = changeID
        offer.originDeviceID = remoteDeviceID
        offer.mimeType = ClipboardCore.supportedMIMEType
        offer.byteLength = UInt64(bytes.count)
        offer.sha256 = sha256(bytes)
        return offer
    }

    private func validContent(
        changeID: Data = Data(repeating: 0x20, count: ClipboardCore.changeIDByteCount),
        text: String = "clipboard text"
    ) -> VSClipboardContent {
        let bytes = Data(text.utf8)
        var content = VSClipboardContent()
        content.changeID = changeID
        content.originDeviceID = remoteDeviceID
        content.mimeType = ClipboardCore.supportedMIMEType
        content.content = bytes
        content.sha256 = sha256(bytes)
        return content
    }

    private func sha256(_ data: Data) -> Data {
        Data(SHA256.hash(data: data))
    }
}
