import AppKit
import CryptoKit
import Foundation
import XCTest
import VibeScreenProtocol
@testable import Telemachus

@MainActor
final class ClipboardUIControllerTests: XCTestCase {
    private final class PasteboardSpy: ClipboardPasteboard {
        var stored: String?
        var writeSucceeds = true
        var readCount = 0
        var writeCount = 0
        var lastWritten: String?

        func readString() -> String? {
            readCount += 1
            return stored
        }

        func writeString(_ string: String) -> Bool {
            writeCount += 1
            lastWritten = string
            return writeSucceeds
        }
    }

    private final class PasteboardStorageSpy: ClipboardPasteboardStorage {
        var stored: String?
        var writeSucceeds = true
        var writeCount = 0

        func string(forType dataType: NSPasteboard.PasteboardType) -> String? {
            dataType == .string ? stored : nil
        }

        func writeObjects(_ objects: [NSPasteboardWriting]) -> Bool {
            writeCount += 1
            guard writeSucceeds else { return false }
            if let item = objects.first as? NSPasteboardItem {
                stored = item.string(forType: .string)
            }
            return true
        }
    }

    private final class ServerSpy: ClipboardServer {
        var clipboardAvailable = true
        var shareSucceeds = true
        var requestSucceeds = true
        var expireSucceeds = true
        var sharedTexts: [String] = []
        var sentRequests: [VSClipboardRequest] = []
        var expiredChangeIDs: [Data] = []

        func shareClipboardText(_ text: String) -> Bool {
            sharedTexts.append(text)
            return shareSucceeds
        }

        func sendClipboardRequest(_ request: VSClipboardRequest) -> Bool {
            sentRequests.append(request)
            return requestSucceeds
        }

        func expireClipboardRequest(changeID: Data) -> Bool {
            expiredChangeIDs.append(changeID)
            return expireSucceeds
        }
    }

    private final class AlertSpy: ClipboardAlertPresenter {
        struct Confirmation: Equatable {
            let title: String
            let message: String
            let confirmButtonTitle: String
        }

        struct Information: Equatable {
            let title: String
            let message: String
        }

        var confirmationResult = true
        var confirmations: [Confirmation] = []
        var information: [Information] = []

        nonisolated init() {}

        func presentConfirmation(
            title: String,
            message: String,
            confirmButtonTitle: String
        ) -> Bool {
            confirmations.append(Confirmation(
                title: title,
                message: message,
                confirmButtonTitle: confirmButtonTitle
            ))
            return confirmationResult
        }

        func presentInformation(title: String, message: String) {
            information.append(Information(title: title, message: message))
        }
    }

    private final class TimeoutSchedulerSpy: ClipboardRequestTimeoutScheduling {
        var scheduledAction: (@MainActor () -> Void)?

        nonisolated init() {}

        func schedule(_ action: @escaping @MainActor () -> Void) {
            scheduledAction = action
        }

        func cancel() {
            scheduledAction = nil
        }

        func fire() {
            let action = scheduledAction
            scheduledAction = nil
            action?()
        }
    }

    private func makeController(
        pasteboard: PasteboardSpy,
        alerts: AlertSpy = AlertSpy(),
        timeoutScheduler: ClipboardRequestTimeoutScheduling = TimeoutSchedulerSpy()
    ) -> (ClipboardUIController, NSMenuItem, NSMenuItem, AlertSpy) {
        let share = NSMenuItem(title: "Share", action: nil, keyEquivalent: "")
        let receive = NSMenuItem(title: "Receive", action: nil, keyEquivalent: "")
        let controller = ClipboardUIController(
            pasteboard: pasteboard,
            shareMenuItem: share,
            receiveMenuItem: receive,
            alertPresenter: alerts,
            requestTimeoutScheduler: timeoutScheduler
        )
        return (controller, share, receive, alerts)
    }

    private func bind(
        _ controller: ClipboardUIController,
        server: ServerSpy,
        generation: UInt64 = 1,
        transport: ClipboardTransport = .usb,
        available: Bool = true
    ) {
        controller.bind(
            server: server,
            generation: generation,
            transport: transport,
            clipboardAvailable: available
        )
    }

    private func perform(_ item: NSMenuItem, on controller: ClipboardUIController) {
        guard let action = item.action else {
            XCTFail("Expected menu action")
            return
        }
        _ = controller.perform(action, with: item)
    }

    private func offerMetadata(
        changeID: Data = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount),
        byteLength: UInt64 = 5
    ) -> ClipboardOfferMetadata {
        ClipboardOfferMetadata(
            changeID: changeID,
            originDeviceID: "peer",
            mimeType: ClipboardCore.supportedMIMEType,
            byteLength: byteLength,
            sha256: Data(repeating: 0x02, count: ClipboardCore.sha256ByteCount)
        )
    }

    private func validatedContent(
        changeID: Data = Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount),
        text: String = "hello"
    ) -> ValidatedClipboardContent {
        ValidatedClipboardContent(
            changeID: changeID,
            originDeviceID: "peer",
            mimeType: ClipboardCore.supportedMIMEType,
            text: text,
            sha256: Data(SHA256.hash(data: Data(text.utf8)))
        )
    }

    func testPasteboardAdapterFailedWritePreservesExistingString() {
        let storage = PasteboardStorageSpy()
        storage.stored = "existing"
        storage.writeSucceeds = false
        let adapter = NSPasteboardClipboardAdapter(pasteboard: storage)

        XCTAssertFalse(adapter.writeString("replacement"))

        XCTAssertEqual(storage.writeCount, 1)
        XCTAssertEqual(adapter.readString(), "existing")
    }

    func testPasteboardAdapterSuccessfulWriteReplacesString() {
        let storage = PasteboardStorageSpy()
        storage.stored = "existing"
        let adapter = NSPasteboardClipboardAdapter(pasteboard: storage)

        XCTAssertTrue(adapter.writeString("replacement"))

        XCTAssertEqual(storage.writeCount, 1)
        XCTAssertEqual(adapter.readString(), "replacement")
    }

    func testDirectContentRequiresConfirmationBeforePasteboardWrite() {
        let pasteboard = PasteboardSpy()
        let alerts = AlertSpy()
        alerts.confirmationResult = false
        let (controller, _, receive, _) = makeController(pasteboard: pasteboard, alerts: alerts)
        let server = ServerSpy()
        bind(controller, server: server)
        controller.handleDirectContent(validatedContent(text: "direct paste"), generation: 1)

        perform(receive, on: controller)
        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertEqual(alerts.confirmations.count, 1)

        alerts.confirmationResult = true
        perform(receive, on: controller)
        XCTAssertEqual(pasteboard.writeCount, 1)
        XCTAssertEqual(pasteboard.lastWritten, "direct paste")
        XCTAssertFalse(receive.isEnabled)
    }

    func testOfferClickSendsOneRequestAndWaitsForContent() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)

        perform(receive, on: controller)

        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertEqual(server.sentRequests.map(\.changeID), [metadata.changeID])
        XCTAssertFalse(receive.isEnabled)
    }

    func testRequestFailureIsVisibleAndCanBeRetried() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, alerts) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        server.requestSucceeds = false
        bind(controller, server: server)
        controller.handleOffer(offerMetadata(), generation: 1)

        perform(receive, on: controller)

        XCTAssertEqual(alerts.information.last?.title, "Clipboard Receive Failed")
        XCTAssertTrue(receive.isEnabled)
    }

    func testRequestTimeoutRestoresSameOfferForRetryAndSurfacesFailure() {
        let pasteboard = PasteboardSpy()
        let alerts = AlertSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, _) = makeController(
            pasteboard: pasteboard,
            alerts: alerts,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        bind(controller, server: server)
        controller.handleOffer(offerMetadata(), generation: 1)

        perform(receive, on: controller)
        XCTAssertFalse(receive.isEnabled)

        timeoutScheduler.fire()

        XCTAssertEqual(server.expiredChangeIDs, [offerMetadata().changeID])
        XCTAssertTrue(receive.isEnabled)
        XCTAssertEqual(alerts.information.last?.title, "Clipboard Request Timed Out")

        perform(receive, on: controller)
        XCTAssertEqual(server.sentRequests.count, 2)
    }

    func testTimeoutDoesNotClearApprovalWhenCoreAlreadyConsumedRequest() {
        let pasteboard = PasteboardSpy()
        let alerts = AlertSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, _) = makeController(
            pasteboard: pasteboard,
            alerts: alerts,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        server.expireSucceeds = false
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)

        timeoutScheduler.fire()

        XCTAssertTrue(alerts.information.isEmpty)
        XCTAssertFalse(receive.isEnabled)
        controller.handleContent(
            validatedContent(changeID: metadata.changeID, text: "already queued"),
            generation: 1
        )
        XCTAssertEqual(pasteboard.lastWritten, "already queued")
    }

    func testTimeoutClearsApprovalWhenClipboardBecomesUnavailable() {
        let pasteboard = PasteboardSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, alerts) = makeController(
            pasteboard: pasteboard,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)

        server.clipboardAvailable = false
        timeoutScheduler.fire()

        XCTAssertTrue(server.expiredChangeIDs.isEmpty)
        XCTAssertTrue(alerts.information.isEmpty)
        XCTAssertFalse(receive.isEnabled)
        controller.handleContent(
            validatedContent(changeID: metadata.changeID, text: "late content"),
            generation: 1
        )
        XCTAssertNil(pasteboard.lastWritten)
    }

    func testDirectContentCannotReplaceApprovedInFlightOffer() {
        let pasteboard = PasteboardSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, _) = makeController(
            pasteboard: pasteboard,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)

        controller.handleDirectContent(
            validatedContent(changeID: Data(repeating: 0x09, count: 16), text: "direct"),
            generation: 1
        )
        controller.handleContent(
            validatedContent(changeID: metadata.changeID, text: "approved"),
            generation: 1
        )

        XCTAssertEqual(pasteboard.writeCount, 1)
        XCTAssertEqual(pasteboard.lastWritten, "approved")
        XCTAssertFalse(receive.isEnabled)
    }

    func testLateDirectContentCannotReplaceNewerOfferAfterSupersedingRequest() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        let oldMetadata = offerMetadata(
            changeID: Data(repeating: 0x01, count: ClipboardCore.changeIDByteCount)
        )
        let newMetadata = offerMetadata(
            changeID: Data(repeating: 0x02, count: ClipboardCore.changeIDByteCount)
        )
        controller.handleOffer(oldMetadata, generation: 1)
        perform(receive, on: controller)
        controller.handleOffer(newMetadata, generation: 1)

        controller.handleDirectContent(
            validatedContent(changeID: oldMetadata.changeID, text: "late old content"),
            generation: 1
        )
        perform(receive, on: controller)

        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertEqual(server.sentRequests.map(\.changeID), [oldMetadata.changeID, newMetadata.changeID])
        XCTAssertFalse(receive.isEnabled)
    }

    func testLateDirectContentForSameTimedOutOfferRequiresConfirmation() {
        let pasteboard = PasteboardSpy()
        let alerts = AlertSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, _) = makeController(
            pasteboard: pasteboard,
            alerts: alerts,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)
        timeoutScheduler.fire()

        controller.handleDirectContent(
            validatedContent(changeID: metadata.changeID, text: "late same content"),
            generation: 1
        )
        perform(receive, on: controller)

        XCTAssertEqual(alerts.confirmations.last?.title, "Overwrite Mac Clipboard?")
        XCTAssertEqual(pasteboard.lastWritten, "late same content")
        XCTAssertFalse(receive.isEnabled)
    }

    func testSameIDDirectContentClosesTimeoutHandoffWindowWithoutAutoWrite() {
        let pasteboard = PasteboardSpy()
        let alerts = AlertSpy()
        let timeoutScheduler = TimeoutSchedulerSpy()
        let (controller, _, receive, _) = makeController(
            pasteboard: pasteboard,
            alerts: alerts,
            timeoutScheduler: timeoutScheduler
        )
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)

        controller.handleDirectContent(
            validatedContent(changeID: metadata.changeID, text: "handoff content"),
            generation: 1
        )

        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertTrue(receive.isEnabled)
        perform(receive, on: controller)
        XCTAssertEqual(alerts.confirmations.last?.title, "Overwrite Mac Clipboard?")
        XCTAssertEqual(pasteboard.lastWritten, "handoff content")
    }

    func testMismatchedContentClearsApprovalAndSurfacesFailure() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, alerts) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        controller.handleOffer(offerMetadata(), generation: 1)
        perform(receive, on: controller)
        XCTAssertFalse(receive.isEnabled)

        controller.handleContent(
            validatedContent(changeID: Data(repeating: 0x09, count: 16)),
            generation: 1
        )

        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertFalse(receive.isEnabled)
        XCTAssertEqual(alerts.information.last?.title, "Clipboard Receive Failed")
    }

    func testUnrequestedContentDoesNotClearOfferAndSolicitedContentWritesOnlyAfterRequest() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)

        controller.handleContent(
            validatedContent(changeID: Data(repeating: 0x09, count: 16)),
            generation: 1
        )
        XCTAssertEqual(pasteboard.writeCount, 0)
        XCTAssertTrue(receive.isEnabled)

        perform(receive, on: controller)
        XCTAssertEqual(server.sentRequests.map(\.changeID), [metadata.changeID])

        controller.handleContent(
            validatedContent(changeID: metadata.changeID, text: "solicited"),
            generation: 1
        )
        XCTAssertEqual(pasteboard.lastWritten, "solicited")
    }

    func testPasteboardWriteFailureIsVisible() {
        let pasteboard = PasteboardSpy()
        pasteboard.writeSucceeds = false
        let (controller, _, receive, alerts) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        let metadata = offerMetadata()
        controller.handleOffer(metadata, generation: 1)
        perform(receive, on: controller)

        controller.handleContent(validatedContent(changeID: metadata.changeID), generation: 1)

        XCTAssertEqual(alerts.information.last?.title, "Clipboard Write Failed")
    }

    func testShareReadsPasteboardOnlyOnClickAndSurfacesSendFailure() {
        let pasteboard = PasteboardSpy()
        pasteboard.stored = "copy me"
        let (controller, share, _, alerts) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        server.shareSucceeds = false
        bind(controller, server: server)

        XCTAssertEqual(pasteboard.readCount, 0)
        perform(share, on: controller)

        XCTAssertEqual(pasteboard.readCount, 1)
        XCTAssertEqual(server.sharedTexts, ["copy me"])
        XCTAssertEqual(alerts.information.last?.title, "Clipboard Share Failed")
    }

    func testTrustedLANRequiresConfirmationBeforeShareOrRequest() {
        let pasteboard = PasteboardSpy()
        pasteboard.stored = "private text"
        let alerts = AlertSpy()
        alerts.confirmationResult = false
        let (controller, share, receive, _) = makeController(pasteboard: pasteboard, alerts: alerts)
        let server = ServerSpy()
        bind(controller, server: server, transport: .trustedLAN)

        perform(share, on: controller)
        XCTAssertTrue(server.sharedTexts.isEmpty)
        XCTAssertTrue(alerts.confirmations.last?.message.contains("encrypted application records") == true)

        controller.handleOffer(offerMetadata(), generation: 1)
        perform(receive, on: controller)
        XCTAssertTrue(server.sentRequests.isEmpty)
        XCTAssertTrue(alerts.confirmations.last?.message.contains("encrypted application records") == true)
    }

    func testCapabilitySnapshotDisablesControlsWithoutReadingPasteboard() {
        let pasteboard = PasteboardSpy()
        pasteboard.stored = "must stay local"
        let (controller, share, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server, available: false)

        XCTAssertFalse(share.isEnabled)
        controller.handleOffer(offerMetadata(), generation: 1)
        XCTAssertFalse(receive.isEnabled)
        perform(share, on: controller)
        XCTAssertEqual(pasteboard.readCount, 0)
    }

    func testStaleGenerationEventsAreDroppedAndRebindClearsPending() {
        let pasteboard = PasteboardSpy()
        let (controller, _, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server, generation: 2)

        controller.handleOffer(offerMetadata(), generation: 1)
        controller.handleDirectContent(validatedContent(), generation: 1)
        XCTAssertFalse(receive.isEnabled)

        controller.handleDirectContent(validatedContent(), generation: 2)
        XCTAssertTrue(receive.isEnabled)
        bind(controller, server: server, generation: 3)
        XCTAssertFalse(receive.isEnabled)
    }

    func testUnbindDisablesControlsAndClearsPending() {
        let pasteboard = PasteboardSpy()
        let (controller, share, receive, _) = makeController(pasteboard: pasteboard)
        let server = ServerSpy()
        bind(controller, server: server)
        controller.handleDirectContent(validatedContent(), generation: 1)
        XCTAssertTrue(share.isEnabled)
        XCTAssertTrue(receive.isEnabled)

        controller.unbind()

        XCTAssertFalse(share.isEnabled)
        XCTAssertFalse(receive.isEnabled)
        XCTAssertEqual(pasteboard.writeCount, 0)
    }

    func testMenuItemsAreWiredToController() {
        let pasteboard = PasteboardSpy()
        let (controller, share, receive, _) = makeController(pasteboard: pasteboard)
        XCTAssertTrue(share.target === controller)
        XCTAssertTrue(receive.target === controller)
        XCTAssertNotNil(share.action)
        XCTAssertNotNil(receive.action)
    }
}
