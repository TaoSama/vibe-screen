import AppKit
import VibeScreenProtocol
import XCTest
@testable import Telemachus

@MainActor
final class FileTransferUIControllerTests: XCTestCase {
    private final class ServerSpy: FileTransferServer {
        var fileTransferAvailable = true
        var offers: [(URL, String)] = []

        func offerProtocolV1File(fileURL: URL, mimeType: String) throws {
            offers.append((fileURL, mimeType))
        }
    }

    private final class AlertSpy: FileTransferAlertPresenter {
        struct Warning: Equatable {
            let title: String
            let message: String
        }

        var approvalResult = false
        var approvalRequests: [(String, UInt64, String)] = []
        var cancelApprovalCount = 0
        var information: [(String, String)] = []
        var warnings: [Warning] = []

        nonisolated init() {}

        func presentIncomingFileApproval(fileName: String, byteLength: UInt64, mimeType: String) -> Bool {
            approvalRequests.append((fileName, byteLength, mimeType))
            return approvalResult
        }

        func cancelIncomingFileApproval() {
            cancelApprovalCount += 1
        }

        func presentInformation(title: String, message: String) {
            information.append((title, message))
        }

        func presentWarning(title: String, message: String) {
            warnings.append(Warning(title: title, message: message))
        }
    }

    private func makeController(
        alerts: AlertSpy = AlertSpy()
    ) -> (FileTransferUIController, AlertSpy) {
        let menuItem = NSMenuItem(title: "Send File", action: nil, keyEquivalent: "")
        return (FileTransferUIController(sendMenuItem: menuItem, alertPresenter: alerts), alerts)
    }

    func testUserDeniedIncomingResultDoesNotShowFailureAlert() {
        let (controller, alerts) = makeController()

        controller.handleFileTransferResult(
            direction: .incoming,
            accepted: false,
            reason: ProtocolV1FileTransferError.userDenied.reasonCode
        )

        XCTAssertTrue(alerts.warnings.isEmpty)
        XCTAssertEqual(alerts.cancelApprovalCount, 0)
    }

    func testSessionDeactivatedIncomingResultCancelsApprovalWithoutFailureAlert() {
        let (controller, alerts) = makeController()

        controller.handleFileTransferResult(
            direction: .incoming,
            accepted: false,
            reason: "session_deactivated"
        )

        XCTAssertTrue(alerts.warnings.isEmpty)
        XCTAssertEqual(alerts.cancelApprovalCount, 1)
    }

    func testOtherIncomingFailureShowsFailureAlert() {
        let (controller, alerts) = makeController()

        controller.handleFileTransferResult(
            direction: .incoming,
            accepted: false,
            reason: ProtocolV1FileTransferError.bulkSendFailed.reasonCode
        )

        XCTAssertEqual(alerts.cancelApprovalCount, 1)
        XCTAssertEqual(alerts.warnings.count, 1)
        XCTAssertEqual(alerts.warnings[0].title, "Incoming File Transfer Failed")
        XCTAssertEqual(
            alerts.warnings[0].message,
            "The file transfer data channel could not send the next chunk."
        )
    }

    func testOutgoingFailureUsesOutgoingTitle() {
        let (controller, alerts) = makeController()

        controller.handleFileTransferResult(
            direction: .outgoing,
            accepted: false,
            reason: ProtocolV1FileTransferError.policyDenied.reasonCode
        )

        XCTAssertEqual(alerts.warnings.count, 1)
        XCTAssertEqual(alerts.warnings[0].title, "File Transfer Failed")
        XCTAssertEqual(alerts.warnings[0].message, "File transfer is disabled by the current managed policy.")
    }

    func testMenuValidationReadsLiveServerAvailability() {
        let server = ServerSpy()
        let menuItem = NSMenuItem(title: "Send File", action: nil, keyEquivalent: "")
        let controller = FileTransferUIController(sendMenuItem: menuItem, alertPresenter: AlertSpy())

        controller.bind(server: server, fileTransferAvailable: true)
        XCTAssertTrue(menuItem.isEnabled)
        XCTAssertTrue(controller.validateMenuItem(menuItem))

        server.fileTransferAvailable = false

        XCTAssertFalse(controller.validateMenuItem(menuItem))
        XCTAssertFalse(menuItem.isEnabled)
    }

    func testMenuValidationEnablesWhenLiveServerAvailabilityBecomesAvailable() {
        let server = ServerSpy()
        server.fileTransferAvailable = false
        let menuItem = NSMenuItem(title: "Send File", action: nil, keyEquivalent: "")
        let controller = FileTransferUIController(sendMenuItem: menuItem, alertPresenter: AlertSpy())

        controller.bind(server: server, fileTransferAvailable: false)
        XCTAssertFalse(controller.validateMenuItem(menuItem))

        server.fileTransferAvailable = true

        XCTAssertTrue(controller.validateMenuItem(menuItem))
        XCTAssertTrue(menuItem.isEnabled)
    }

    func testRefreshAvailabilityReadsLiveServerAvailability() {
        let server = ServerSpy()
        let menuItem = NSMenuItem(title: "Send File", action: nil, keyEquivalent: "")
        let controller = FileTransferUIController(sendMenuItem: menuItem, alertPresenter: AlertSpy())

        controller.bind(server: server, fileTransferAvailable: true)
        XCTAssertTrue(menuItem.isEnabled)

        server.fileTransferAvailable = false
        controller.refreshAvailability()

        XCTAssertFalse(menuItem.isEnabled)
    }
}
