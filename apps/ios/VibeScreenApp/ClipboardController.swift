import Foundation
import UIKit
import VibeScreenCore
import VibeScreenProtocol

@MainActor
final class ClipboardController: ObservableObject {
    @Published private(set) var pendingRemoteContent: VSClipboardContent?
    private var coordinator = ClipboardTransferCoordinator()

    func prepareOutgoing(originDeviceID: String, policy: ManagedPolicy) throws -> VSClipboardContent {
        let pasteboard = UIPasteboard.general
        guard let string = pasteboard.string else { throw ClipboardControllerError.noSupportedContent }
        return try coordinator.prepareOutgoing(
            content: Data(string.utf8),
            mimeType: "text/plain",
            originDeviceID: originDeviceID,
            operation: .userInitiatedSend,
            policy: policy
        )
    }

    func stage(_ content: VSClipboardContent) {
        pendingRemoteContent = content
    }

    func approvePending(policy: ManagedPolicy) throws {
        guard let pendingRemoteContent else { throw ClipboardControllerError.noPendingContent }
        let validated = try coordinator.acceptIncoming(
            pendingRemoteContent,
            operation: .userApprovedReceive,
            policy: policy
        )
        guard validated.mimeType == "text/plain",
              let string = String(data: validated.content, encoding: .utf8) else {
            throw ClipboardControllerError.noSupportedContent
        }
        UIPasteboard.general.string = string
        self.pendingRemoteContent = nil
    }

    func rejectPending() {
        pendingRemoteContent = nil
    }
}

enum ClipboardControllerError: Error {
    case noSupportedContent
    case noPendingContent
}
